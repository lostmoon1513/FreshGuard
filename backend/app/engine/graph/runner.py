"""`verify`: run one verification through a compiled graph. Never raises."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.engine.nodes import Deps, fail_result
from app.schemas.verification import VerificationRequest, VerificationResult

log = logging.getLogger(__name__)


async def verify(
    graph: Any, deps: Deps, request: VerificationRequest, *, result_id: str | None = None
) -> VerificationResult:
    """Always returns a VerificationResult: COMPLETED, or FAILED with a generic message.
    Internal exception details go to the log, never into the result."""
    rid = result_id or uuid.uuid4().hex
    created = deps.clock()
    try:
        final = await graph.ainvoke(
            {
                "result_id": rid,
                "question": request.question,
                "answer": request.answer,
                "created_at": created,
            }
        )
        result = final["result"]
        if not isinstance(result, VerificationResult):
            raise TypeError("graph returned no result")
        return result
    except Exception:
        log.exception("Verification graph crashed")
        return fail_result(rid, "Verification failed unexpectedly.", created, deps.clock())