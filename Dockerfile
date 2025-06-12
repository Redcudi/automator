FROM python:3.11-slim
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# ffmpeg para audio
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# dependencias + yt-dlp última
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --upgrade yt-dlp

# pre-carga tiny.en
RUN python - <<EOF
import whisper
whisper.load_model("tiny.en")
EOF

# código
COPY . .

EXPOSE 8000
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]