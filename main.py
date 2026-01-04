import os
import time
import datetime
import subprocess
import requests
import re
import asyncio
import uuid
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
import yt_dlp

# ─────────────────────────────
# CONFIG
# ─────────────────────────────
MONGO_URL = os.getenv("MONGO_DB_URI")
if not MONGO_URL:
    print("⚠️ MONGO_DB_URI not found.")

CATBOX_UPLOAD = "https://catbox.moe/user/api.php"

# COOKIES PATH CHECK
COOKIES_PATHS = ["/app/cookies.txt", "./cookies.txt", "/etc/cookies.txt", "/tmp/cookies.txt"]
COOKIES_PATH = None
for path in COOKIES_PATHS:
    if os.path.exists(path):
        COOKIES_PATH = path
        print(f"✅ Found cookies: {path}")
        break

app = FastAPI(title="⚡ Sudeep API (Wait Mode + Node)")

# ─────────────────────────────
# DATABASE
# ─────────────────────────────
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["MusicAPI_DB12"]
videos_col = db["videos_cacht"]    # Data
keys_col = db["api_users"]         # Keys
queries_col = db["query_mapping"]  # Memory ("Ishq" -> "vid_01")

# RAM CACHE
RAM_CACHE = {}

# ─────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────
def extract_video_id(q: str):
    if not q: return None
    q = q.strip()
    if len(q) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', q): return q
    patterns = [r'(?:v=|\/)([0-9A-Za-z_-]{11})', r'youtu\.be\/([0-9A-Za-z_-]{11})']
    for pattern in patterns:
        match = re.search(pattern, q)
        if match: return match.group(1)
    return None

def format_time(seconds):
    try: return f"{int(seconds)//60}:{int(seconds)%60:02d}"
    except: return "0:00"

# SYNC SEARCH (Blocking)
def sync_search_info(query: str = None, video_id: str = None):
    ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'extract_flat': True}
    if COOKIES_PATH: ydl_opts['cookiefile'] = COOKIES_PATH
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if video_id:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                return video_id, info.get('title'), format_time(info.get('duration'))
            else:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
                if info and 'entries' in info and info['entries']:
                    v = info['entries'][0]
                    return v['id'], v['title'], format_time(v.get('duration'))
    except Exception as e:
        print(f"Search Error: {e}")
    return None, None, None

# UPLOAD
def upload_catbox(path: str):
    try:
        with open(path, "rb") as f:
            r = requests.post(CATBOX_UPLOAD, data={"reqtype": "fileupload"}, files={"fileToUpload": f}, timeout=120)
        return r.text.strip() if r.status_code == 200 and r.text.startswith("http") else None
    except: return None

# 🔥 UPDATED DOWNLOAD FUNCTION (With Node.js & Optimization)
def auto_download_video(video_id: str):
    random_name = str(uuid.uuid4())
    out = f"/tmp/{random_name}.mp4"
    if os.path.exists(out): os.remove(out)

    cmd = [
        "python", "-m", "yt_dlp",
        
        # ✅ Node JS Enable (Speed Boost)
        "--js-runtimes", "node",
        
        "--no-playlist", "--geo-bypass", "--force-ipv4",
        
        # ✅ Optimized 480p + H.264 (Universal Playback & Fast Upload)
        "-f", "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--postprocessor-args", "VideoConvertor:-c:v libx264 -c:a aac -movflags +faststart",
        
        "-o", out, f"https://www.youtube.com/watch?v={video_id}"
    ]
    
    if COOKIES_PATH: 
        cmd.insert(3, "--cookies")
        cmd.insert(4, COOKIES_PATH)

    try:
        print(f"🚀 Starting Optimized Download: {video_id}")
        subprocess.run(cmd, check=True, timeout=900)
        return out if os.path.exists(out) and os.path.getsize(out) > 1024 else None
    except Exception as e:
        print(f"❌ Download Failed: {e}")
        return None

# KEY CHECK
async def verify_key_fast(key: str):
    try:
        doc = await keys_col.find_one({"api_key": key, "active": True})
        if not doc: return False, "Invalid API key"
        return True, None
    except: return False, "Error"

# ─────────────────────────────
# 🔥 MAIN ENDPOINT (WAIT LOGIC)
# ─────────────────────────────
@app.get("/getvideo")
async def get_video(query: str, key: str):
    start_time = time.time()
    
    # 1. Key Verify
    valid, msg = await verify_key_fast(key)
    if not valid: return {"status": 403, "error": msg}

    clean_query = query.strip().lower()
    video_id = extract_video_id(query)

    # ──────────────────────────────────────────
    # STEP 1: MEMORY & DB CHECK (Fastest)
    # ──────────────────────────────────────────
    # Agar Video ID nahi hai, toh Query Memory check karo
    if not video_id:
        cached_q = await queries_col.find_one({"query": clean_query})
        if cached_q: 
            video_id = cached_q["video_id"]
            print(f"🧠 Query Hit: {clean_query} -> {video_id}")

    # Agar DB mein link hai
    if video_id:
        cached = await videos_col.find_one({"video_id": video_id})
        if cached and cached.get("catbox_link"):
            return {
                "status": 200,
                "title": cached["title"],
                "duration": cached["duration"],
                "link": cached["catbox_link"],
                "cached": True,
                "response_time": f"{time.time()-start_time:.2f}s"
            }

    # ──────────────────────────────────────────
    # STEP 2: IF NEW SONG -> WAIT & PROCESS ⏳
    # ──────────────────────────────────────────
    
    # A. Search Info (Wait 3s)
    if not video_id:
        video_id, title, duration = await asyncio.to_thread(sync_search_info, query=query)
    else:
        # ID hai par Data nahi hai
        _, title, duration = await asyncio.to_thread(sync_search_info, video_id=video_id)
    
    if not title: return {"status": 404, "error": "Song not found"}

    # B. Save Metadata & Query Immediately (Future ke liye)
    await videos_col.update_one(
        {"video_id": video_id}, {"$set": {"video_id": video_id, "title": title, "duration": duration}}, upsert=True
    )
    # Map Query to ID
    if clean_query and not extract_video_id(clean_query):
        await queries_col.update_one({"query": clean_query}, {"$set": {"video_id": video_id}}, upsert=True)

    # C. DOWNLOAD & UPLOAD (Wait 20-30s) 🛑 User yahan rukega
    # User ko 'Processing' nahi bolenge, sidha link denge
    print(f"⏳ Downloading: {title}")
    file_path = await asyncio.to_thread(auto_download_video, video_id)
    
    if not file_path:
        return {"status": 500, "error": "Download failed"}

    print(f"📤 Uploading: {title}")
    link = await asyncio.to_thread(upload_catbox, file_path)
    
    # Clean file
    if os.path.exists(file_path): os.remove(file_path)

    if not link:
        return {"status": 500, "error": "Upload failed"}

    # D. Save Link to DB
    await videos_col.update_one(
        {"video_id": video_id},
        {"$set": {"catbox_link": link, "cached_at": datetime.datetime.now()}}
    )

    # ──────────────────────────────────────────
    # STEP 3: RETURN FINAL LINK ✅
    # ──────────────────────────────────────────
    return {
        "status": 200,
        "title": title,
        "duration": duration,
        "link": link,
        "cached": False,
        "response_time": f"{time.time()-start_time:.2f}s"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
