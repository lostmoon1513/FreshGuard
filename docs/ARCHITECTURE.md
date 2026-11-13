# Architecture (summary)

```
Developer app --(Python SDK, HTTP)--> FastAPI /v1 --> services/ --> engine (LangGraph)
                                                         |
                                                         +--> db/ (PostgreSQL)
```

Verification graph (built in M3 and M4):

```
START -> extract_claims -> classify_volatility
      -> [any volatile claims?] no  -> decide
                                yes -> generate_queries -> retrieve_evidence (fan-out per claim)
                                    -> validate_sources -> [usable evidence?]
                                         no, first try  -> generate_queries (reformulate once)
                                         no, second try -> decide (unverifiable)
                                         yes            -> compare_stance
                                    -> check_quote_integrity -> decide -> suggest_correction -> END
```

Dependency rule: `schemas` <- `engine`; `schemas` <- `db`; `engine` and `db` <- `services`;
`services` <- `api`. The engine never imports `api` or `db`.
