from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

@app.post("/transcribe")
async def transcribe_video(url: str = Form(...)):
    return {"transcription": f"OK: {url}"}

@app.get("/")
def root():
    return {"message": "API activa"}
