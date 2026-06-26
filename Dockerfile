FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY agent_core/ ./agent_core/
COPY tools/ ./tools/
COPY api/ ./api/
COPY orchestrator/ ./orchestrator/
COPY sandbox/ ./sandbox/
COPY shared/ ./shared/

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
