from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import subprocess, os, uuid
import whisper

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True
)

# Carga el modelo tiny.en (más rápido)
model = whisper.load_model("tiny.en")

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    print("📥 Recibido:", url)
    vid_id = str(uuid.uuid4())
    audio_file = f"{vid_id}.mp3"

    # Descarga SOLO primeros 30s; primero try audio-only, luego best-container
    cmds = [
        ["yt-dlp", "-f", "bestaudio", "--download-sections", "*00:00:00-00:00:30",
         "--extract-audio", "--audio-format", "mp3", "-o", audio_file, url],
        ["yt-dlp", "-f", "best",     "--download-sections", "*00:00:00-00:00:30",
         "--extract-audio", "--audio-format", "mp3", "-o", audio_file, url],
    ]
    err = None
    for cmd in cmds:
        print("🔄 Ejecutando:", " ".join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("stdout:", res.stdout or "<vacío>")
        print("stderr:", res.stderr or "<vacío>")
        if res.returncode == 0 and os.path.exists(audio_file):
            err = None
            break
        err = res.stderr or f"yt-dlp falló {res.returncode}"

    if err:
        print("❌ Descarga fallida:", err)
        return JSONResponse({"error":"No se pudo descargar audio","detail":err}, status_code=400)

    # Transcribe con modelo tiny.en
    try:
        print("✍️ Transcribiendo…")
        out = model.transcribe(audio_file)
        text = out.get("text","")
        print("✅ OK")
    except Exception as e:
        print("❌ Error transcripción:", e)
        return JSONResponse({"error":"Error en transcripción","detail":str(e)}, status_code=500)
    finally:
        os.remove(audio_file)

    return {"transcription": text}

@app.get("/")
def root():
    return {"message":"API activa"}