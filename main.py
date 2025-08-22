import os, tempfile, subprocess, re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="CreatorHoop")

# Serve static UI from /public
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")
if os.path.isdir(PUBLIC_DIR):
    app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")

@app.get("/")
def home():
    idx = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return {"ok": True, "msg": "UI not found, but API is running."}

# ---------- Models ----------
class Profile(BaseModel):
    platform: str
    url: HttpUrl

class JobReq(BaseModel):
    user_id: str
    mode: str  # "collector" | "creative"
    profiles: List[Profile]
    window: str  # "7d" | "21d" | "60d"
    num_scripts: int
    creative: Optional[Dict[str, Any]] = None

class TranscribeReq(BaseModel):
    url: HttpUrl

# ---------- Data types ----------
Post = Dict[str, Any]  # {platform_post_id, url, posted_at, views, likes, comments, duration_sec}

# ---------- Window parsing ----------
def parse_window(window: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    m = re.fullmatch(r"(\d+)d", window.strip().lower())
    days = int(m.group(1)) if m else 21
    start = now - timedelta(days=days)
    return (start, now)

# ---------- Scoring ----------
def compute_baseline(posts: List[Post]) -> float:
    if not posts:
        return 1.0
    views = [max(int(p.get("views") or 0), 0) for p in posts][:10]
    avg = sum(views) / max(len(views), 1)
    return max(avg, 1.0)

def score_post(post: Post, baseline: float) -> float:
    views = max(int(post.get("views") or 0), 0)
    likes = max(int(post.get("likes") or 0), 0)
    comments = max(int(post.get("comments") or 0), 0)
    eng = (likes + comments) / max(views, 1)
    growth = (views - baseline) / max(baseline, 1)
    score = 100.0 * (0.6 * growth + 0.4 * eng)
    return round(score, 2)

# ---------- MOCK scrapers (replace later with real scraping) ----------
def mock_fetch_instagram_posts(profile_url: str, start: datetime, end: datetime) -> List[Post]:
    base = profile_url.rstrip("/")
    posts = []
    for i in range(5):
        posts.append({
            "platform_post_id": f"ig_{i}",
            "url": f"{base}/reel/{1000+i}",
            "posted_at": (end - timedelta(days=i+1)).isoformat(),
            "views": 120000 + i * 5000,
            "likes": 5400 + i * 130,
            "comments": 200 + i * 10,
            "duration_sec": 22 + i
        })
    return posts

def mock_fetch_tiktok_posts(profile_url: str, start: datetime, end: datetime) -> List[Post]:
    base = profile_url.rstrip("/")
    posts = []
    for i in range(5):
        posts.append({
            "platform_post_id": f"tt_{i}",
            "url": f"{base}/video/{2000+i}",
            "posted_at": (end - timedelta(days=i+2)).isoformat(),
            "views": 98000 + i * 6200,
            "likes": 4300 + i * 110,
            "comments": 180 + i * 8,
            "duration_sec": 18 + i
        })
    return posts

def filter_by_window(posts: List[Post], start: datetime, end: datetime) -> List[Post]:
    keep: List[Post] = []
    for p in posts:
        try:
            dt = datetime.fromisoformat(str(p.get("posted_at")))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if start <= dt <= end:
            keep.append(p)
    return keep

def select_top_posts(all_posts: List[Post], num_scripts: int) -> List[Post]:
    baseline = compute_baseline(all_posts)
    ranked = []
    for p in all_posts:
        if int(p.get("duration_sec") or 0) < 5 or int(p.get("views") or 0) <= 0:
            continue
        s = score_post(p, baseline)
        q = p.copy()
        q["score"] = s
        ranked.append(q)
    ranked.sort(key=lambda x: (x.get("score", 0), x.get("views", 0)), reverse=True)
    return ranked[: max(1, min(num_scripts, 5))]

# ---------- Single-link transcribe (stub) ----------
@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    return {
        "items": [{
            "url": str(req.url),
            "metrics": {"views": None, "likes": None, "comments": None, "score": None},
            "script": "Ejemplo de transcripción (conecta tu ASR para texto real). Hook <3s... Desarrollo... CTA..."
        }]
    }

# ---------- Job start: scrape + rank + (stub) transcribe ----------
@app.post("/job/start")
def job_start(req: JobReq):
    try:
        # 1) Window
        start, end = parse_window(req.window)

        # 2) Collect posts across profiles (mock for now)
        all_posts: List[Post] = []
        for pr in (req.profiles or [])[:3]:
            url = str(pr.url)
            platform = pr.platform.lower()
            if platform == "instagram":
                posts = mock_fetch_instagram_posts(url, start, end)
            else:
                posts = mock_fetch_tiktok_posts(url, start, end)
            posts = filter_by_window(posts, start, end)
            all_posts.extend(posts)

        # 3) Fallback demo if nothing
        if not all_posts:
            demo = []
            for i in range(req.num_scripts):
                demo.append({
                    "url": f"https://example.com/post/{i+1}",
                    "metrics": {"views": 100000+i*1000, "likes": 5000+i*50, "comments": 200+i*5, "score": 80.0+i},
                    "script": f"[DEMO] Guion {i+1}: Hook <3s... Desarrollo... CTA..."
                })
            return JSONResponse({"items": demo})

        # 4) Rank and pick Top-N
        top_posts = select_top_posts(all_posts, req.num_scripts)

        # 5) Transcribe each Top post (stub for now)
        items = []
        for p in top_posts:
            transcript_text = "(Transcripción pendiente) — conecta tu transcriptor interno aquí."
            script_text = transcript_text if req.mode == "collector" else "(Adaptación pendiente) — usa Guideon aquí a partir de la transcripción."
            items.append({
                "url": p["url"],
                "metrics": {
                    "views": p.get("views"),
                    "likes": p.get("likes"),
                    "comments": p.get("comments"),
                    "score": p.get("score")
                },
                "script": script_text
            })

        return JSONResponse({"items": items})
    except Exception as e:
        return JSONResponse({"error": "job_start_failed", "detail": str(e)}, status_code=500)

@app.get("/health")
def health():
    return {"status": "ok"}
