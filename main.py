from fastapi import Request

# ---------- Consent log endpoint ----------
@app.post("/consent/log")
async def consent_log(req: Request):
    try:
        data = await req.json()
        if os.getenv("DEBUG_CONSENT", "0").lower() in ("1","true","yes"):
            print("[CONSENT]", data)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": "consent_log_failed", "detail": str(e)}, status_code=400)

import os, sys, tempfile, subprocess, re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv
import json, time, urllib.parse, requests
load_dotenv()

# CORS (allow WP/Railway embeds)
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")
# Comma-separated list, e.g. "https://creatorhoop.com,https://*.creatorhoop.com,https://automator-production-82f2.up.railway.app"
origins = [o.strip() for o in CORS_ALLOW_ORIGINS.split(',') if o.strip()] or ["*"]

app = FastAPI(title="CreatorHoop")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import re as _re

# ---------- GUIDEON (Claude) settings & prompt cache ----------
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "").strip()
# For your request, default to the Haiku model
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307").strip()
GUIDEON_LANG_DEFAULT = os.getenv("GUIDEON_LANG", "es").strip()
GUIDEON_MAX_TOKENS = int(os.getenv("GUIDEON_MAX_TOKENS", "1400"))
GUIDEON_TEMP = float(os.getenv("GUIDEON_TEMP", "0.5"))


_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_PROMPT_CACHE: Dict[str, str] = {}

