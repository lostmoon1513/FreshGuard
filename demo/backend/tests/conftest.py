import os

# Must be set before `app` is imported. No real Gemini calls happen in tests.
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ["USE_MOCK_FRESHGUARD"] = "true"
os.environ["MOCK_DELAY_SECONDS"] = "0"
