from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel
import yt_dlp
import uuid
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

model = WhisperModel("tiny", compute_type="int8", cpu_threads=4)

@app.get("/")
def root():
    return {"message": "API activa con Faster-Whisper"}

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    try:
        base_id = str(uuid.uuid4())
        output_template = f"{base_id}.%(ext)s"

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "download_sections": ["*00:00:00-00:00:30"],
            "quiet": True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        print("📁 Archivos en el directorio actual:")
        print(os.listdir("."))

        mp3_filename = f"{base_id}.mp3"
        if not os.path.isfile(mp3_filename):
            return {"error": "No se generó el archivo MP3", "files": os.listdir(".")}

        segments, _ = model.transcribe(mp3_filename, beam_size=5)

        transcription = " ".join([segment.text for segment in segments])
        os.remove(mp3_filename)

        return {"transcription": transcription.strip()}

    except Exception as e:
        return {"error": "No se pudo transcribir", "detail": str(e)}