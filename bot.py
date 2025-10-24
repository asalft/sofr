# bot.py
import os
import asyncio
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest, CreateChatRequest
from telethon.errors import FloodWaitError

# --- إعدادات ---
API_ID = int(os.environ.get("API_ID", "27227913"))              # ضع API_ID هنا أو كمتغير بيئة
API_HASH = os.environ.get("API_HASH", "ba805b182eca99224403dbcd5d4f50aa")  # ضع API_HASH هنا
STRING_SESSION = os.environ.get(
    "STRING_SESSION",
    "1ApWapzMBu5v8ZCXS5VY2jGWQS8telT1luPammuF_yApdOY9wLfbBih6z6VDla5xzdmWJY7NfeW-d40tpMF4Oct9q2Y__p3lHTEMq_q_ieVB1Ix4ulGADTk3rzhQ9MsgNGlvB-sIBo3KxTH0MQyqNmcCQEe_EcCr2CGVQYT8tT-oht23WgBvC5px-dBRmdgdDesUM5DlAXTfWcWvXu8iq9R_5QuBZ4oXC0L1SYUQykSU2XG6sGOmSgpUQkH3UkKJh_w-2NxpNqJaNYtb1MpTkZHO7N0PS49wDIeuAUI-CMvXbkPOUEU1qznQYk-_1RJ_OTKXkNi38YnX4yDKglEv6X-AdT3WvmWM="
)
DB_PATH = os.environ.get("DB_PATH", "users.db")
WELCOME_TEXT = os.environ.get(
    "WELCOME_TEXT",
    "أهلًا! قبل أن ترسل رسالة، الرجاء اختيار أحد الخيارات:\n\n(قبول = سيتم السماح بالكتابة إليّ، رفض = سيتم حظرك وحذف المحادثة.)",
)
MAX_PENDING = int(os.environ.get("MAX_PENDING", "20"))

# --- التهيئة ---
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# --- قاعدة البيانات ---
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    note TEXT,
    ts INTEGER DEFAULT (strftime('%s','now'))
)
"""
)
conn.commit()

def set_user_status(user_id: int, status: str, note: str = None):
    cur.execute(
        "INSERT OR REPLACE INTO users(user_id, status, note) VALUES (?, ?, ?)",
        (user_id, status, note),
    )
    conn.commit()

def get_user_status(user_id: int):
    cur.execute("SELECT status FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None

pending_asks = {}
def count_pending_requests():
    return len(pending_asks)

# --- إنشاء مجموعة لتسجيل الرسائل ---
log_group_id = None
async def ensure_log_group():
    global log_group_id
    if log_group_id:
        return log_group_id
    me = await client.get_me()
    res = await client(CreateChatRequest(users=[me.id], title="رسائل البوت"))
    log_group_id = res.chats[0].id
    print(f"Log group created: {log_group_id}")
    return log_group_id

async def log_message(event):
    gid = await ensure_log_group()
    sender = await event.get_sender()
    name = sender.first_name if sender else "Unknown"
    chat = await event.get_chat()
    chat_name = getattr(chat, "title", "Private Chat")
    text = event.text or "<non-text>"
    msg = f"📩 من: {name} ({event.sender_id})\nالمحادثة: {chat_name}\nالنص: {text}"
    try:
        await client.send_message(gid, msg)
    except Exception as e:
        print("log fail:", e)

# --- الرسائل الجديدة ---
@client.on(events.NewMessage(incoming=True))
async def on_message(event):
    await log_message(event)
    if not event.is_private:
        return
    uid = event.sender_id
    me_id = (await client.get_me()).id
    if uid == me_id:
        return
    status = get_user_status(uid)

    # رفض يدوي
    if event.raw_text.strip().lower() in ["رفض", "❌ رفض", "no", "reject"]:
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.respond("تم رفضك وسيتم حظرك ❌")
        await handle_reject(uid, "typed_reject")
        return

    # قبول يدوي
    if event.raw_text.strip().lower() in ["قبول", "✅ قبول", "yes", "accept"]:
        set_user_status(uid, "accepted")
        pending_asks.pop(uid, None)
        await event.respond("تم قبولك ✅ يمكنك الآن المراسلة.")
        return

    # حذف رسائل غير المقبولين
    if status not in ["accepted", "rejected"]:
        try:
            await event.delete()
        except Exception:
            pass

    if status == "rejected":
        await handle_reject(uid, "rejected_prev")
        return

    if uid in pending_asks:
        return

    if count_pending_requests() >= MAX_PENDING:
        await event.respond("الطلبات كثيرة حاليًا، حاول لاحقًا 🙏")
        pending_asks[uid] = None
        return

    welcome = await event.respond(
        WELCOME_TEXT,
        buttons=[[Button.inline("✅ قبول", b"accept"), Button.inline("❌ رفض", b"reject")]],
    )
    pending_asks[uid] = welcome.id

# --- الأزرار ---
@client.on(events.CallbackQuery)
async def on_button(event):
    uid = event.sender_id
    data = event.data
    status = get_user_status(uid)
    if status == "accepted":
        await event.answer("أنت مقبول بالفعل ✅", alert=True)
        return
    if status == "rejected":
        await event.answer("لقد تم حظرك سابقًا.", alert=True)
        return
    if data == b"accept":
        set_user_status(uid, "accepted")
        pending_asks.pop(uid, None)
        await event.edit("تم قبولك ✅")
    elif data == b"reject":
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.answer("تم رفضك وسيتم حظرك الآن.", alert=True)
        await handle_reject(uid, "clicked_reject")

# --- حظر المستخدم ---
async def handle_reject(user_id: int, reason: str):
    try:
        await client(DeleteHistoryRequest(peer=user_id, max_id=0, revoke=True))
    except Exception:
        pass
    try:
        await client(BlockRequest(id=user_id))
    except Exception:
        pass
    try:
        await client.delete_dialog(user_id)
    except Exception:
        pass
    cur.execute("UPDATE users SET note = ? WHERE user_id = ?", (reason, user_id))
    conn.commit()

# --- التشغيل ---
async def main():
    print("Starting client...")
    await client.start()
    me = await client.get_me()
    print(f"Logged in as {me.first_name}")
    await ensure_log_group()
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