def _load_prompt(name: str) -> str:
    """
    Carga y cachea un prompt desde /prompts.
    Nombres esperados:
      - 'guionista' -> prompts/guionista (o .txt)
      - 'sencilla'  -> prompts/sencilla
      - 'reglas_del_usuario' -> prompts/reglas_del_usuario
    """
    key = name.strip().lower()
    if key in _PROMPT_CACHE:
        return _PROMPT_CACHE[key]
    # intenta con y sin .txt
    candidates = [
        os.path.join(_PROMPTS_DIR, key),
        os.path.join(_PROMPTS_DIR, f"{key}.txt"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _PROMPT_CACHE[key] = f.read().strip()
                return _PROMPT_CACHE[key]
        except Exception:
            continue
    _PROMPT_CACHE[key] = ""
    return ""



# ---- Apify configuration flags ----
APIFY_IG_ACTOR = os.getenv("APIFY_IG_ACTOR", "apify~instagram-scraper")
APIFY_TT_ACTOR = os.getenv("APIFY_TT_ACTOR", "apify~tiktok-scraper")
APIFY_ONLY = os.getenv("APIFY_ONLY", "1").lower() in ("1", "true", "yes")  # si True, NO usar fallback yt_dlp
DEBUG_APIFY = os.getenv("DEBUG_APIFY", "0").lower() in ("1", "true", "yes")

if DEBUG_APIFY:
    print("[APIFY] Config:", {
        "APIFY_TOKEN": bool(os.getenv("APIFY_TOKEN")),
        "APIFY_IG_ACTOR": APIFY_IG_ACTOR,
        "APIFY_TT_ACTOR": APIFY_TT_ACTOR,
        "APIFY_ONLY": APIFY_ONLY,
    })

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
    # nuevos campos para ordenamiento
    sort_by: Optional[str] = "score"   # "score" | "views" | "likes" | "comments"
    order: Optional[str] = "desc"      # "asc" | "desc"

class TranscribeReq(BaseModel):
    url: HttpUrl

# --- Inserted: RewriteReq model for per-card rewrites ---
class RewriteReq(BaseModel):
    script: str
    user_prompt: str
    mode: Optional[str] = None
    niche_prompt: Optional[str] = ""
    adaptation_level: Optional[str] = "completa"  # 'simple' | 'completa'
    rules_source: Optional[str] = "guideon"       # 'guideon' | 'custom'
    custom_rules: Optional[str] = ""
    lang: Optional[str] = None

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

# ---------- YouTube provider (auto-select best videos by profile + date range) ----------
def fetch_youtube_posts(profile_url: str, start: datetime, end: datetime) -> List[Post]:
    """
    Usa yt_dlp para extraer la lista de videos de un canal/perfil de YouTube
    y luego obtiene detalles (views, likes, comments, duration) por video.
    Devuelve una lista de Post con campos uniformes para el ranker.
    Acepta URLs de canal, /@handle, /user/, /c/ y playlists.
    """
    try:
        from yt_dlp import YoutubeDL
    except Exception as e:
        # Si no está instalado, no devolvemos nada (el pipeline usará el fallback demo)
        return []

    # 1) Extrae el feed del perfil (lista plana de videos)
    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,     # primero en plano para descubrir entries
        "skip_download": True,
    }
    posts: List[Post] = []
    try:
        with YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(profile_url, download=False)
    except Exception:
        return []

    # Normaliza a entries (puede venir como playlist/canal/usuario)
    entries = []
    if isinstance(info, dict):
        if "entries" in info and isinstance(info["entries"], list):
            entries = info["entries"]
        else:
            # si devuelve un solo video/canal sin entries
            entries = [info]
    else:
        return []

    # 2) Para cada entry dentro de la ventana, pide detalles completos
    detail_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    def parse_upload_dt(v: dict) -> Optional[datetime]:
        # YouTube suele dar upload_date como YYYYMMDD o timestamp
        dt = None
        up = v.get("upload_date")
        if up and isinstance(up, str) and len(up) == 8 and up.isdigit():
            try:
                dt = datetime.strptime(up, "%Y%m%d").replace(tzinfo=timezone.utc)
            except Exception:
                dt = None
        if not dt:
            # intenta con release_timestamp / timestamp
            ts = v.get("release_timestamp") or v.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                except Exception:
                    dt = None
        return dt

    # Itera entries y recoge detalles por video
    for ent in entries:
        # Cada entry plana suele tener 'url' (video id) y/o 'webpage_url'
        video_url = ent.get("webpage_url") or ent.get("url")
        if not video_url:
            continue

        try:
            with YoutubeDL(detail_opts) as ydl:
                v = ydl.extract_info(video_url, download=False)
        except Exception:
            continue

        # Filtra por fecha (ventana seleccionada)
        dt = parse_upload_dt(v)
        if not dt or not (start <= dt <= end):
            continue

        duration = v.get("duration") or 0
        views = v.get("view_count") or 0
        likes = v.get("like_count") or 0
        comments = v.get("comment_count") or 0

        posts.append({
            "platform_post_id": v.get("id") or video_url,
            "url": v.get("webpage_url") or video_url,
            "posted_at": dt.isoformat(),
            "views": int(views) if views else 0,
            "likes": int(likes) if likes else 0,
            "comments": int(comments) if comments else 0,
            "duration_sec": int(duration) if duration else 0,
        })

    return posts


# ---- APIFY generic runner helper ----
def _run_apify_actor(actor: str, token: str, payload: dict, run_timeout_sec: int, debug_tag: str = ""):
    """Ejecuta un actor de Apify y devuelve la lista de items del dataset por defecto.
    Retorna [] si falla o si no hay items. Incluye logs si DEBUG_APIFY.
    """
    run_url = f"https://api.apify.com/v2/acts/{urllib.parse.quote(actor)}/runs?token={token}"
    try:
        run = requests.post(run_url, json=payload, timeout=30)
        run.raise_for_status()
        run_id = (run.json().get("data") or {}).get("id")
        if not run_id:
            if DEBUG_APIFY:
                print(f"[APIFY][{debug_tag}] no run_id (payload schema?)")
            return []
        if DEBUG_APIFY:
            print(f"[APIFY][{debug_tag}] run_id={run_id}")
    except Exception as e:
        if DEBUG_APIFY:
            print(f"[APIFY][{debug_tag}] run start failed: {e}")
        return []

    status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
    deadline = time.time() + run_timeout_sec
    dataset_items = []
    while time.time() < deadline:
        try:
            st = requests.get(status_url, timeout=15).json()
        except Exception:
            break
        data = st.get("data") or {}
        status = data.get("status")
        if DEBUG_APIFY:
            print(f"[APIFY][{debug_tag}] status={status}")
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            dataset_id = data.get("defaultDatasetId")
            if status == "SUCCEEDED" and dataset_id:
                items_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?clean=true"
                try:
                    resp = requests.get(items_url, timeout=60)
                    resp.raise_for_status()
                    dataset_items = resp.json() or []
                    if DEBUG_APIFY:
                        print(f"[APIFY][{debug_tag}] items={len(dataset_items)}")
                except Exception as e:
                    if DEBUG_APIFY:
                        print(f"[APIFY][{debug_tag}] fetch items failed: {e}")
                    dataset_items = []
            break
        time.sleep(2)
    return dataset_items

# ---- APIFY sync endpoint helper ----
def _run_apify_actor_sync_items(actor: str, token: str, payload: dict, debug_tag: str = ""):
    """Ejecuta el actor con el endpoint síncrono `run-sync-get-dataset-items`.
    Devuelve directamente la lista de items (array JSON) o [] si falla.
    """
    url = f"https://api.apify.com/v2/acts/{urllib.parse.quote(actor)}/run-sync-get-dataset-items?token={token}"
    try:
        resp = requests.post(url, json=payload, timeout=120)
        if resp.status_code >= 400:
            if DEBUG_APIFY:
                print(f"[APIFY][{debug_tag}] sync HTTP {resp.status_code}: {resp.text[:300]} ...")
            resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            # Algunos actores pueden devolver NDJSON; intentamos dividir por líneas
            text = resp.text.strip()
            if not text:
                return []
            data = []
            for line in text.splitlines():
                try:
                    data.append(json.loads(line))
                except Exception:
                    pass
        if DEBUG_APIFY:
            print(f"[APIFY][{debug_tag}] sync-items -> {len(data)} items")
        return data if isinstance(data, list) else []
    except Exception as e:
        if DEBUG_APIFY:
            print(f"[APIFY][{debug_tag}] sync run failed: {e}")
        return []


def fetch_instagram_posts_apify(profile_url: str, start: datetime, end: datetime, limit: int = 50) -> List[Post]:
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        return []

    actor = APIFY_IG_ACTOR
    run_timeout = int(os.getenv("APIFY_RUN_TIMEOUT_SEC", "120"))
    limit = max(10, min(limit, 100))

    # Extrae handle de la URL si es posible (para actores que piden usernames)
    m = _re.search(r"instagram\.com/([^/?#]+)", profile_url.rstrip("/"), _re.I)
    handle = m.group(1) if m else None

    use_proxy = os.getenv("APIFY_USE_PROXY", "0").lower() in ("1","true","yes")
    proxy_groups = os.getenv("APIFY_PROXY_GROUPS", "")  # p.ej. 'RESIDENTIAL' o 'SHADER'

    common_proxy = None
    if use_proxy:
        common_proxy = {"useApifyProxy": True}
        if proxy_groups:
            common_proxy["apifyProxyGroups"] = [g.strip() for g in proxy_groups.split(",") if g.strip()]

    # Payload A: directUrls (lo que ya usábamos)
    payloads = []
    pA = {
        "directUrls": [profile_url],
        "resultsLimit": limit,
        "includeComments": False,
        "includeVideoThumbnails": False,
    }
    if common_proxy:
        pA["proxyConfiguration"] = common_proxy
    payloads.append((pA, "IG-A:directUrls"))

    # Payload B: usernames (varios actores usan 'usernames' o 'profiles')
    if handle:
        pB = {
            "usernames": [handle],
            "resultsLimit": limit,
            "includeComments": False,
        }
        if common_proxy:
            pB["proxyConfiguration"] = common_proxy
        payloads.append((pB, "IG-B:usernames"))

        pC = {
            "profiles": [handle],
            "resultsLimit": limit,
        }
        if common_proxy:
            pC["proxyConfiguration"] = common_proxy
        payloads.append((pC, "IG-C:profiles"))

    dataset_items = []
    for payload, tag in payloads:
        # 1) Intento rápido: endpoint síncrono que devuelve items directamente
        dataset_items = _run_apify_actor_sync_items(actor, token, payload, debug_tag=f"{tag}-sync")
        if dataset_items:
            break
        # 2) Fallback: modo asincrónico con polling
        dataset_items = _run_apify_actor(actor, token, payload, run_timeout, debug_tag=f"{tag}-poll")
        if dataset_items:
            break

    posts: List[Post] = []
    for it in (dataset_items or []):
        ts = it.get("timestamp") or it.get("takenAtTimestamp") or it.get("createdAt")
        dt = None
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts if ts < 10**12 else ts/1000, tz=timezone.utc)
                elif isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                dt = None
        if not dt or not (start <= dt <= end):
            continue

        url = it.get("url") or it.get("shortCodeUrl") or it.get("shortCode") or ""
        views = it.get("videoViewCount") or it.get("views") or 0
        likes = it.get("likesCount") or it.get("likes") or 0
        comments = it.get("commentsCount") or it.get("comments") or 0
        duration = it.get("videoDuration") or it.get("duration") or 0

        # NEW: intento de URL directa del video desde el actor
        media_url = (
            it.get("videoUrl")
            or it.get("video_url")
            or (it.get("media") or {}).get("videoUrl")
            or it.get("videoUrlHd")
            or ""
        )

        posts.append({
            "platform_post_id": str(it.get("id") or it.get("shortCode") or url),
            "url": str(url),
            "posted_at": dt.isoformat(),
            "views": int(views) if views else 0,
            "likes": int(likes) if likes else 0,
            "comments": int(comments) if comments else 0,
            "duration_sec": int(duration) if duration else 0,
            "media_url": str(media_url) if media_url else ""
        })
    return posts

