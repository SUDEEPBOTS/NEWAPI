import os

# 1. MongoDB URI
MONGO_DB_URI = os.getenv("MONGO_DB_URI", "")

# 2. Bot Settings
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
LOGGER_ID = -1003639584506

# 3. PROXY / API SETTINGS
JIOSAAVN_URL = "https://jiosaavn-api-v3.vercel.app"

# 4. YOUTUBE API KEYS (Environment se load karega) 🔑
# Render me 'YOUTUBE_API_KEYS' variable bana ke comma separated keys daalna
_keys_str = os.getenv("YOUTUBE_API_KEYS", "")

if _keys_str:
    # Comma se tod kar list bana raha hai aur spaces hata raha hai
    YOUTUBE_API_KEYS = [key.strip() for key in _keys_str.split(",") if key.strip()]
else:
    # Agar galti se bhool gaya toh empty list
    YOUTUBE_API_KEYS = []
    print("⚠️ Warning: YOUTUBE_API_KEYS not found in Environment Variables!")
