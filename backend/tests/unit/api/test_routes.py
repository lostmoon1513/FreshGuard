"""HTTP-level tests. They need fastapi + httpx (the project's real dependencies) and are skipped
where those are missing."""

import asyncio
import time
from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.app import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.memory import InMemoryStore  # noqa: E402
from app.schemas.labels import Label  # noqa: E402
from app.services.verification_service import VerificationService  # noqa: E402
from tests.unit._factories import completed_result  # noqa: E402

KEY = {"X-API-Key": "k1"}
BODY = {"question": "Who runs Acme?", "answer": "Jon Lee runs Acme.", "metadata": {"m": "1"}}


def make_client(*, delay: float = 0.0, key: str | None = "k1", rate: int = 1000):
    async def run(request, rid):
        await asyncio.sleep(delay)
        return completed_result(rid, Label.STALE, correction="Priya Raman runs Acme.")

    settings = Settings(
        llm_provider="fake",
        search_provider="fake",
        freshguard_api_key=key,
        rate_limit_per_minute=rate,
    )
    service = VerificationService(
        InMemoryStore(), run, clock=lambda: datetime.now(UTC), max_concurrent=3
    )
    return TestClient(create_app(service, settings))


def test_health_needs_no_key():
    with make_client() as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_auth_required_and_error_shape():
    with make_client() as client:
        r = client.post("/v1/verifications", json=BODY)
        assert r.status_code == 401
        assert r.json() == {
            "error": {"code": "unauthorized", "message": "Missing or invalid API key."}
        }
        assert client.get("/v1/verifications", headers={"X-API-Key": "bad"}).status_code == 401


def test_auth_disabled_when_no_key_configured():
    with make_client(key=None) as client:
        assert client.post("/v1/verifications", json=BODY).status_code == 202


def test_submit_returns_202_then_poll_until_completed():
    with make_client(delay=0.05) as client:
        r = client.post("/v1/verifications", json=BODY, headers=KEY)
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "pending" and body["id"]
        assert r.headers["X-Request-ID"]
        for _ in range(100):
            got = client.get(f"/v1/verifications/{body['id']}", headers=KEY)
            if got.json()["status"] == "completed":
                break
            time.sleep(0.05)
        data = got.json()
        assert got.status_code == 200 and data["label"] == "stale"
        assert data["metadata"] == {"m": "1"} and data["suggested_correction"]
        assert data["claims"][0]["evidence"][0]["integrity_ok"] is True


def test_wait_true_returns_200_with_result():
    with make_client() as client:
        r = client.post("/v1/verifications?wait=true&timeout=5", json=BODY, headers=KEY)
        assert r.status_code == 200 and r.json()["status"] == "completed"


def test_wait_true_times_out_with_202():
    with make_client(delay=3) as client:
        r = client.post("/v1/verifications?wait=true&timeout=1", json=BODY, headers=KEY)
        assert r.status_code == 202 and r.json()["status"] in ("pending", "running")


def test_validation_errors_are_422_in_our_format():
    with make_client() as client:
        r = client.post("/v1/verifications", json={"question": "q", "answer": ""}, headers=KEY)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "validation_error" and "answer" in err["message"]
        bad_meta = {**BODY, "metadata": {"k": "x" * 300}}
        assert client.post("/v1/verifications", json=bad_meta, headers=KEY).status_code == 422
        assert (
            client.post("/v1/verifications?timeout=0&wait=true", json=BODY, headers=KEY).status_code
            == 422
        )


def test_unknown_id_and_unknown_route_use_error_format():
    with make_client() as client:
        r = client.get("/v1/verifications/nope", headers=KEY)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        r = client.get("/v1/nothing", headers=KEY)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_list_with_paging_and_label_filter():
    with make_client() as client:
        ids = []
        for _ in range(3):
            r = client.post("/v1/verifications?wait=true&timeout=5", json=BODY, headers=KEY)
            ids.append(r.json()["id"])
        page = client.get("/v1/verifications?limit=2", headers=KEY).json()
        assert len(page["items"]) == 2 and page["next_before"]
        rest = client.get(
            f"/v1/verifications?limit=2&before={page['next_before']}", headers=KEY
        ).json()
        assert len(rest["items"]) == 1 and rest["next_before"] is None
        assert client.get("/v1/verifications?label=fresh", headers=KEY).json()["items"] == []
        assert client.get("/v1/verifications?label=bogus", headers=KEY).status_code == 422
        assert client.get("/v1/verifications?limit=0", headers=KEY).status_code == 422


def test_rate_limit_returns_429_with_retry_after():
    with make_client(rate=2) as client:
        codes = [
            client.post("/v1/verifications", json=BODY, headers=KEY).status_code for _ in range(3)
        ]
        assert codes == [202, 202, 429]
        r = client.post("/v1/verifications", json=BODY, headers=KEY)
        assert r.json()["error"]["code"] == "rate_limited" and int(r.headers["Retry-After"]) >= 1


def test_incoming_request_id_is_echoed_only_if_safe():
    with make_client() as client:
        ok = client.get("/health", headers={"X-Request-ID": "abc-123"})
        assert ok.headers["X-Request-ID"] == "abc-123"
        bad = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
        assert bad.headers["X-Request-ID"] != "bad id with spaces"


def test_reverify_creates_new_job_linked_to_original():
    with make_client() as client:
        first = client.post("/v1/verifications", json=BODY, headers=KEY).json()
        again = client.post(f"/v1/verifications/{first['id']}/reverify?wait=true", headers=KEY)
        assert again.status_code == 200
        data = again.json()
        assert data["id"] != first["id"] and data["metadata"]["reverified_from"] == first["id"]
        assert data["metadata"]["m"] == "1" and data["status"] == "completed"


def test_reverify_unknown_id_404_and_needs_key():
    with make_client() as client:
        r = client.post("/v1/verifications/nope/reverify", headers=KEY)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        assert client.post("/v1/verifications/nope/reverify").status_code == 401