def fetch_tiktok_posts_apify(profile_url: str, start: datetime, end: datetime, limit: int = 50) -> List[Post]:
    """
    Trae posts de un perfil de TikTok usando el actor clockworks~tiktok-scraper.
    Requiere pasar 'profiles' (usernames sin @) y 'resultsPerPage'. Soporta filtros de fecha.
    """
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        return []

    actor = os.getenv("APIFY_TT_ACTOR", "clockworks~tiktok-scraper")
    run_timeout = int(os.getenv("APIFY_RUN_TIMEOUT_SEC", "120"))
    limit = max(1, min(limit, 100))

    # Limpia URL y extrae handle (sin @)
    clean_url = profile_url.split('?', 1)[0].rstrip('/')
    m = _re.search(r"tiktok\.com/@([^/?#]+)", clean_url, _re.I)
    handle = m.group(1) if m else None
    if not handle:
        return []

    # Proxy opcional de Apify
    use_proxy = os.getenv("APIFY_USE_PROXY", "0").lower() in ("1","true","yes")
    proxy_groups = os.getenv("APIFY_PROXY_GROUPS", "")
    common_proxy = None
    if use_proxy:
        common_proxy = {"useApifyProxy": True}
        if proxy_groups:
            common_proxy["apifyProxyGroups"] = [g.strip() for g in proxy_groups.split(",") if g.strip()]

    # Payload recomendado por el schema del actor:
    # https://apify.com/clockworks/tiktok-scraper/input-schema
    payload = {
        "profiles": [handle],                 # <— usernames sin @
        "resultsPerPage": limit,              # cuántos videos por perfil
        "profileSorting": "latest",          # ordenar por recientes
        "excludePinnedPosts": True,           # evita fijados
        # Filtros de fecha (funcionan con sorting latest/oldest)
        "oldestPostDateUnified": start.date().isoformat(),  # YYYY-MM-DD
        "newestPostDate": end.date().isoformat(),           # YYYY-MM-DD
        # No descargues binarios para ahorrar tiempo/costo
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
        "shouldDownloadSubtitles": False,
        "shouldDownloadAvatars": False,
        "shouldDownloadMusicCovers": False,
    }
    if common_proxy:
        payload["proxyConfiguration"] = common_proxy

    # 1) Intento síncrono
    items = _run_apify_actor_sync_items(actor, token, payload, debug_tag="TT-profiles-sync")
    # 2) Fallback con polling si hizo falta
    if not items:
        items = _run_apify_actor(actor, token, payload, run_timeout, debug_tag="TT-profiles-poll")

    posts: List[Post] = []
    for it in (items or []):
        # fechas: createTime (epoch) o createTimeISO
        ts = it.get("createTime") or it.get("createTimeISO")
        dt = None
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                elif isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                dt = None
        if not dt or not (start <= dt <= end):
            continue

        url = (
            it.get("url")
            or it.get("webVideoUrl")
            or it.get("shareUrl")
            or it.get("webpageUrl")
            or it.get("playableUrl")
            or ""
        )
        stats = it.get("stats") or {}
        views = it.get("playCount") or stats.get("playCount") or 0
        likes = it.get("diggCount") or stats.get("diggCount") or 0
        comments = it.get("commentCount") or stats.get("commentCount") or 0
        duration = (
            (it.get("video") or {}).get("duration")
            or it.get("duration")
            or it.get("videoDuration")
            or it.get("durationMs")
            or 0
        )
        try:
            # si viene en ms, normaliza; si ya son segundos, queda igual
            duration = int(duration)
            if duration > 600 and str(duration).endswith("000"):
                duration = duration // 1000
        except Exception:
            duration = 0

            # Si el actor no trae duración, pon 10s para no filtrar en el ranker
            if not duration:
                duration = 10

        media_url = (
            (it.get("video") or {}).get("downloadAddr")
            or (it.get("video") or {}).get("playAddr")
            or it.get("playableUrl")
            or ""
        )

        posts.append({
            "platform_post_id": str(it.get("id") or url),
            "url": str(url),
            "posted_at": dt.isoformat(),
            "views": int(views) if views else 0,
            "likes": int(likes) if likes else 0,
            "comments": int(comments) if comments else 0,
            "duration_sec": int(duration) if duration else 0,
            "media_url": str(media_url) if media_url else ""
        })

    return posts

