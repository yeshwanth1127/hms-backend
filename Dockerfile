FROM node:22-alpine AS staff-ui
WORKDIR /staff-web
COPY staff-web/package*.json ./
RUN npm ci --ignore-scripts
COPY staff-web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY --from=staff-ui /app/staff_static ./app/staff_static
COPY STAFF_WORKSPACE_UX_DECISION_BOOK.md GROWTH_UX_DECISION_BOOK.md ./
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
