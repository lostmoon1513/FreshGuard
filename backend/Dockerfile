FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Install dependencies and the app. The build context is the backend/ folder.
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# One process on purpose: verification jobs run in-process (see docs/DECISIONS.md D32).
# Render and Railway provide $PORT; default 8000 for local `docker run`.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]