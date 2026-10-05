"""
Shared LLM configuration for all agents.

- LLM_MODEL: default model for planning/synthesis (cheap, fast).
- STRONG_LLM_MODEL: used where faithfulness matters most -- copying verbatim
  evidence (Source Hunter) and turning it into cited prose (Report Writer).
  Set either in .env to switch models without touching agent code.
"""

import os

from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
STRONG_LLM_MODEL = os.getenv("STRONG_MODEL_NAME", "gpt-4o")
