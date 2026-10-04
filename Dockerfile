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
# Bake the embedding model into the image so the container starts without a download. Load it
# directly (not via create_embedder, which falls back to keyword matching) so a failed download
# fails the build instead of shipping a degraded image.
RUN python -c "from shift_assistant.config import Settings; from shift_assistant.retrieval.embedder import FastEmbedEmbedder; s = Settings(); FastEmbedEmbedder(s.embedding_model, s.cache_dir / 'fastembed')"

EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
