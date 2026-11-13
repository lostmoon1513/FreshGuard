"""A tiny stand-in for `langgraph.graph`, for tests only.

It implements just what `build_graph` uses (add_node, add_edge, add_conditional_edges, compile,
ainvoke) with the same semantics: nodes return partial state updates that are merged. It lets us
test OUR wiring when langgraph is not installed; the real library is tested when present.
"""

from __future__ import annotations

START = "__start__"
END = "__end__"


class _Compiled:
    def __init__(self, nodes, edges, conditionals):
        self.nodes, self.edges, self.conditionals = nodes, edges, conditionals

    async def ainvoke(self, state):
        state = dict(state)
        current = self.edges[START]
        steps = 0
        while current != END:
            steps += 1
            assert steps < 100, "graph loop"
            state.update(await self.nodes[current](state) or {})
            if current in self.conditionals:
                router, mapping = self.conditionals[current]
                current = mapping[router(state)]
            else:
                current = self.edges[current]
        return state


class StateGraph:
    def __init__(self, state_schema):
        self.nodes, self.edges, self.conditionals = {}, {}, {}

    def add_node(self, name, fn):
        assert name not in self.nodes
        self.nodes[name] = fn

    def add_edge(self, src, dst):
        assert src not in self.edges, f"duplicate edge from {src}"
        self.edges[src] = dst

    def add_conditional_edges(self, src, router, mapping):
        assert src not in self.edges and src not in self.conditionals
        self.conditionals[src] = (router, mapping)

    def compile(self):
        for src in [*self.edges, *self.conditionals]:
            assert src in self.nodes or src == START, f"unknown node {src}"
        targets = [*self.edges.values()] + [
            d for _, m in self.conditionals.values() for d in m.values()
        ]
        for dst in targets:
            assert dst in self.nodes or dst == END, f"unknown target {dst}"
        for name in self.nodes:
            assert name in self.edges or name in self.conditionals, f"{name} has no way out"
        return _Compiled(self.nodes, self.edges, self.conditionals)