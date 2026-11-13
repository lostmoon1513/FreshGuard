# Verification nodes (M3)

Plain async functions in `backend/app/engine/nodes/`; M4 wires them into LangGraph. Each takes a
frozen `ClaimWork` (or list) and returns an updated copy. Providers arrive through `Deps`.

| Order | Node | File | LLM? | Notes |
|---|---|---|---|---|
| 1 | extract_claims | extract.py | yes | claims need a verbatim `answer_span` |
| 2 | classify_volatility | volatility.py | yes (light) | code guard; default slow |
| 3 | generate_queries | queries.py | yes (light) | max 3 queries; fallback = claim text |
| 4 | retrieve_evidence | retrieve.py | no | parallel searches, URL dedupe |
| 5 | validate_sources | sources.py | no | tiering, ranking, page fetch |
| 6 | compare_stance | stance.py | yes | one call per claim |
| 7 | check_quote_integrity | integrity.py | no | verbatim substring or discard |
| 8 | decide | decide.py | no | `rules.decide_claim` |
| 9 | suggest_correction | correction.py | yes | STALE only, grounded |
| - | assemble_result | assemble.py | no | worst label wins |

Routing helpers: `needs_search` (skip static), `needs_reformulation` (no sources after round 1,
no outage -> one more query round, then UNVERIFIABLE).

Tests: `backend/tests/unit/nodes/` (per node, plus `test_pipeline.py` end-to-end with fakes using
the test-only sequential runner `_runner.py`). Run: `python -m pytest tests/unit/nodes -q`.

## Graph (M4)
`backend/app/engine/graph/`: `steps.py` (nodes + routers), `builder.py` (LangGraph wiring),
`runner.py` (`verify(graph, deps, request)`).

```
START -> extract --error--> fail -> END
          |--no claims--> assemble -> END
          v
   classify -> queries -> retrieve -> validate --some claim has no usable source-->
        reformulate -> retrieve_retry -> validate_retry -> stance
   validate --otherwise--> stance -> integrity -> decide -> correct -> assemble -> END
```
Usage: `graph = build_graph(deps); result = await verify(graph, deps, VerificationRequest(...))`.