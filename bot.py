import os
import time
import secrets
import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient

# ─────────────────────────────
# CONFIG
# ─────────────────────────────
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

MONGO_URL = os.getenv("MONGO_DB_URI")

ADMIN_ID = 8315544720
ADMIN_CONTACT = "@HEX_KING9"

FREE_DAYS = 2
DEFAULT_LIMIT = 50

# ─────────────────────────────
# DB
# ─────────────────────────────
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["API999_DB1"]
keys_col = db["api_users"]

# ─────────────────────────────
# BOT
# ─────────────────────────────
app = Client(
    "APIKeyBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ─────────────────────────────
# HELPERS
# ─────────────────────────────
def generate_key():
    return "999cores-" + secrets.token_hex(8)

def now_ts():
    return int(time.time())

def days_to_ts(days: int):
    return now_ts() + days * 86400

# ─────────────────────────────
# START
# ─────────────────────────────
@app.on_message(filters.command("start"))
async def start(_, m: Message):
    await m.reply(
        "👋 **Welcome to HanThar Music API Bot**\n\n"
        "📌 Use `/getapi` to generate your API key\n"
        "📌 Free access for 2 days\n\n"
        "api key ဝယ်ခြင်းပါက"
        f"🆘 Support: {ADMIN_CONTACT}"
    )

# ─────────────────────────────
# GET API KEY
# ─────────────────────────────
@app.on_message(filters.command("getapi"))
async def get_api(_, m: Message):
    user = m.from_user
    uid = user.id

    doc = await keys_col.find_one({"user_id": uid})

    if doc:
        exp = datetime.datetime.fromtimestamp(doc["expires_at"])
        await m.reply(
            "🔑 **Your API Key**\n\n"
            f"`{doc['api_key']}`\n\n"
            f"📆 Expires: `{exp}`\n"
            f"📊 Daily limit: `{doc['daily_limit']}`"
        )
        return

    api_key = generate_key()

    new_doc = {
        "user_id": uid,
        "api_key": api_key,
        "expires_at": days_to_ts(FREE_DAYS),
        "daily_limit": DEFAULT_LIMIT,
        "used_today": 0,
        "last_reset": str(datetime.date.today()),
        "active": True
    }

    await keys_col.insert_one(new_doc)

    await m.reply(
        "✅ **API Key Generated Successfully**\n\n"
        f"🔑 Key:\n`{api_key}`\n\n"
        f"⏳ Valid for **{FREE_DAYS} days**\n"
        f"📊 Daily limit: `{DEFAULT_LIMIT}`\n\n"
        "⚠️ Do not share your key!"
    )

# ─────────────────────────────
# ADMIN PANEL
# ─────────────────────────────
@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def admin_panel(_, m: Message):
    await m.reply(
        "🛠 **Admin Panel**\n\n"
        "/setlimit <user_id> <limit>\n"
        "/extend <user_id> <days>\n"
        "/disable <user_id>"
    )

# ─────────────────────────────
# SET LIMIT
# ─────────────────────────────
@app.on_message(filters.command("setlimit") & filters.user(ADMIN_ID))
async def set_limit(_, m: Message):
    try:
        _, uid, limit = m.text.split()
        uid = int(uid)
        limit = int(limit)

        await keys_col.update_one(
            {"user_id": uid},
            {"$set": {"daily_limit": limit}}
        )

        await m.reply(f"✅ Limit updated for `{uid}` → `{limit}`")

    except:
        await m.reply("❌ Usage: `/setlimit user_id limit`")

# ─────────────────────────────
# EXTEND
# ─────────────────────────────
@app.on_message(filters.command("extend") & filters.user(ADMIN_ID))
async def extend_key(_, m: Message):
    try:
        _, uid, days = m.text.split()
        uid = int(uid)
        days = int(days)

        doc = await keys_col.find_one({"user_id": uid})
        if not doc:
            await m.reply("❌ User not found")
            return

        new_exp = doc["expires_at"] + days * 86400

        await keys_col.update_one(
            {"user_id": uid},
            {"$set": {"expires_at": new_exp}}
        )

        await m.reply(f"✅ Extended `{uid}` by `{days}` days")

    except:
        await m.reply("❌ Usage: `/extend user_id days`")

# ─────────────────────────────
# DISABLE
# ─────────────────────────────
@app.on_message(filters.command("disable") & filters.user(ADMIN_ID))
async def disable_key(_, m: Message):
    try:
        _, uid = m.text.split()
        uid = int(uid)

        await keys_col.update_one(
            {"user_id": uid},
            {"$set": {"active": False}}
        )

        await m.reply(f"🚫 API key disabled for `{uid}`")

    except:
        await m.reply("❌ Usage: `/disable user_id`")

# ─────────────────────────────
# RUN
# ─────────────────────────────
app.run()
