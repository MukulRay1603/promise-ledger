FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
# Run as a non-root user. It owns /srv so the local store and runtime readings can be written.
RUN useradd --create-home --uid 10001 app
COPY --chown=app:app app ./app
COPY --chown=app:app data ./data
RUN chown app:app /srv
USER app
# Cloud Run sets $PORT.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
