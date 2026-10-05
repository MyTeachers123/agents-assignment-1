"""
Task Definitions for Research Crew

Four sequential tasks, each consuming the outputs of the earlier ones via
`context`:

    expand_task -> search_task -> synthesis_task -> report_task
"""

import json
from pathlib import Path

from crewai import Task

from agents import query_expander, source_hunter, synthesizer, report_writer

PAPER_INDEX = Path(__file__).resolve().parent.parent / "data" / "papers" / "paper_index.json"


def load_papers() -> list[dict]:
    """Load paper metadata and add a ready-made (Author, Year) citation key."""
    try:
        papers = json.loads(PAPER_INDEX.read_text(encoding="utf-8"))["papers"]
    except (OSError, KeyError, json.JSONDecodeError):
        return []

    for p in papers:
        authors = p.get("authors", [])
        first = authors[0].split()[-1] if authors else "Unknown"
        if len(authors) > 2:
            p["short"] = f"{first} et al."
        elif len(authors) == 2:
            p["short"] = f"{first} & {authors[1].split()[-1]}"
        else:
            p["short"] = first
        p["citation"] = f"({p['short']}, {p['year']})"
        p["reference"] = (
            f"{', '.join(authors[:3])}{', et al.' if len(authors) > 3 else ''} "
            f"({p['year']}). *{p['title']}*. {p.get('venue') or 'arXiv'}."
        )
    return papers


PAPERS = load_papers()

# paper_id -> citation + full reference (lets the writer cite correctly
# instead of guessing author names from memory)
PAPER_CATALOG = "\n".join(
    f"- {p['id']} -> {p['citation']} | {p['reference']}" for p in PAPERS
) or "(paper index unavailable)"

# paper -> its own vocabulary (lets the planner write queries that match how
# each paper actually phrases its ideas, which improves vector retrieval)
CONCEPT_CATALOG = "\n".join(
    f"- {p['id']} ({p['title']}): {', '.join(p.get('key_concepts', [])[:6])}"
    for p in PAPERS
) or "(paper index unavailable)"


