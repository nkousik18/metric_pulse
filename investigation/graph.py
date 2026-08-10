"""
Compiles the Phase 1 investigation graph (docs/scoping.md Section 2.4) from
the node/routing functions in nodes.py/routing.py. This is the first place in
the package that actually depends on `langgraph` -- everything else is plain
Python, importable and testable with zero LangGraph dependency.

    START -> detect -> route_after_detection -> {decompose_all, finalize_skip}
    decompose_all -> assess_ambiguity -> route_after_ambiguity -> {drill_down, synthesize}
    drill_down -> synthesize
    synthesize -> route_after_synthesis -> {assess_ambiguity, finalize}
    finalize -> END
    finalize_skip -> END

No checkpointer (docs/scoping.md Section 2.8: optional, purely for
mid-run inspection -- not required, and this graph has no cross-invocation
persistence need).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from investigation.nodes import (  # noqa: E402
    assess_ambiguity,
    decompose_all,
    detect,
    drill_down,
    finalize,
    finalize_skip,
    synthesize,
)
from investigation.routing import (  # noqa: E402
    route_after_ambiguity,
    route_after_detection,
    route_after_synthesis,
)
from investigation.state import InvestigationState  # noqa: E402


def build_investigation_graph():
    graph = StateGraph(InvestigationState)

    graph.add_node('detect', detect)
    graph.add_node('decompose_all', decompose_all)
    graph.add_node('assess_ambiguity', assess_ambiguity)
    graph.add_node('drill_down', drill_down)
    graph.add_node('synthesize', synthesize)
    graph.add_node('finalize', finalize)
    graph.add_node('finalize_skip', finalize_skip)

    graph.add_edge(START, 'detect')
    graph.add_conditional_edges('detect', route_after_detection, {
        'decompose_all': 'decompose_all',
        'finalize_skip': 'finalize_skip',
    })
    graph.add_edge('decompose_all', 'assess_ambiguity')
    graph.add_conditional_edges('assess_ambiguity', route_after_ambiguity, {
        'drill_down': 'drill_down',
        'synthesize': 'synthesize',
    })
    graph.add_edge('drill_down', 'synthesize')
    graph.add_conditional_edges('synthesize', route_after_synthesis, {
        'assess_ambiguity': 'assess_ambiguity',
        'finalize': 'finalize',
    })
    graph.add_edge('finalize', END)
    graph.add_edge('finalize_skip', END)

    return graph.compile()


investigation_graph = build_investigation_graph()
