from fastapi import FastAPI, Form
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

# Carga el modelo en build-time; si falla aquí tu contenedor no arrancará
model = whisper.load_model("tiny")

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    print("📥 URL recibida:", url)
    video_id = str(uuid.uuid4())
    audio_file = f"{video_id}.mp3"

    # Comando yt-dlp
    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "--extract-audio",
        "--audio-format", "mp3",
        "-o", audio_file,
        url
    ]
    try:
        print("⬇️ Ejecutando yt-dlp:", " ".join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("🪵 yt-dlp stdout:", res.stdout.strip() or "<sin stdout>")
        print("⚠️ yt-dlp stderr:", res.stderr.strip() or "<sin stderr>")

        if res.returncode != 0 or not os.path.exists(audio_file):
            raise RuntimeError(f"yt-dlp falló con código {res.returncode}")
    except Exception as e:
        detail = getattr(res, "stderr", str(e))
        print("❌ Error descarga audio:", detail)
        return JSONResponse(
            {"error": "No se pudo descargar audio", "detail": detail},
            status_code=400
        )

    # Transcripción con Whisper
    try:
        print("✍️ Transcribiendo audio…")
        result = model.transcribe(audio_file)
        text = result.get("text", "")
        print("✅ Transcripción completada")
    except Exception as e:
        print("❌ Error en transcripción:", e)
        return JSONResponse(
            {"error": "Error durante la transcripción", "detail": str(e)},
            status_code=500
        )
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)
            print("🗑️ Audio temporal eliminado:", audio_file)

    return {"transcription": text}


@app.get("/")
def root():
    return {"message": "API activa"}