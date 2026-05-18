FROM python:3.11-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir poetry==2.3.3

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false \
 && poetry install --only main --no-interaction --no-ansi

COPY conveyor_belt/ conveyor_belt/

EXPOSE 8000

CMD ["uvicorn", "conveyor_belt.server:app", "--host", "0.0.0.0", "--port", "8000"]
