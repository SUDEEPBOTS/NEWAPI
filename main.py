import os
import time
import datetime
import subprocess
import requests
import re
import asyncio
import uuid
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
import yt_dlp

# ─────────────────────────────
# CONFIG
# ─────────────────────────────
MONGO_URL = os.getenv("MONGO_DB_URI")
# Agar testing kar rahe ho to manually string daal sakte ho, warna env var rahne do
if not MONGO_URL:
    print("⚠️ MONGO_DB_URI not found in env.")

CATBOX_UPLOAD = "https://catbox.moe/user/api.php"

# COOKIES PATH
COOKIES_PATHS = [
    "/app/cookies.txt",      # Render default
    "./cookies.txt",         # Current directory
    "/etc/cookies.txt",      # System directory
    "/tmp/cookies.txt"       # Temp directory
]

COOKIES_PATH = None
for path in COOKIES_PATHS:
    if os.path.exists(path):
        COOKIES_PATH = path
        print(f"✅ Found cookies at: {path}")
        break

if not COOKIES_PATH:
    print("⚠️ WARNING: No cookies.txt found! YouTube may block downloads.")

# ─────────────────────────────
# FASTAPI APP
# ─────────────────────────────
app = FastAPI(title="⚡ Sudeep Music API")

# MongoDB
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["MusicAPI_DB12"]
videos_col = db["videos_cacht"]
keys_col = db["api_users"]

# RAM CACHE
RAM_CACHE = {}

# ─────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────
def extract_video_id(q: str):
    if not q: return None
    q = q.strip()
    if len(q) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', q):
        return q
    patterns = [r'(?:v=|\/)([0-9A-Za-z_-]{11})', r'youtu\.be\/([0-9A-Za-z_-]{11})']
    for pattern in patterns:
        match = re.search(pattern, q)
        if match: return match.group(1)
    return None

def format_time(seconds):
    if not seconds: return "0:00"
    try:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"
    except: return "0:00"

def quick_search(query: str):
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'extract_flat': True}
        if COOKIES_PATH and os.path.exists(COOKIES_PATH):
            ydl_opts['cookiefile'] = COOKIES_PATH
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info and 'entries' in info and info['entries']:
                video = info['entries'][0]
                return {
                    "id": video.get('id'),
                    "title": video.get('title', 'Unknown Title'),
                    "duration": format_time(video.get('duration'))
                }
    except Exception as e:
        print(f"Search error: {e}")
    return None

def get_video_info(video_id: str):
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        if COOKIES_PATH and os.path.exists(COOKIES_PATH):
            ydl_opts['cookiefile'] = COOKIES_PATH
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return {
                "id": video_id,
                "title": info.get('title', f'Video {video_id}'),
                "duration": format_time(info.get('duration'))
            }
    except Exception as e:
        print(f"Video info error: {e}")
        return None

async def verify_key_fast(key: str):
    try:
        doc = await keys_col.find_one({"api_key": key, "active": True})
        if not doc: return False, "Invalid API key"
        if time.time() > doc.get("expires_at", 0): return False, "API key expired"
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        if doc.get("last_reset") != today:
            await keys_col.update_one({"_id": doc["_id"]}, {"$set": {"used_today": 0, "last_reset": today}})
            used_today = 0
        else: used_today = doc.get("used_today", 0)
        if used_today >= doc.get("daily_limit", 50): return False, "Daily limit exceeded"
        await keys_col.update_one({"_id": doc["_id"]}, {"$inc": {"used_today": 1}})
        return True, None
    except Exception as e: return False, f"Verification error: {str(e)}"

# ─────────────────────────────
# 🔥 YOUR REQUESTED STYLE FUNCTIONS
# ─────────────────────────────

def upload_catbox(path: str):
    """
    Aapka requested upload style.
    """
    try:
        print(f"📤 Uploading to Catbox: {path}")
        with open(path, "rb") as f:
            r = requests.post(
                CATBOX_UPLOAD,
                data={"reqtype": "fileupload"},
                files={"fileToUpload": f},
                timeout=120
            )
        if r.status_code == 200 and r.text.startswith("http"):
            print(f"✅ Upload Success: {r.text.strip()}")
            return r.text.strip()
        else:
            print(f"❌ Upload Failed: Status {r.status_code} | Body: {r.text}")
            return None
    except Exception as e:
        print(f"❌ Catbox Exception: {e}")
        return None

