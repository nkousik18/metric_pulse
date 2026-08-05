"""
LLM client factory for the `synthesize` node. One place for provider/model
choice so future recalibration (docs/scoping.md Section 10.3) doesn't require
hunting through investigation/nodes.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_groq import ChatGroq  # noqa: E402

from config.settings import GROQ_API_KEY, GROQ_MODEL  # noqa: E402
from investigation.schemas import SynthesisOutput  # noqa: E402


def get_synthesis_llm():
    """
    Returns a chat model bound to SynthesisOutput via structured output
    (tool-calling based -- explicit `method='function_calling'` sidesteps a
    known incompatibility between LangChain's default strict-JSON-schema mode
    and some Groq-hosted models).
    """
    llm = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0)
    return llm.with_structured_output(SynthesisOutput, method='function_calling')
