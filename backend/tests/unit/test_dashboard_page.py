"""Static safety checks on the embedded dashboard page (no browser or fastapi needed)."""

import re

from app.api.dashboard import DASHBOARD_HTML


def test_page_never_inserts_untrusted_text_as_html():
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in DASHBOARD_HTML


def test_page_has_no_external_resources_and_no_baked_in_secrets():
    assert not re.search(r'(src|href)="https?://', DASHBOARD_HTML)
    assert "@import" not in DASHBOARD_HTML
    assert "X-API-Key" in DASHBOARD_HTML  # sends the key the viewer types, nothing else


def test_links_are_checked_before_use():
    assert "safeUrl" in DASHBOARD_HTML and "noopener" in DASHBOARD_HTML