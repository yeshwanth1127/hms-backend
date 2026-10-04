FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live')" || exit 1

# Migrations are run explicitly by the deployment job before this service is
# replaced. Keeping them out of process startup prevents concurrent migrations.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
