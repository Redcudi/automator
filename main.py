from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import subprocess
import os
import uuid
import whisper

app = FastAPI()

# CORS abierto para tu frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Carga el modelo una sola vez al arrancar
try:
    model = whisper.load_model("tiny")
    print("✅ Modelo Whisper cargado")
except Exception as e:
    print("❌ No se pudo cargar Whisper:", e)
    model = None

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    if model is None:
        raise HTTPException(500, "Modelo no disponible")

    print("📥 Recibido URL:", url)
    video_id = str(uuid.uuid4())
    audio_file = f"{video_id}.mp3"

    # 1) Descarga el audio con yt-dlp
    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "--extract-audio",
        "--audio-format", "mp3",
        "-o", audio_file,
        url
    ]
    try:
        print("⬇️ Ejecutando yt-dlp...")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("🪵 yt-dlp stdout:", res.stdout)
        print("⚠️ yt-dlp stderr:", res.stderr)
        if res.returncode != 0 or not os.path.exists(audio_file):
            raise RuntimeError(f"yt-dlp falló (code {res.returncode})")
    except Exception as e:
        print("❌ Error descarga audio:", e)
        return JSONResponse({"error": "No se pudo descargar el audio"}, status_code=400)

    # 2) Transcribe con Whisper
    try:
        print("✍️ Transcribiendo audio...")
        result = model.transcribe(audio_file)
        text = result.get("text", "")
        print("✅ Transcripción completada")
    except Exception as e:
        print("❌ Error al transcribir:", e)
        return JSONResponse({"error": "Error en la transcripción"}, status_code=500)
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)
            print("🗑️ Audio temporal eliminado")

    return {"transcription": text}


@app.get("/")
def root():
    return {"message": "API activa"}
