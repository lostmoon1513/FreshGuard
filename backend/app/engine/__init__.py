"""Verification engine (LangGraph).

Responsibility: take (question, answer) and return a verification result.
Rule: this package must never import from `app.api` or `app.db`.
It talks to the outside world only through provider interfaces (LLM, search),
so it can be tested with fakes and no database. Enforced by tests/unit/test_architecture.py.
"""
