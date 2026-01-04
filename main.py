import os
import subprocess
import requests
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from youtubesearchpython import VideosSearch

# ─────────────────────────────
# CONFIG
# ─────────────────────────────
MONGO_URL = os.getenv("MONGO_DB_URI")
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_GROUP_ID = os.getenv("LOG_GROUP_ID")

CATBOX_UPLOAD = "https://catbox.moe/user/api.php"
COOKIES_PATH = "/app/cookies.txt"

# ─────────────────────────────
# APP
# ─────────────────────────────
app = FastAPI(title="Sudeep Music API ⚡ Video Auto")

client = AsyncIOMotorClient(MONGO_URL)
db = client["MusicAPI_DB1"]
collection = db["videos_cachet"]

MEM_CACHE = {}

# ─────────────────────────────
# HELPERS
# ─────────────────────────────
def yt_url(video_id: str):
    return f"https://www.youtube.com/watch?v={video_id}"

def extract_video_id(q: str):
    q = q.strip()
    if len(q) == 11 and " " not in q:
        return q
    if "v=" in q:
        return q.split("v=")[1].split("&")[0]
    if "youtu.be/" in q:
        return q.split("youtu.be/")[1].split("?")[0]
    return None

def search_youtube(query: str):
    search = VideosSearch(query, limit=1)
    res = search.result().get("result")
    if not res:
        return None, None
    return res[0]["id"], res[0]["title"]

def send_logger(text: str):
    if not BOT_TOKEN or not LOG_GROUP_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": LOG_GROUP_ID, "text": text},
            timeout=10
        )
    except:
        pass

def upload_catbox(path: str):
    with open(path, "rb") as f:
        r = requests.post(
            CATBOX_UPLOAD,
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=120
        )
    if r.status_code == 200 and r.text.startswith("https://"):
        return r.text.strip()
    raise Exception("Catbox upload failed")

def auto_download_video(video_id: str) -> str:
    if not os.path.exists(COOKIES_PATH):
        raise Exception("cookies.txt missing")

    out = f"/tmp/{video_id}.mp4"

    cmd = [
        "python", "-m", "yt_dlp",
        "--cookies", COOKIES_PATH,
        "--js-runtimes", "node",
        "--no-playlist",
        "--geo-bypass",
        "--force-ipv4",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        yt_url(video_id),
        "-o", out
    ]

    subprocess.run(cmd, check=True, timeout=900)
    return out

# ─────────────────────────────
# MAIN VIDEO API
# ─────────────────────────────
@app.get("/getvideo")
async def get_video(query: str):
    # 1️⃣ extract or search
    video_id = extract_video_id(query)
    title = None

    if not video_id:
        video_id, title = search_youtube(query)
        if not video_id:
            raise HTTPException(404, "No video found")

    # 2️⃣ RAM cache
    if video_id in MEM_CACHE:
        return MEM_CACHE[video_id]

    # 3️⃣ DB cache
    cached = await collection.find_one({"video_id": video_id}, {"_id": 0})
    if cached:
        resp = {
            "t": cached["title"],
            "u": cached["catbox_link"],
            "id": video_id
        }
        MEM_CACHE[video_id] = resp
        return resp

    # 4️⃣ Auto download
    try:
        file_path = auto_download_video(video_id)
        catbox = upload_catbox(file_path)

        try:
            os.remove(file_path)
        except:
            pass

        if not title:
            title = video_id

        doc = {
            "video_id": video_id,
            "title": title,
            "catbox_link": catbox
        }

        await collection.update_one(
            {"video_id": video_id},
            {"$set": doc},
            upsert=True
        )

        resp = {
            "t": title,
            "u": catbox,
            "id": video_id
        }
        MEM_CACHE[video_id] = resp

        send_logger(
            f"🎥 New Video Added\n\n"
            f"🆔 {video_id}\n"
            f"🔗 {catbox}"
        )

        return resp

    except Exception as e:
        raise HTTPException(500, str(e))

# ─────────────────────────────
# HEALTH
# ─────────────────────────────
@app.api_route("/", methods=["GET", "HEAD"])
async def home():
    return {"status": "ok", "cache": len(MEM_CACHE)}