# ---------- MOCK scrapers (replace later with real scraping) ----------
def mock_fetch_instagram_posts(profile_url: str, start: datetime, end: datetime) -> List[Post]:
    """
    IG real via yt_dlp (requiere cookies en muchos casos).
    Usa extract_flat para listar posts y luego pide detalles por cada post dentro de la ventana.
    Variables de entorno opcionales:
      - YTDLP_UA
      - YTDLP_COOKIES (ruta a cookies.txt)
      - YTDLP_COOKIES_FROM_BROWSER (ej: 'chrome')
    """
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return []

    ua = os.getenv("YTDLP_UA", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    cookie_file = os.getenv("YTDLP_COOKIES", "").strip()
    cookies_from_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()

    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "user_agent": ua,
    }
    if cookie_file:
        base_opts["cookies"] = cookie_file
    if cookies_from_browser:
        base_opts["cookiesfrombrowser"] = cookies_from_browser

    detail_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "user_agent": ua,
    }
    if cookie_file:
        detail_opts["cookies"] = cookie_file
    if cookies_from_browser:
        detail_opts["cookiesfrombrowser"] = cookies_from_browser

    def parse_dt(v: dict) -> Optional[datetime]:
        # IG suele dar 'timestamp' en segundos
        ts = v.get("timestamp")
        if ts:
            try:
                return datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                pass
        # a veces 'release_timestamp'
        ts = v.get("release_timestamp")
        if ts:
            try:
                return datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                pass
        # fallback: nada
        return None

    posts: List[Post] = []
    try:
        with YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(profile_url, download=False)
    except Exception:
        return []

    entries = []
    if isinstance(info, dict):
        if "entries" in info and isinstance(info["entries"], list):
            entries = info["entries"]
        else:
            entries = [info]
    else:
        return []

    for ent in entries:
        video_url = ent.get("webpage_url") or ent.get("url")
        if not video_url:
            continue
        try:
            with YoutubeDL(detail_opts) as ydl:
                v = ydl.extract_info(video_url, download=False)
        except Exception:
            continue

        dt = parse_dt(v)
        if not dt or not (start <= dt <= end):
            continue

        duration = v.get("duration") or 0
        views = v.get("view_count") or 0
        likes = v.get("like_count") or 0
        comments = v.get("comment_count") or 0

        posts.append({
            "platform_post_id": v.get("id") or video_url,
            "url": v.get("webpage_url") or video_url,
            "posted_at": dt.isoformat(),
            "views": int(views) if views else 0,
            "likes": int(likes) if likes else 0,
            "comments": int(comments) if comments else 0,
            "duration_sec": int(duration) if duration else 0,
        })
    return posts

