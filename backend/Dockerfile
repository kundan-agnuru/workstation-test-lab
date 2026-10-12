FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
COPY runner ./runner
COPY parsers ./parsers
COPY ingestion ./ingestion
COPY analysis ./analysis
RUN pip install --no-cache-dir .
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]

