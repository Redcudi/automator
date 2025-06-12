# Usa una imagen oficial de Python slim
FROM python:3.11-slim

# Evita que apt pregunte durante la instalación
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Instala ffmpeg (necesario para manejar audio en Whisper)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copia y instala dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto de tu código
COPY . .

# Expone el puerto para que Railway (o la plataforma) lo mapee
EXPOSE 8000

# Arranca Uvicorn en el puerto que te asigne la plataforma (o 8000 si no existe)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