def mock_fetch_tiktok_posts(profile_url: str, start: datetime, end: datetime) -> List[Post]:
    """
    TikTok via yt_dlp.
    Lista videos del perfil y extrae detalles para calcular métricas y filtrar por ventana.
    Variables opcionales:
      - YTDLP_UA
      - YTDLP_COOKIES / YTDLP_COOKIES_FROM_BROWSER (si hiciera falta)
    """
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return []

    ua = os.getenv("YTDLP_UA", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    cookie_file = os.getenv("YTDLP_COOKIES", "").strip()
    cookies_from_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()

    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "user_agent": ua,
    }
    if cookie_file:
        base_opts["cookies"] = cookie_file
    if cookies_from_browser:
        base_opts["cookiesfrombrowser"] = cookies_from_browser

    detail_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "user_agent": ua,
    }
    if cookie_file:
        detail_opts["cookies"] = cookie_file
    if cookies_from_browser:
        detail_opts["cookiesfrombrowser"] = cookies_from_browser

    def parse_dt(v: dict) -> Optional[datetime]:
        ts = v.get("timestamp") or v.get("release_timestamp")
        if ts:
            try:
                return datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                return None
        return None

    posts: List[Post] = []
    try:
        with YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(profile_url, download=False)
    except Exception:
        return []

    entries = []
    if isinstance(info, dict):
        if "entries" in info and isinstance(info["entries"], list):
            entries = info["entries"]
        else:
            entries = [info]
    else:
        return []

    for ent in entries:
        video_url = ent.get("webpage_url") or ent.get("url")
        if not video_url:
            continue
        try:
            with YoutubeDL(detail_opts) as ydl:
                v = ydl.extract_info(video_url, download=False)
        except Exception:
            continue

        dt = parse_dt(v)
        if not dt or not (start <= dt <= end):
            continue

        duration = v.get("duration") or 0
        views = v.get("view_count") or 0
        likes = v.get("like_count") or 0
        comments = v.get("comment_count") or 0

        posts.append({
            "platform_post_id": v.get("id") or video_url,
            "url": v.get("webpage_url") or video_url,
            "posted_at": dt.isoformat(),
            "views": int(views) if views else 0,
            "likes": int(likes) if likes else 0,
            "comments": int(comments) if comments else 0,
            "duration_sec": int(duration) if duration else 0,
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

def select_top_posts(all_posts: List[Post], num_scripts: int, sort_by: str = "score", order: str = "desc") -> List[Post]:
    sort_by = (sort_by or "score").lower()
    order = (order or "desc").lower()
    reverse = (order != "asc")

    # Precalcula score si hace falta
    ranked = []
    if sort_by == "score":
        baseline = compute_baseline(all_posts)
        for p in all_posts:
            q = p.copy()
            q["score"] = score_post(p, baseline)
            ranked.append(q)
    else:
        for p in all_posts:
            # asegura que exista una key de score por compatibilidad de UI
            q = p.copy()
            q.setdefault("score", 0.0)
            ranked.append(q)

    # Clave de ordenamiento
    if sort_by in ("views", "likes", "comments", "score"):
        keyfn = lambda x: (x.get(sort_by) or 0)
    else:
        # default a score
        keyfn = lambda x: (x.get("score") or 0)

    ranked.sort(key=keyfn, reverse=reverse)

    # Fallbacks si quedara vacía la lista
    if not ranked:
        tmp = []
        for p in all_posts:
            q = p.copy()
            q["score"] = (int(p.get("likes") or 0) + int(p.get("comments") or 0))
            tmp.append(q)
        tmp.sort(key=lambda x: (x.get("score", 0), x.get("likes", 0)), reverse=True)
        if tmp:
            return tmp[: max(1, min(num_scripts, 5))]
        return all_posts[: max(1, min(num_scripts, 5))]

    return ranked[: max(1, min(num_scripts, 5))]

# ---------- ASR helpers (yt-dlp + ffmpeg + faster-whisper) ----------
def _download_audio(url: str, out_dir: str) -> str:
    tmp_template = os.path.join(out_dir, "input.%(ext)s")
    # Opciones de robustez para IG/TikTok: UA, cookies, geo-bypass y concurrencia
    ua = os.getenv("YTDLP_UA", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    cookie_file = os.getenv("YTDLP_COOKIES", "").strip()        # Ruta a un cookies.txt (opcional)
    cookies_from_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()  # ej: 'chrome' (opcional)

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio/best",
        "--no-playlist",
        "--geo-bypass",
        "-N", "4",
        "--user-agent", ua,
        "-o", tmp_template,
        url,
    ]
    if cookie_file:
        cmd.extend(["--cookies", cookie_file])
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])

    try:
        res = subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # Eleva un error con el stderr decodificado para que el endpoint lo devuelva como detalle
        raise RuntimeError(f"yt-dlp failed: {e.stderr.decode('utf-8','ignore')[:800]}")

    # encuentra el archivo descargado y convíertelo a WAV mono 16k con ffmpeg
    files = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("input.")]
    if not files:
        raise RuntimeError("No se pudo descargar el audio (no se encontró archivo de salida de yt-dlp).")
    input_path = files[0]
    wav_path = os.path.join(out_dir, "audio.wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-ac", "1", "-ar", "16000", wav_path],
            check=True, capture_output=True
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {e.stderr.decode('utf-8','ignore')[:800]}")
    return wav_path

