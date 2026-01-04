import os
import time
import datetime
import subprocess
import requests
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from youtubesearchpython import VideosSearch
import yt_dlp  # yt_dlp को import करें

# ... (पहले का कोड same रहेगा) ...

def search_youtube(query: str):
    """
    Returns: {id, title, duration}
    """
    try:
        print(f"🔍 Searching YouTube for: {query}")  # Debug log
        s = VideosSearch(query, limit=1)
        result = s.result()
        print(f"📊 Raw search result: {result}")  # Debug log
        
        if not result or "result" not in result or not result["result"]:
            print("❌ No results found")
            return None
        
        video_data = result["result"][0]
        print(f"🎬 Found video: {video_data}")  # Debug log
        
        return {
            "id": video_data.get("id"),
            "title": video_data.get("title", "Unknown Title"),
            "duration": video_data.get("duration", "0:00"),
            "channel": video_data.get("channel", {}).get("name", "Unknown Channel"),
            "viewCount": video_data.get("viewCount", {}).get("text", "0 views"),
            "publishedTime": video_data.get("publishedTime", "Unknown")
        }
    except Exception as e:
        print(f"❌ Search error: {e}")
        return None

def get_video_info_with_ytdlp(video_id: str):
    """yt-dlp का उपयोग करके video की details प्राप्त करें"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            return {
                "id": video_id,
                "title": info.get('title', 'Unknown Title'),
                "duration": str(info.get('duration', 0)),
                "channel": info.get('uploader', 'Unknown Channel'),
                "viewCount": info.get('view_count', 0),
            }
    except Exception as e:
        print(f"❌ yt-dlp info error: {e}")
        return None

# ... (बाकी functions same रहेंगे) ...

@app.get("/getvideo")
async def get_video(query: str, key: str | None = None):
    if not key:
        return {"status": 401, "error": "API key required"}

    ok, err = await verify_api_key(key)
    if not ok:
        return {"status": 403, "error": err}

    video_id = extract_video_id(query)
    print(f"🎯 Input query: '{query}' -> Extracted video_id: '{video_id}'")  # Debug log

    # 🔎 Search if needed
    if not video_id:
        print(f"🔍 Performing search for: '{query}'")
        data = search_youtube(query)
        if not data or not data.get("id"):
            return {
                "status": 404,
                "error": "Video not found",
                "title": None,
                "duration": None,
                "link": None,
                "video_id": None
            }

        video_id = data["id"]
        title = data["title"]
        duration = data["duration"]
        print(f"✅ Search successful - ID: {video_id}, Title: {title}")
    else:
        # Video ID directly दिया गया है
        print(f"🎬 Direct video ID: {video_id}")
        data = search_youtube(video_id)
        if data:
            title = data["title"]
            duration = data["duration"]
        else:
            # yt-dlp से कोशिश करें
            data = get_video_info_with_ytdlp(video_id)
            if data:
                title = data["title"]
                duration = data["duration"]
            else:
                title = "Unknown Title"
                duration = "0:00"

    # ⚡ RAM Cache
    if video_id in MEM_CACHE:
        print(f"⚡ Serving from RAM cache: {video_id}")
        return MEM_CACHE[video_id]

    # 💾 DB Cache
    cached = await videos_col.find_one({"video_id": video_id})
    if cached:
        resp = {
            "status": 200,
            "title": cached["title"],
            "duration": cached.get("duration", "unknown"),
            "link": cached["catbox_link"],
            "video_id": video_id,
            "cached": True
        }
        MEM_CACHE[video_id] = resp
        print(f"💾 Serving from DB cache: {video_id}")
        return resp

    # ⬇️ Download → Catbox
    try:
        print(f"⬇️ Downloading video: {video_id}")
        file_path = auto_download_video(video_id)
        print(f"✅ Downloaded to: {file_path}")
        
        print(f"📤 Uploading to Catbox...")
        catbox = upload_catbox(file_path)
        print(f"✅ Uploaded: {catbox}")

        try:
            os.remove(file_path)
            print(f"🗑️ Cleaned temp file: {file_path}")
        except:
            pass

        # अगर title और duration अभी तक नहीं मिले, तो फिर से कोशिश करें
        if not title or title == "Unknown Title":
            data = get_video_info_with_ytdlp(video_id)
            if data:
                title = data["title"]
                duration = data["duration"]

        await videos_col.update_one(
            {"video_id": video_id},
            {"$set": {
                "video_id": video_id,
                "title": title or f"Video {video_id}",
                "duration": duration or "unknown",
                "catbox_link": catbox,
                "cached_at": datetime.datetime.utcnow()
            }},
            upsert=True
        )

        resp = {
            "status": 200,
            "title": title or f"Video {video_id}",
            "duration": duration or "unknown",
            "link": catbox,
            "video_id": video_id,
            "cached": False
        }

        MEM_CACHE[video_id] = resp
        return resp

    except subprocess.TimeoutExpired:
        return {
            "status": 408,
            "error": "Download timeout (15 minutes)",
            "title": title,
            "duration": duration,
            "link": None,
            "video_id": video_id
        }
    except Exception as e:
        print(f"❌ Error in get_video: {e}")
        return {
            "status": 500,
            "error": str(e),
            "title": title,
            "duration": duration,
            "link": None,
            "video_id": video_id
        }

# Debug endpoint
@app.get("/debug/search")
async def debug_search(query: str):
    """Search को debug करने के लिए endpoint"""
    result = search_youtube(query)
    return {
        "query": query,
        "result": result,
        "raw": VideosSearch(query, limit=1).result() if result else None
    }

@app.get("/debug/ytdlp")
async def debug_ytdlp(video_id: str):
    """yt-dlp से info प्राप्त करने के लिए endpoint"""
    info = get_video_info_with_ytdlp(video_id)
    return {
        "video_id": video_id,
        "info": info
        }