def create_research_tasks(research_question: str) -> list[Task]:
    """Create the 4-task pipeline for a research question."""

    # =========================================
    # Task 1: Query Expansion
    # =========================================
    expand_task = Task(
        description=(
            f"RESEARCH QUESTION: {research_question}\n\n"
            "Design a search strategy for a corpus of 15 AI-agent papers.\n"
            "1. Restate the question in one sentence and name its core concepts.\n"
            "2. Break it into 4-6 sub-questions covering different angles "
            "(definitions, mechanisms/methods, comparisons, limitations/open problems).\n"
            "3. For each sub-question, write 2 concrete search queries. Use the "
            "papers' OWN terminology from the concept list below (e.g. 'memory "
            "stream', 'verbal reinforcement', 'interleaved reasoning and acting') "
            "rather than generic phrases like 'mechanisms of reasoning'.\n"
            "4. For each sub-question, name the paper ids most likely to answer it. "
            "Aim to cover at least 5 different papers across the plan.\n\n"
            f"Corpus papers and their key concepts:\n{CONCEPT_CATALOG}\n\n"
            "Do NOT answer the question yourself. Only plan the search."
        ),
        expected_output=(
            "A Markdown search plan with:\n"
            "## Core concepts: a bullet list\n"
            "## Sub-questions: a numbered list of 4-6 items; under each, "
            "'Queries:' (2 search strings using paper terminology) and "
            "'Likely papers:' (paper ids)\n"
            "## Scope notes: 1-3 bullets on what is out of scope for this corpus"
        ),
        agent=query_expander,
    )

    # =========================================
    # Task 2: Source Hunting
    # =========================================
    search_task = Task(
        description=(
            f"RESEARCH QUESTION: {research_question}\n\n"
            "Execute the search plan from the previous task using the "
            "'Search Research Papers' tool.\n"
            "Rules:\n"
            "- Run at least one search per sub-question (use k=8).\n"
            "- If results are weak, off-topic, reference lists/author lists, or all "
            "from one or two survey papers, rephrase using a specific paper's "
            "terminology and search again.\n"
            "- Keep 8-12 passages from AT LEAST 5 different papers.\n"
            "- The 'Quote' must be copied character-for-character from the text "
            "between the quotation marks in the tool output, skipping the "
            "'[Paper:...] [Section:...] [Pages:...]' header lines. If the tool "
            "shows '...', keep the '...' and stop there. Never extend, complete, "
            "merge or paraphrase a passage.\n"
            "- The paper id in each heading must be the 'Source:' of THAT passage.\n"
            "- 'Why it matters' may interpret; the Quote may not."
        ),
        expected_output=(
            "A Markdown evidence log:\n"
            "## Evidence\n"
            "For each passage (8-12 total, at least 5 different papers):\n"
            "### E<n>: <paper_id> | Relevance: <score>\n"
            "- Sub-question: <number>\n"
            "- Quote: \"<verbatim text from the tool, '...' kept>\"\n"
            "- Why it matters: <one sentence>\n\n"
            "## Coverage check\n"
            "A table of sub-question -> evidence ids, plus any sub-question with "
            "weak or no evidence marked 'GAP'."
        ),
        agent=source_hunter,
        context=[expand_task],
    )

    # =========================================
    # Task 3: Synthesis
    # =========================================
    synthesis_task = Task(
        description=(
            f"RESEARCH QUESTION: {research_question}\n\n"
            "Analyse the evidence log; do not simply summarise each paper.\n"
            "1. Group the evidence into 3-5 themes that answer the question.\n"
            "2. For each theme, explain how the papers relate: agreement, building "
            "on each other, or tension/trade-off.\n"
            "3. Identify at least 2 debates or contrasting positions.\n"
            "4. Identify at least 2 gaps the corpus does not answer.\n"
            "Rules:\n"
            "- Every claim cites evidence ids AND their paper ids, e.g. "
            "'(E3, react_2023)'. Attribute each E# only to the paper id shown in "
            "its heading -- never to a different paper.\n"
            "- Do not introduce facts that are not in the evidence. If a passage is "
            "truncated or weak, say the evidence is thin.\n"
            "- Do not describe a 1995 paper as discussing LLMs."
        ),
        expected_output=(
            "A Markdown synthesis:\n"
            "## Themes: for each theme, a heading, a 3-5 sentence analysis, and "
            "'Evidence: E# (paper_id), ...'\n"
            "## Consensus: bullets with evidence ids\n"
            "## Debates & tensions: at least 2 bullets with evidence ids\n"
            "## Gaps: at least 2 bullets\n"
            "## Papers used: the list of distinct paper ids cited above\n"
            "## Answer in one paragraph: a direct answer to the research question"
        ),
        agent=synthesizer,
        context=[expand_task, search_task],
    )

    # =========================================
    # Task 4: Report Writing
    # =========================================
    report_task = Task(
        description=(
            f"RESEARCH QUESTION: {research_question}\n\n"
            "Write the final literature review in Markdown using ONLY the "
            "synthesis and evidence log.\n\n"
            "Citation rules:\n"
            "- Convert paper ids to (Author, Year) citations using this catalog:\n"
            f"{PAPER_CATALOG}\n"
            "- Cite ONLY the papers listed under 'Papers used' in the synthesis.\n"
            "- Use the exact citation form from the catalog, e.g. (Yao et al., 2023). "
            "When two papers share a citation (ReAct and Tree of Thoughts are both "
            "Yao et al., 2023), name the method in the sentence, e.g. "
            "'ReAct (Yao et al., 2023)'.\n"
            "- Do not put evidence ids (E1, E2) in the final report.\n"
            "- References list ONLY cited papers; it will be validated automatically.\n"
            "- Short direct quotes must come from the evidence log verbatim.\n\n"
            "Write analytically: compare, contrast, and evaluate rather than "
            "listing papers one by one. Do not attribute modern LLM claims to "
            "Wooldridge & Jennings (1995)."
        ),
        expected_output=(
            "A complete Markdown literature review (about 1,200-1,800 words) with "
            "exactly these sections:\n"
            "# <Title>\n"
            "## Executive Summary (one paragraph answering the question)\n"
            "## 1. Introduction (context, the question, why it matters)\n"
            "## 2. Methodology (multi-agent RAG over a 15-paper corpus: query "
            "expansion, retrieval, synthesis; note limitations)\n"
            "## 3. Findings (one ### subsection per theme, with in-text citations)\n"
            "## 4. Discussion (debates, trade-offs, gaps)\n"
            "## 5. Conclusion\n"
            "## References (alphabetical, full entries from the catalog)"
        ),
        agent=report_writer,
        context=[expand_task, search_task, synthesis_task],
    )

    return [expand_task, search_task, synthesis_task, report_task]
