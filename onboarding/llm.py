"""
LLM client factory for Stage B classification. Mirrors investigation/llm.py's
role and reasoning exactly -- same provider, same structured-output method,
same env vars, just a different bound schema.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_groq import ChatGroq  # noqa: E402

from config.settings import GROQ_API_KEY, GROQ_MODEL  # noqa: E402
from onboarding.schemas import SchemaClassification  # noqa: E402


def get_classification_llm():
    """
    Returns a chat model bound to SchemaClassification via structured output.
    method='function_calling' (not the strict-JSON-schema default) for the
    same reason investigation/llm.py uses it: sidesteps a known incompatibility
    between LangChain's strict mode and some Groq-hosted models.
    """
    llm = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0)
    return llm.with_structured_output(SchemaClassification, method='function_calling')
