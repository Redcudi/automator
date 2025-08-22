
import os, tempfile, subprocess
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from typing import Optional, List

try:
    from faster_whisper import WhisperModel
    HAVE_WHISPER = True
except Exception:
    HAVE_WHISPER = False

app = FastAPI(title="CreatorHoop")

PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")
if os.path.isdir(PUBLIC_DIR):
    app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")

@app.get("/")
def home():
    idx = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return {"ok": True, "msg": "UI not found, but API is running."}

class TranscribeReq(BaseModel):
    url: HttpUrl

@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    # Minimal fake response to prove UI wiring works.
    return {
        "items": [{
            "url": str(req.url),
            "metrics": {"views": 5300, "likes": 310, "comments": 25, "score": 84.3},
            "script": "Ejemplo de transcripción (conecta tu ASR para texto real). Hook <3s... Desarrollo... CTA..."
        }]
    }

@app.get("/health")
def health():
    return {"status": "ok"}
