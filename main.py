from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import subprocess
import os
import uuid
import whisper

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Carga modelo en build-time (ya descargado en Dockerfile)
model = whisper.load_model("tiny")

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    print("📥 URL recibida:", url)
    video_id = str(uuid.uuid4())
    audio_file = f"{video_id}.mp3"

    # Intentos de descarga: primero audio puro, luego contenedor completo
    cmds = [
        ["yt-dlp", "-f", "bestaudio", "--extract-audio", "--audio-format", "mp3", "-o", audio_file, url],
        ["yt-dlp", "-f", "best",     "--extract-audio", "--audio-format", "mp3", "-o", audio_file, url],
    ]
    download_error = None
    for cmd in cmds:
        print("🔄 Probando descarga con:", " ".join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("🪵 stdout:", res.stdout.strip() or "<sin stdout>")
        print("⚠️ stderr:", res.stderr.strip() or "<sin stderr>")
        if res.returncode == 0 and os.path.exists(audio_file):
            download_error = None
            break
        download_error = res.stderr or f"yt-dlp falló con código {res.returncode}"

    if download_error:
        print("❌ Todos los intentos fallaron:", download_error)
        return JSONResponse(
            {"error":"No se pudo descargar audio", "detail": download_error},
            status_code=400
        )

    # Transcribe con Whisper
    try:
        print("✍️ Transcribiendo audio…")
        result = model.transcribe(audio_file)
        text = result.get("text", "")
        print("✅ Transcripción completada")
    except Exception as e:
        print("❌ Error en transcripción:", e)
        return JSONResponse(
            {"error":"Error durante la transcripción", "detail": str(e)},
            status_code=500
        )
    finally:
        os.remove(audio_file)
        print("🗑️ Audio temporal eliminado:", audio_file)

    return {"transcription": text}

@app.get("/")
def root():
    return {"message":"API activa"}