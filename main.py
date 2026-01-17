import os
import time
import datetime
import requests
import asyncio
import uuid
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
import config
import urllib3

# SSL Warnings disable taaki terminal saaf rahe
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="⚡ Sudeep API (Sumit API + Catbox Edition)")

# ─────────────────────────────
# DATABASE & CONFIG
# ─────────────────────────────
if not config.MONGO_DB_URI:
    print("⚠️ MONGO_DB_URI not found.")

mongo = AsyncIOMotorClient(config.MONGO_DB_URI)
db = mongo["MusicAPI_DB_Final"]
videos_col = db["videos_cache"]
keys_col = db["api_users"]

CATBOX_UPLOAD = "https://catbox.moe/user/api.php"

# ─────────────────────────────
# 🔗 HELPERS
# ─────────────────────────────
def format_duration(seconds):
    try:
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"
    except: return "0:00"

# YouTube Key Rotation (For Metadata/Thumbnail)
current_key_index = 0
def get_next_key():
    global current_key_index
    keys = config.YOUTUBE_API_KEYS
    if not keys: return None
    key = keys[current_key_index]
    current_key_index = (current_key_index + 1) % len(keys)
    return key

def send_telegram_log(title, duration, link, vid_id):
    if not config.BOT_TOKEN: return
    try:
        msg = (f"🍫 **ɴᴇᴡ sᴏɴɢ (Sumit API)**\n\n"
               f"🫶 **ᴛɪᴛʟᴇ:** {title}\n"
               f"⏱ **ᴅᴜʀᴀᴛɪᴏɴ:** {duration}\n"
               f"🛡️ **ɪᴅ:** `{vid_id}`\n"
               f"👀 [ʟɪɴᴋ]({link})\n\n"
               f"🍭 @Kaito_3_2")
        requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
                      data={"chat_id": config.LOGGER_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

# ─────────────────────────────
# 🔥 STEP 1: YOUTUBE METADATA
# ─────────────────────────────
def get_youtube_metadata(query):
    for _ in range(3):
        api_key = get_next_key()
        if not api_key: break
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part": "snippet", "q": query, "type": "video", "maxResults": 1, "key": api_key}
        try:
            resp = requests.get(url, params=params, timeout=5).json()
            if "items" in resp and len(resp["items"]) > 0:
                item = resp["items"][0]
                return {"id": item["id"]["videoId"], "title": item["snippet"]["title"], "thumbnail": item["snippet"]["thumbnails"]["high"]["url"]}
        except: continue
    return None

# ─────────────────────────────
# 🔥 STEP 2: SUMIT API (DIRECT AUDIO) 🎵
# ─────────────────────────────
def get_audio_from_sumit(song_title):
    """
    Directly fetches working high-quality links from saavn.sumit.co
    """
    print(f"🎵 Searching Sumit API: {song_title}")
    try:
        # Search API Call
        url = f"https://saavn.sumit.co/api/search/songs?query={song_title}&limit=1"
        resp = requests.get(url, timeout=10).json()

        if resp.get("success") and resp.get("data") and resp["data"]["results"]:
            song = resp["data"]["results"][0]
            
            # downloadUrl list mein aakhri link hamesha best quality (320kbps) hota hai
            download_urls = song.get("downloadUrl", [])
            if not download_urls: return None
            
            final_link = download_urls[-1]["url"] # 320kbps verified URL
            
            # Extra Check: Verifying Link Status
            r = requests.head(final_link, timeout=5)
            if r.status_code == 200:
                return {
                    "link": final_link, 
                    "title": song.get("name"), 
                    "duration": format_duration(song.get("duration", 0))
                }
    except Exception as e:
        print(f"❌ API Error: {e}")
    return None

# ─────────────────────────────
# 🔥 STEP 3: BRIDGE (CATBOX)
# ─────────────────────────────
def bridge_to_catbox(jio_url):
    temp_file = f"/tmp/{uuid.uuid4()}.m4a"
    try:
        print("📥 Downloading Audio...")
        with requests.get(jio_url, stream=True, timeout=30, verify=False) as r:
            r.raise_for_status()
            with open(temp_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        print("📤 Uploading to Catbox...")
        with open(temp_file, "rb") as f:
            r = requests.post(CATBOX_UPLOAD, data={"reqtype": "fileupload"}, files={"fileToUpload": f}, timeout=120)
        
        os.remove(temp_file)
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except:
        if os.path.exists(temp_file): os.remove(temp_file)
    return None

# ─────────────────────────────
# 🚀 MAIN ROUTE
# ─────────────────────────────
@app.get("/getvideo")
async def get_video(query: str, key: str):
    start_time = time.time()

    # Auth Check
    doc = await keys_col.find_one({"api_key": key})
    if not doc or not doc.get("active", True): return {"status": 403, "error": "Invalid Key"}
    await keys_col.update_one({"api_key": key}, {"$inc": {"total_usage": 1}})

    # 1. YouTube Metadata
    yt_data = await asyncio.to_thread(get_youtube_metadata, query)
    if not yt_data: return {"status": 404, "error": "Not Found on YouTube"}
    
    video_id = yt_data["id"]

    # 2. DB Check (Cache)
    cached = await videos_col.find_one({"video_id": video_id})
    if cached and cached.get("catbox_link"):
        return {"status": 200, "title": cached["title"], "link": cached["catbox_link"], "id": video_id, "thumbnail": yt_data["thumbnail"], "duration": cached["duration"], "cached": True}

    # 3. Get Audio via Sumit API (One-Step Process) 🚀
    # Hum seedha original query bhej rahe hain kyunki Sumit API smart hai
    audio_data = await asyncio.to_thread(get_audio_from_sumit, query)
    
    # Fallback: Agar pehla fail ho toh YouTube title try karo
    if not audio_data:
        audio_data = await asyncio.to_thread(get_audio_from_sumit, yt_data["title"])

    if not audio_data: return {"status": 500, "error": "Audio Not Found on Server"}

    # 4. Bridge to Catbox (Permanent Storage)
    catbox_link = await asyncio.to_thread(bridge_to_catbox, audio_data["link"])
    if not catbox_link: return {"status": 500, "error": "Bridge Upload Failed"}

    # 5. Save to DB & Log
    await videos_col.update_one(
        {"video_id": video_id}, 
        {"$set": {
            "title": audio_data["title"], 
            "video_id": video_id, 
            "catbox_link": catbox_link, 
            "duration": audio_data["duration"], 
            "thumbnail": yt_data["thumbnail"],
            "cached_at": datetime.datetime.now()
        }}, upsert=True
    )
    asyncio.create_task(asyncio.to_thread(send_telegram_log, audio_data["title"], audio_data["duration"], catbox_link, video_id))

    return {
        "status": 200, "title": audio_data["title"], "duration": audio_data["duration"],
        "link": catbox_link, "id": video_id, "thumbnail": yt_data["thumbnail"],
        "cached": False, "response_time": f"{time.time()-start_time:.2f}s"
    }

@app.api_route("/", methods=["GET", "HEAD"])
async def home(): return {"status": "Running", "mode": "Sumit-API-V1"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
