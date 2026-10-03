FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e .

COPY data ./data
COPY app ./app
# Bake the embedding model into the image so the container starts without a download.
RUN python -c "from shift_assistant.config import Settings; from shift_assistant.retrieval.embedder import create_embedder; s = Settings(); create_embedder(s.embedding_model, s.cache_dir)"

EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
