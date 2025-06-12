FROM python:3.11-slim
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# 1) Instala ffmpeg para el audio
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 2) Copia e instala dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) Pre-descarga el modelo tiny de Whisper
RUN python - <<EOF
import whisper
# Esto bajará y cacheará el modelo tiny dentro del contenedor
whisper.load_model("tiny")
EOF

# 4) Copia el resto del código
COPY . .

EXPOSE 8000

# 5) Arranca Uvicorn usando el puerto dinámico
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
