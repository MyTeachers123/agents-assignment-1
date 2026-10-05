"""
Research Crew Configuration

Wires the four agents and tasks into a sequential pipeline:
Query Expander -> Source Hunter -> Synthesizer -> Report Writer

Two deterministic safeguards wrap the LLM pipeline:
1. warm_up_vector_store(): opens the ChromaDB collection once before the crew
   starts. CrewAI may run several tool calls in parallel; without a warm-up
   they race to initialise the client and some fail with
   "Could not connect to tenant default_tenant".
2. rebuild_references(): rewrites the References section from the citations
   actually used in the text, so the reference list can never contain
   uncited papers or miss cited ones.
"""

# Load environment variables BEFORE importing crewai
from dotenv import load_dotenv
load_dotenv()

import re

from crewai import Crew, Process

from agents import query_expander, source_hunter, synthesizer, report_writer
from tasks.task_definitions import create_research_tasks, PAPERS


def warm_up_vector_store() -> None:
    """Initialise the shared ChromaDB collection once, before parallel tool calls."""
    try:
        from tools.paper_rag_tool import _get_collection
        _get_collection()
    except Exception as e:  # the tool itself reports errors to the agent
        print(f"[warm-up] vector store not ready: {e}")


def _is_cited(paper: dict, body: str) -> bool:
    """Return True if the paper's (Author, Year) citation appears in the body."""
    short = re.escape(paper["short"])
    year = paper["year"]
    pattern = rf"{short},?\s*\(?{year}"
    if not re.search(pattern, body):
        return False
    # ReAct and Tree of Thoughts share "Yao et al., 2023": disambiguate by name
    if paper["id"] == "react_2023":
        return "ReAct" in body or "Tree of Thought" not in body
    if paper["id"] == "tot_2023":
        return "Tree of Thought" in body
    return True


def rebuild_references(report: str) -> str:
    """Replace the References section with entries for papers cited in the text."""
    if not PAPERS:
        return report

    match = re.search(r"^#{1,3}\s*References\s*$", report, flags=re.MULTILINE | re.IGNORECASE)
    body = report[: match.start()] if match else report

    cited = [p for p in PAPERS if _is_cited(p, body)]
    if not cited:
        return report

    cited.sort(key=lambda p: p["short"].lower())
    refs = "\n".join(f"- {p['reference']}" for p in cited)
    return body.rstrip() + "\n\n## References\n" + refs + "\n"


def create_research_crew(research_question: str) -> Crew:
    """Create a Research Crew configured for the given question."""
    tasks = create_research_tasks(research_question)

    return Crew(
        agents=[query_expander, source_hunter, synthesizer, report_writer],
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )


def run_research(research_question: str) -> str:
    """Execute the research crew and return the final report as Markdown."""
    if not research_question or not research_question.strip():
        raise ValueError("Research question must not be empty.")

    warm_up_vector_store()
    crew = create_research_crew(research_question.strip())
    result = crew.kickoff()
    return rebuild_references(str(result))


# Allow running crew.py directly for testing
if __name__ == "__main__":
    test_question = "What are the main approaches to building AI agents that can reason and act?"
    print(f"Testing crew with question: {test_question}\n")
    report = run_research(test_question)
    print("\n" + "=" * 50)
    print("FINAL REPORT:")
    print("=" * 50)
    print(report)