def auto_download_video(video_id: str) -> str:
    """
    Aapka requested download style + Safety Fixes (UUID & H.264)
    """
    # 1. UUID Filename (Taaki '-' ID wale songs fail na ho)
    random_name = str(uuid.uuid4())
    out = f"/tmp/{random_name}.mp4"
    
    # Safely remove if exists
    if os.path.exists(out):
        os.remove(out)

    # 2. Command Construction (Using python -m yt_dlp as requested)
    cmd = [
        "python", "-m", "yt_dlp",
        
        # System Flags
        "--js-runtimes", "node",
        "--no-playlist",
        "--geo-bypass",
        "--force-ipv4",
        
        # Cookies
        "--cookies", COOKIES_PATH if COOKIES_PATH else "",
        
        # Format & Codec (CRITICAL FOR PLAYBACK)
        # H.264 + AAC force kar rahe hain taaki black screen na aaye
        "-f", "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--postprocessor-args", "VideoConvertor:-c:v libx264 -c:a aac -movflags +faststart",
        
        # Output
        "-o", out,
        
        # Input URL
        f"https://www.youtube.com/watch?v={video_id}"
    ]

    # Remove empty cookie arg if no cookies found
    if not COOKIES_PATH:
        cmd.remove("--cookies")
        cmd.remove("")

    print(f"🚀 Executing: {' '.join(cmd)}")

    try:
        # 3. Running Subprocess
        subprocess.run(cmd, check=True, timeout=900)
        
        # 4. Verification
        if os.path.exists(out) and os.path.getsize(out) > 1024:
            return out
        
        # Fallback check (agar extension change ho gayi ho)
        for f in os.listdir("/tmp"):
            if random_name in f:
                return os.path.join("/tmp", f)
                
        raise Exception("File not created after download")

    except subprocess.CalledProcessError as e:
        print(f"❌ Download Error: {e}")
        return None
    except Exception as e:
        print(f"❌ General Error: {e}")
        return None

# ─────────────────────────────
# BACKGROUND TASK
# ─────────────────────────────
async def background_worker(video_id: str, title: str, duration: str):
    try:
        print(f"🔄 Processing: {video_id}")
        
        # 1. Download (Using your style)
        file_path = auto_download_video(video_id)
        if not file_path:
            return

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # 2. Upload (Using your style)
        link = upload_catbox(file_path)
        
        # Cleanup
        try: os.remove(file_path)
        except: pass

        if not link:
            return

        # 3. Save DB
        await videos_col.update_one(
            {"video_id": video_id},
            {"$set": {
                "video_id": video_id, "title": title, "duration": duration,
                "catbox_link": link, "cached_at": datetime.datetime.now(),
                "size_mb": file_size_mb
            }}, upsert=True
        )

        # 4. Cache
        RAM_CACHE[video_id] = {
            "status": 200, "title": title, "duration": duration,
            "link": link, "video_id": video_id, "cached": True
        }
        print(f"✅ DONE: {title}")

    except Exception as e:
        print(f"❌ Background Worker Error: {e}")

# ─────────────────────────────
# API ENDPOINT
# ─────────────────────────────
@app.get("/getvideo")
async def get_video(query: str, key: str):
    start_time = time.time()
    
    # Key Check
    valid, msg = await verify_key_fast(key)
    if not valid:
        return {"status": 403, "error": msg}

    # Search / ID
    video_id = extract_video_id(query)
    title, duration = None, None

    if video_id:
        info = get_video_info(video_id)
        if info: title, duration = info["title"], info["duration"]
        else: title, duration = f"Video {video_id}", "unknown"
    else:
        res = quick_search(query)
        if not res: return {"status": 404, "error": "Not found"}
        video_id, title, duration = res["id"], res["title"], res["duration"]

    # RAM Cache
    if video_id in RAM_CACHE:
        resp = RAM_CACHE[video_id].copy()
        resp["response_time_ms"] = int((time.time() - start_time) * 1000)
        return resp

    # DB Cache
    cached = await videos_col.find_one({"video_id": video_id})
    if cached and cached.get("catbox_link"):
        resp = {"status": 200, "title": cached["title"], "duration": cached["duration"], "link": cached["catbox_link"], "cached": True}
        RAM_CACHE[video_id] = resp
        return resp

    # Process New
    asyncio.create_task(background_worker(video_id, title, duration))
    
    return {
        "status": 202,
        "title": title,
        "duration": duration,
        "message": "Processing...",
        "response_time_ms": int((time.time() - start_time) * 1000)
    }

@app.get("/")
def home():
    return {"status": "Running", "cookies": "Yes" if COOKIES_PATH else "No"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
        
