import os
import time
import datetime
import re
import asyncio
import uuid
import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client
import yt_dlp

# ─────────────────────────────
# CONFIG
# ─────────────────────────────
MONGO_URL = os.getenv("MONGO_DB_URI")
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")         
API_HASH = os.getenv("API_HASH")     
LOGGER_ID = int(os.getenv("LOGGER_ID", "-100363958")) 

# ⚡ External Downloader Config
EXTERNAL_API_URL = "https://shrutibots.site"

# 👇 Tera Render URL (Stream Redirect ke liye)
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://music.yukiapi.site")

app = FastAPI(title="⚡ Sudeep API (Final Edition)")

# ─────────────────────────────
# TELEGRAM CLIENT
# ─────────────────────────────
bot = Client(
    "Sudeep_Session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

# ─────────────────────────────
# DATABASE
# ─────────────────────────────
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["API999_DB120"]
videos_col = db["telegram_files_v2"]  
keys_col = db["api_users"]            

# ─────────────────────────────
# STARTUP
# ─────────────────────────────
@app.on_event("startup")
async def startup_event():
    print("🤖 Starting Telegram Client...")
    await bot.start()
    
    # 🔥 Self-Check
    try:
        me = await bot.get_me()
        print(f"✅ Bot Started: {me.first_name} (@{me.username})")
    except Exception as e:
        print(f"⚠️ သတိပေးချက် - Bot က Logger Channel ({LOGGER_ID}) မှာ Admin (စီမံခန့်ခွဲသူ) ဖြစ်မနေလောက်ဘူး!")
 )
        print(f"Error: {e}")

    print("✅ Telegram Client Ready!")

@app.on_event("shutdown")
async def shutdown_event():
stop    await bot.s)

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

# 🔥 LIMIT CHECKER
async def check_api_limit(key: str):
    user = await keys_col.find_one({"api_key": key})
    if not user or not user.get("active", True):
        return False, "Invalid or Inactive API Key"
    
    today = str(datetime.date.today())
    if user.get("last_reset") != today:
        await keys_col.update_one(
            {"api_key": key}, 
            {"$set": {"used_today": 0, "last_reset": today}}
        )
        user["used_today"] = 0 
    
    daily_limit = user.get("daily_limit", 100)
    if user.get("used_today", 0) >= daily_limit:
        return False, "Daily Limit Exceeded."
    
    return True, None

# 🔥 INCREMENT COUNTER
async def increment_usage(key: str):
    await keys_col.update_one(
        {"api_key": key}, 
        {"$inc": {"used_today": 1, "total_usage": 1}}
    )

