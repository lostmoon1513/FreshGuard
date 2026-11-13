import subprocess
import sys

import freshguard


def test_public_api_is_exported():
    for name in freshguard.__all__:
        assert hasattr(freshguard, name), name
    assert freshguard.LABELS == ("fresh", "stale", "potentially_stale", "unverifiable")
    assert issubclass(freshguard.AuthError, freshguard.FreshGuardError)
    assert issubclass(freshguard.VerificationTimeout, freshguard.FreshGuardError)


def test_importing_the_package_does_not_import_httpx():
    code = "import sys, freshguard; sys.exit(1 if 'httpx' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0