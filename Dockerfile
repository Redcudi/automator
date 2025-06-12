# Usa una imagen oficial de Python slim
FROM python:3.11-slim

# Evita prompts interactivos durante apt-get
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# 1) Instala ffmpeg para procesar audio
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 2) Copia y instala dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --upgrade yt-dlp

# 3) Pre-descarga el modelo tiny de Whisper en build time
RUN python - <<EOF
import whisper
whisper.load_model("tiny")
EOF

# 4) Copia el resto del código
COPY . .

# 5) Expone el puerto (Railway inyecta $PORT)
EXPOSE 8000

# 6) Arranca Uvicorn usando la variable $PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]