# 🔥 METADATA
def get_video_metadata(query: str):
    ydl_opts = {
        'quiet': True, 'skip_download': True, 'extract_flat': True, 'noplaylist': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            direct_id = extract_video_id(query)
            if direct_id:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={direct_id}", download=False)
                thumb = info.get('thumbnail') or f"https://i.ytimg.com/vi/{direct_id}/hqdefault.jpg"
                return direct_id, info.get('title'), format_time(info.get('duration')), thumb
            else:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
                if info and 'entries' in info and info['entries']:
                    v = info['entries'][0]
                    vid_id = v['id']
                    thumb = v.get('thumbnail') or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
                    return vid_id, v['title'], format_time(v.get('duration')), thumb
    except Exception as e:
        print(f"Metadata Error: {e}")
    return None, None, None, None

# 🔥 DOWNLOADER
async def download_via_shrutibots(video_id: str, type: str):
    ext = "mp4" if type == "video" else "mp3"
    random_name = str(uuid.uuid4())
    out_path = f"/tmp/{random_name}.{ext}"
    try:
        async with aiohttp.ClientSession() as session:
            token_url = f"{EXTERNAL_API_URL}/download"
            params = {"url": video_id, "type": type}
            async with session.get(token_url, params=params, timeout=20) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                token = data.get("download_token")
            if not token: return None

            stream_url = f"{EXTERNAL_API_URL}/stream/{video_id}?type={type}"
            headers = {"X-Download-Token": token}
            async with session.get(stream_url, headers=headers, timeout=1200) as resp:
                if resp.status != 200: return None
                with open(out_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(16384):
                        f.write(chunk)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
                return out_path
            return None
    except Exception as e:
        print(f"❌ Download Error: {e}")
        return None

# 🔥 UPLOADER (Updated: Fixes file_0.bin issue) 🛠️
async def upload_to_telegram(file_path: str, title: str, duration: str, vid_id: str, link: str, type: str):
    try:
        # 1. Filename Clean karo
        clean_title = re.sub(r'[\\/*?:"<>|]', "", title)
        if not clean_title: clean_title = "Unknown_File"
        
        # 2. Extension lagao
        ext = "mp4" if type == "video" else "mp3"
        final_filename = f"{clean_title}.{ext}"

        caption = (
            f"🫶 **ᴛɪᴛʟᴇ:** {title}\n"
            f"⏱ **ᴅᴜʀᴀᴛɪᴏɴ:** {duration}\n"
            f"🛡️ **ɪᴅ:** `{vid_id}`\n"
            f"🔗 [Stream Link]({link})"
        )

        print(f"🚀 Uploading as: {final_filename}...")

        if type == "video":
            msg = await bot.send_video(
                LOGGER_ID, 
                file_path, 
                caption=caption, 
                supports_streaming=True,
                file_name=final_filename  # 👈 YE FIX HAI
            )
            return msg.video.file_id
        else:
            msg = await bot.send_audio(
                LOGGER_ID, 
                file_path, 
                caption=caption, 
                title=title, 
                performer="Sudeep API",
                file_name=final_filename  # 👈 YE FIX HAI
            )
            return msg.audio.file_id

    except Exception as e:
        print(f"❌ Upload Error: {e}")
        return None

# ─────────────────────────────
# 🔥 MAIN LOGIC
# ─────────────────────────────
async def process_request(query: str, key: str, type: str):
    start_time = time.time()

    # 1. Limit Check
    is_allowed, error_msg = await check_api_limit(key)
    if not is_allowed:
        return {"status": 403, "error": error_msg}

    # ID Extraction
    clean_query = query.strip()
    video_id = extract_video_id(clean_query)
    title, duration, thumbnail = None, "0:00", None

    if not video_id:
        video_id, title, duration, thumbnail = await asyncio.to_thread(get_video_metadata, query)

    if not video_id: return {"status": 404, "error": "Not Found"}

    # Cache Check
    existing = await videos_col.find_one({"yt_id": video_id})
    stream_link = f"{BASE_URL}/stream/{video_id}?type={type}"

    if existing:
        file_id = existing.get("video_file_id") if type == "video" else existing.get("audio_file_id")
        if file_id:
            await increment_usage(key)
            return {
                "status": 200,
                "title": existing.get("title", title),
                "duration": existing.get("duration", duration),
                "link": stream_link,
                "id": video_id,
                "thumbnail": existing.get("thumbnail", thumbnail),
                "source": "cache",
                "type": type,
                "response_time": f"{time.time() - start_time:.2f}s"
            }

    # Download New
    if not title:
        _, title, duration, thumbnail = await asyncio.to_thread(get_video_metadata, video_id)
        if not title: title = "Unknown"

    file_path = await download_via_shrutibots(video_id, type)
    if not file_path: return {"status": 500, "error": "Download Failed"}

    # Upload New
    file_id = await upload_to_telegram(file_path, title, duration, video_id, stream_link, type)
    if os.path.exists(file_path): os.remove(file_path)

    if not file_id: return {"status": 500, "error": "Upload Failed"}

    # Save to DB
    update_field = "video_file_id" if type == "video" else "audio_file_id"
    await videos_col.update_one(
        {"yt_id": video_id},
        {"$set": {
            "yt_id": video_id, "title": title, "duration": duration, "thumbnail": thumbnail,
            update_field: file_id, "cached_at": datetime.datetime.now()
        }}, upsert=True
    )

    await increment_usage(key)

    return {
        "status": 200,
        "title": title,
        "duration": duration,
        "link": stream_link,
        "id": video_id,
        "thumbnail": thumbnail,
        "source": "new_upload",
        "type": type,
        "response_time": f"{time.time() - start_time:.2f}s"
    }

# ─────────────────────────────
# 🚀 ENDPOINTS
# ─────────────────────────────

# 1️⃣ Uptime
@app.get("/")
@app.head("/")
async def home():
    return JSONResponse(content={"status": "Alive", "msg": "HanThar API Running ⚡"}, status_code=200)

# 2️⃣ AUDIO
@app.get("/getaudio")
async def get_audio_endpoint(query: str, key: str):
    return await process_request(query, key, "audio")

# 3️⃣ VIDEO
@app.get("/getvideo")
async def get_video_endpoint(query: str, key: str):
    return await process_request(query, key, "video")

# 4️⃣ STATS
@app.get("/stats")
async def get_stats(key: str):
    user = await keys_col.find_one({"api_key": key})
    if not user:
        return JSONResponse(content={"error": "Invalid API Key"}, status_code=403)
    
    daily_limit = user.get("daily_limit", 100)
    used_today = user.get("used_today", 0)
    
    return {
        "status": 200,
        "owner": user.get("owner_name", "Unknown"),
        "plan": "Premium" if daily_limit > 500 else "Free",
        "daily_limit": daily_limit,
        "used_today": used_today,
        "remaining": daily_limit - used_today,
        "total_usage": user.get("total_usage", 0)
    }

# 5️⃣ STREAM REDIRECT (Direct API - 100% Works)
@app.get("/stream/{yt_id}")
async def stream_redirect(yt_id: str, type: str = "audio"):
    doc = await videos_col.find_one({"yt_id": yt_id})
    if not doc:
        return RedirectResponse("https://http.cat/404")
    
    target_file_id = doc.get("video_file_id") if type == "video" else doc.get("audio_file_id")
    if not target_file_id:
        return RedirectResponse("https://http.cat/404")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Seedha Telegram Server se Link maango
            api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={target_file_id}"
            
            async with session.get(api_url) as resp:
                data = await resp.json()
                
                if not data.get("ok"):
                    print(f"❌ Telegram API Error: {data}")
                    return JSONResponse(content=data, status_code=400)
                
                file_path = data["result"]["file_path"]
                fresh_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                
                return RedirectResponse(url=fresh_link)

    except Exception as e:
        print(f"❌ Stream Server Error: {e}")
        return RedirectResponse("https://http.cat/500")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
