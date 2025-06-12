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
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Verifica que el archivo se haya creado
        if not os.path.exists(filename):
            return {"error": "El archivo de audio no se generó"}

        segments, _ = model.transcribe(filename, beam_size=5)
        transcription = " ".join([segment.text for segment in segments])
        os.remove(filename)

        return {"transcription": transcription.strip()}

    except Exception as e:
        return {"error": "No se pudo transcribir", "detail": str(e)}