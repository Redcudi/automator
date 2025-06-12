from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel
import yt_dlp
import uuid
import os

app = FastAPI()

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Cargar modelo Whisper
model = WhisperModel("tiny", compute_type="int8", cpu_threads=4)

@app.get("/")
def root():
    return {"message": "API activa con Faster-Whisper"}

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    try:
        filename = f"{uuid.uuid4()}.mp3"
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": filename,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "download_sections": ["*00:00:00-00:00:30"],
            "quiet": False,
            "verbose": True,
            "no_warnings": True,
        }

        print(f"📥 Recibiendo: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        print(f"🧠 Transcribiendo archivo: {filename}")
        segments, _ = model.transcribe(filename, beam_size=5)

        transcription = " ".join([segment.text for segment in segments])

        # os.remove(filename)  # 🔁 Temporalmente desactivado para debug
        return {"transcription": transcription.strip()}

    except Exception as e:
        return {"error": "No se pudo transcribir", "detail": str(e)}