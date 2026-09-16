FROM python:3.12-slim

WORKDIR /app

# System dependencies for pymupdf / chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Data and model cache directories (mounted as volumes at runtime)
RUN mkdir -p /app/data /app/chroma_data /app/models

# Hugging Face model cache for FlagEmbedding reranker
ENV HF_HOME=/app/models

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
