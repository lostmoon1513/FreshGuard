"""Wires `Steps` into a LangGraph StateGraph.

    extract -> classify -> queries -> retrieve -> validate --(some claim has no usable source)-->
        reformulate -> retrieve_retry -> validate_retry -> stance
    validate --(otherwise)--> stance -> integrity -> decide -> correct -> assemble -> END
    extract --(provider error)--> fail -> END;  extract --(no claims)--> assemble

langgraph is imported inside `build_graph`, so importing the engine never requires it.
"""

from __future__ import annotations

from typing import Any

from app.engine.graph.steps import GraphState, Steps
from app.engine.nodes import Deps

CHAIN = (
    ("classify", "queries"),
    ("queries", "retrieve"),
    ("retrieve", "validate"),
    ("reformulate", "retrieve_retry"),
    ("retrieve_retry", "validate_retry"),
    ("validate_retry", "stance"),
    ("stance", "integrity"),
    ("integrity", "decide"),
    ("decide", "correct"),
    ("correct", "assemble"),
)


def build_graph(deps: Deps) -> Any:
    """Return the compiled graph. Call `await graph.ainvoke(initial_state)`."""
    from langgraph.graph import END, START, StateGraph

    steps = Steps(deps)
    graph = StateGraph(GraphState)
    for name in (
        "extract", "classify", "queries", "retrieve", "validate", "reformulate",
        "retrieve_retry", "validate_retry", "stance", "integrity", "decide", "correct",
        "assemble", "fail",
    ):  # fmt: skip
        graph.add_node(name, getattr(steps, name))
    graph.add_edge(START, "extract")
    graph.add_conditional_edges(
        "extract",
        steps.after_extract,
        {"fail": "fail", "classify": "classify", "assemble": "assemble"},
    )
    for src, dst in CHAIN:
        graph.add_edge(src, dst)
    graph.add_conditional_edges(
        "validate", steps.after_validate, {"reformulate": "reformulate", "stance": "stance"}
    )
    graph.add_edge("assemble", END)
    graph.add_edge("fail", END)
    return graph.compile()