# Backend container - works on Render, Railway, Fly.io, Cloud Run, etc.
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg: MarkItDown's audio transcription decodes .mp3/.m4a via pydub, which
# shells out to ffmpeg - without it those uploads fail with "no extractable
# text" in production while working in local dev (.wav needs no ffmpeg).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code (tests/ and the local venv are excluded via .dockerignore)
COPY app ./app

EXPOSE 8000

# Hosts inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