def _download_media_direct(media_url: str, out_dir: str) -> str:
    """
    Descarga un MP4 directamente (requests) y lo convierte a WAV mono 16k con ffmpeg.
    Devuelve la ruta WAV.
    """
    import requests
    mp4_path = os.path.join(out_dir, "input.mp4")
    with requests.get(media_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(mp4_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    wav_path = os.path.join(out_dir, "audio.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp4_path, "-ac", "1", "-ar", "16000", wav_path],
        check=True, capture_output=True
    )
    return wav_path

def _whisper_transcribe(audio_path: str) -> str:
    try:
        from faster_whisper import WhisperModel
    except Exception:
        # fallback si no está el modelo
        return "Transcripción de ejemplo (instala/configura faster-whisper para texto real)."
    model_size = os.getenv("ASR_MODEL", "small")
    model = WhisperModel(model_size, compute_type="int8")
    segments, info = model.transcribe(audio_path, vad_filter=True, beam_size=1, language="es")
    parts = [seg.text.strip() for seg in segments]
    return " ".join(parts).strip() or "(vacío)"

def transcribe_link(url: str, media_url: Optional[str] = None) -> str:
    with tempfile.TemporaryDirectory() as td:
        if media_url:
            wav = _download_media_direct(media_url, td)
        else:
            wav = _download_audio(url, td)
        text = _whisper_transcribe(wav)
    return text

# ---------- GUIDEON (Claude) helpers ----------
def _anthropic_messages(system_text: str, user_text: str) -> Optional[str]:
    """Call Anthropic Messages API. Returns text content or None."""
    api_key = CLAUDE_API_KEY
    if not api_key:
        return None
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": GUIDEON_MAX_TOKENS,
        "temperature": GUIDEON_TEMP,
        "system": system_text,
        "messages": [
            {"role": "user", "content": user_text}
        ],
    }
    try:
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
        if resp.status_code >= 400:
            print(f"[GUIDEON] HTTP {resp.status_code}: {resp.text[:300]} ...")
            return None
        data = resp.json()
        parts = data.get("content") or []
        texts = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                texts.append(p.get("text") or "")
        out = "\n".join(t for t in texts if t)
        return out.strip() or None
    except Exception as e:
        print(f"[GUIDEON] request failed: {e}")
        return None

def _safe_json_extract(text: str) -> Optional[dict]:
    """Intenta extraer un JSON {script, hooks, cta} desde un texto. Tolerante a ruido."""
    if not text:
        return None
    # Primer intento: parsear todo
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Segundo intento: buscar el primer bloque {...}
    try:
        m = _re.search(r"\{[\s\S]*\}", text)
        if m:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
    except Exception:
        return None
    return None

# ---------- Helper: rewrite_with_guideon for per-card rewrites ----------
def adapt_with_guideon(transcript: str, niche_prompt: str, rules_prompt: str,
                       adaptation_level: str = "simple", rules_source: str = "guideon",
                       custom_rules: str = "", lang: str = None) -> dict:
    """Devuelve dict con keys: script, hooks (list), cta (str). Fallback: script=transcript."""
    lang = (lang or GUIDEON_LANG_DEFAULT or "es").strip()
    t = (transcript or "").strip()
    # Limita longitud para controlar costos
    if len(t) > 2000:
        t = t[:2000] + "..."

    # System
    if adaptation_level == "simple":
        simple_rules = _load_prompt("sencilla")
        if simple_rules:
            system_text = simple_rules
        else:
            system_text = (
                "Eres un guionista que ADAPTA un texto al NICHO indicado, sin reestructurar ni cambiar el tono original. "
                "Conserva la idea, pero reemplaza ejemplos, términos y CTA al contexto del nicho. Evita frases idénticas. "
                f"Idioma: {lang}"
            )
    else:
        if rules_source == "custom" and custom_rules.strip():
            base = _load_prompt("reglas_del_usuario")
            if not base:
                base = "Eres un guionista senior para Reels/TikTok. Sigue estas reglas del usuario con prioridad. Entrega final con // corte. "
            system_text = f"{base}\n\nREGLAS_USUARIO:\n{custom_rules.strip()}\nIdioma: {lang}"
        else:
            guideon_rules = _load_prompt("guionista")
            if not guideon_rules:
                guideon_rules = (
                    "Eres un guionista senior para Reels/TikTok. Estructura: Hook (&lt;3s) → Desarrollo (2-3 ideas) → "
                    "Prueba social → CTA. Originalidad obligatoria. Usa cortes (// corte). "
                )
            system_text = f"{guideon_rules}\nIdioma: {lang}"

    # User task
    if adaptation_level == "simple":
        user_text = (
            f"NICHO: {niche_prompt}\n"
            f"REGLAS: {rules_prompt}\n"
            "ADAPTA SOLO el contexto (ejemplos, CTA, terminología) sin cambiar estructura ni ritmo original.\n"
            "Devuélvelo como TEXTO PLANO listo para grabar.\n\n"
            f"TEXTO_ORIG:\n{t}\n"
        )
    else:
        user_text = (
            f"Nicho/Producto: {niche_prompt}\n"
            f"Reglas/Tono: {rules_prompt}\n"
            f"Idioma: {lang}\n"
            "Transcripción fuente a adaptar (NO copiar literal):\n" + t + "\n\n"
            "Entrega SOLO un JSON con esta forma exacta:\n"
            "{\n  \"script\": \"texto final listo para grabar con // corte\",\n  \"hooks\": [\"hook1\",\"hook2\",\"hook3\",\"hook4\",\"hook5\"],\n  \"cta\": \"llamado a la acción\"\n}\n"
        )

    resp_text = _anthropic_messages(system_text, user_text)
    if not resp_text:
        return {"script": transcript, "hooks": [], "cta": ""}

    obj = _safe_json_extract(resp_text) if adaptation_level != "simple" else None
    if obj and isinstance(obj, dict):
        script = (obj.get("script") or transcript or "").strip()
        hooks = obj.get("hooks") or []
        cta = obj.get("cta") or ""
    else:
        # simple: devolvió texto plano
        script = resp_text.strip()
        hooks = []
        cta = ""

    return {"script": script, "hooks": hooks, "cta": cta}

# ---------- Helper: rewrite_with_guideon for per-card rewrites ----------
def rewrite_with_guideon(script: str, user_prompt: str, niche_prompt: str = "",
                         adaptation_level: str = "completa",
                         rules_source: str = "guideon",
                         custom_rules: str = "",
                         lang: Optional[str] = None) -> dict:
    """Toma un guion existente y aplica cambios pedidos por el usuario usando Guideon/Claude.
    Devuelve dict {script, hooks, cta}. Si no hay JSON válido en salida, devuelve texto plano en `script`.
    """
    lang = (lang or GUIDEON_LANG_DEFAULT or "es").strip()
    base_text = (script or "").strip()
    if len(base_text) > 4000:
        base_text = base_text[:4000] + "..."

    # Siempre usar prompts/guionista como system_text, con fallback si no existe
    guideon_rules = _load_prompt("guionista")
    if not guideon_rules:
        guideon_rules = (
            "Eres un guionista senior para Reels/TikTok. Estructura: Hook (<3s) → Desarrollo (2-3 ideas) → Prueba social → CTA. "
            "Originalidad obligatoria. Usa // corte."
        )
    system_text = f"{guideon_rules}\nIdioma: {lang}"

    user_text = (
        f"NICHO (opcional): {niche_prompt}\n"
        "A partir del TEXTO_BASE, realiza SOLO los cambios requeridos por el usuario.\n"
        "Si procede, devuelve un JSON con esta forma; si no aplica, devuelve solo texto plano:\n"
        "{\n  \"script\": \"texto listo con // corte\",\n  \"hooks\": [\"...\"],\n  \"cta\": \"...\"\n}\n\n"
        f"INSTRUCCIÓN_USUARIO:\n{user_prompt}\n\n"
        f"TEXTO_BASE:\n{base_text}\n"
    )

    resp = _anthropic_messages(system_text, user_text)
    if not resp:
        return {"script": script, "hooks": [], "cta": ""}
    obj = _safe_json_extract(resp)
    if obj and isinstance(obj, dict):
        return {
            "script": (obj.get("script") or script or "").strip(),
            "hooks": obj.get("hooks") or [],
            "cta": obj.get("cta") or "",
        }
    return {"script": resp.strip(), "hooks": [], "cta": ""}

# ---------- Single-link transcribe (real) ----------
@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    try:
        text = transcribe_link(str(req.url))
        return {
            "items": [{
                "url": str(req.url),
                "metrics": {"views": None, "likes": None, "comments": None, "score": None},
                "script": text
            }]
        }
    except RuntimeError as e:
        return JSONResponse({"error": "transcription_failed", "detail": str(e)}, status_code=500)
    except subprocess.CalledProcessError as e:
        return JSONResponse(
            {"error": "download_or_convert_failed", "detail": e.stderr.decode("utf-8", "ignore")[:800]},
            status_code=500
        )
    except Exception as e:
        return JSONResponse({"error": "transcription_failed", "detail": str(e)}, status_code=500)

# ---------- Per-card rewrite endpoint ----------
@app.post("/guideon/rewrite")
def guideon_rewrite(req: RewriteReq):
    try:
        if not CLAUDE_API_KEY:
            return JSONResponse({"error": "no_claude_key", "detail": "Configura CLAUDE_API_KEY en el entorno."}, status_code=400)
        out = rewrite_with_guideon(
            script=req.script,
            user_prompt=req.user_prompt,
            niche_prompt=req.niche_prompt or "",
            adaptation_level=(req.adaptation_level or "completa"),
            rules_source=(req.rules_source or "guideon"),
            custom_rules=req.custom_rules or "",
            lang=req.lang or GUIDEON_LANG_DEFAULT,
        )
        return out
    except Exception as e:
        return JSONResponse({"error": "guideon_failed", "detail": str(e)}, status_code=500)

# ---------- Job start: scrape + rank + transcribe ----------
@app.post("/job/start")
def job_start(req: JobReq):
    try:
        # 1) Window
        start, end = parse_window(req.window)

        # 2) Collect posts across profiles (YouTube real, IG/TikTok prefer Apify)
        all_posts: List[Post] = []
        for pr in (req.profiles or [])[:3]:
            url = str(pr.url)
            platform = (pr.platform or "").lower()

            posts = []
            used_provider = None
            if "instagram.com" in url or platform == "instagram":
                posts = fetch_instagram_posts_apify(url, start, end, limit=int(os.getenv("APIFY_DATASET_LIMIT", "50")))
                used_provider = "apify_ig"
                if not posts and not APIFY_ONLY:
                    posts = mock_fetch_instagram_posts(url, start, end)
                    used_provider = "yt_dlp_ig"
            elif "tiktok.com" in url or platform == "tiktok":
                posts = fetch_tiktok_posts_apify(url, start, end, limit=int(os.getenv("APIFY_DATASET_LIMIT", "50")))
                used_provider = "apify_tt"
                if not posts and not APIFY_ONLY:
                    posts = mock_fetch_tiktok_posts(url, start, end)
                    used_provider = "yt_dlp_tt"
            else:
                posts = []
                used_provider = "none"

            if DEBUG_APIFY:
                print(f"[APIFY] Provider for {url}: {used_provider}, posts_found={len(posts)}")

            posts = filter_by_window(posts, start, end)
            all_posts.extend(posts)

        # 3) If nothing found, return diagnostic when DEBUG_APIFY is on
        if not all_posts and DEBUG_APIFY:
            return JSONResponse({
                "error": "no_posts_found",
                "hint": "Apify no devolvió items para los perfiles y ventana indicados. Revisa actor/token/perfil (privado) o incrementa APIFY_RUN_TIMEOUT_SEC.",
                "details": {
                    "APIFY_ONLY": APIFY_ONLY,
                    "APIFY_IG_ACTOR": APIFY_IG_ACTOR,
                    "APIFY_TT_ACTOR": APIFY_TT_ACTOR,
                    "window": req.window,
                    "profiles": [{"platform": p.platform, "url": str(p.url)} for p in req.profiles],
                }
            }, status_code=200)
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
        top_posts = select_top_posts(all_posts, req.num_scripts, getattr(req, "sort_by", "score"), getattr(req, "order", "desc"))
        
        if not top_posts:
            top_posts = all_posts[: max(1, min(req.num_scripts, 5))]

        # 5) Transcribe each Top post (real)
        items = []
        for p in top_posts:
            try:
                transcript_text = transcribe_link(p["url"], p.get("media_url") or None)
            except Exception as e:
                transcript_text = f"(Error transcribiendo este video) {str(e)[:200]}"

            script_text = transcript_text
            hooks = []
            cta = ""

            if (req.mode or "").lower() == "creative":
                cobj = req.creative or {}
                niche = (cobj.get("niche_prompt") or "").strip()
                rules = (cobj.get("rules_prompt") or "").strip()
                adaptation_level = (cobj.get("adaptation_level") or "simple").strip().lower()
                rules_source = (cobj.get("rules_source") or "guideon").strip().lower()
                custom_rules = (cobj.get("custom_rules") or "").strip()
                lang = (cobj.get("lang") or GUIDEON_LANG_DEFAULT or "es").strip()

                guide = adapt_with_guideon(
                    transcript=transcript_text,
                    niche_prompt=niche,
                    rules_prompt=rules,
                    adaptation_level=adaptation_level,
                    rules_source=rules_source,
                    custom_rules=custom_rules,
                    lang=lang,
                )
                script_text = guide.get("script") or transcript_text
                hooks = guide.get("hooks") or []
                cta = guide.get("cta") or ""

                # Formatea para mostrar hooks/cta arriba del guion en la card actual
                if hooks or cta:
                    header = []
                    if hooks:
                        header.append("[HOOKS]\n- " + "\n- ".join([str(h) for h in hooks if h]))
                    if cta:
                        header.append("\n[CTA]\n" + str(cta))
                    script_text = ("\n\n".join(header) + "\n\n[GUION]\n" + script_text).strip()

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
#nota