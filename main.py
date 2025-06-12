from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import subprocess, os, uuid, whisper

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Carga el modelo ya descargado en build time
model = whisper.load_model("tiny")

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    print("📥 URL:", url)
    video_id = str(uuid.uuid4())
    audio_file = f"{video_id}.mp3"

    # 1) Descargar audio
    cmd = ["yt-dlp","-f","bestaudio","--extract-audio","--audio-format","mp3","-o",audio_file,url]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
        if not os.path.exists(audio_file):
            raise RuntimeError("No se creó el MP3")
    except Exception as e:
        print("❌ yt-dlp error:", e)
        return JSONResponse({"error":"No se pudo descargar audio"}, status_code=400)

    # 2) Transcribir
    try:
        print("✍️ Transcribiendo…")
        res = model.transcribe(audio_file)
        text = res.get("text","")
        print("✅ OK")
    except Exception as e:
        print("❌ Whisper error:", e)
        return JSONResponse({"error":"Transcripción fallida"}, status_code=500)
    finally:
        os.remove(audio_file)

    return {"transcription": text}

@app.get("/")
def root():
    return {"message":"API activa"}
