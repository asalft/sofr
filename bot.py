# bot.py
"""
Telethon-based approval gate + message logging to a group.
Features:
- Private messages approval: "قبول" / "رفض"
- Deletes messages from users who are not accepted
- Blocks users who type "رفض"
- Logs all messages (private or groups) to a new group with info
"""

import os
import asyncio
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest, CreateChatRequest, SendMessageRequest
from telethon.errors import FloodWaitError

# --- إعدادات (من environment) ---
API_ID = int(os.environ.get("API_ID", "27227913")
API_HASH = os.environ.get("API_HASH", "ba805b182eca99224403dbcd5d4f50aa")
STRING_SESSION = os.environ.get("STRING_SESSION", "1ApWapzMBu5v8ZCXS5VY2jGWQS8telT1luPammuF_yApdOY9wLfbBih6z6VDla5xzdmWJY7NfeW-d40tpMF4Oct9q2Y__p3lHTEMq_q_ieVB1Ix4ulGADTk3rzhQ9MsgNGlvB-sIBo3KxTH0MQyqNmcCQEe_EcCr2CGVQYT8tT-oht23WgBvC5px-dBRmdgdDesUM5DlAXTfWcWvXu8iq9R_5QuBZ4oXC0L1SYUQykSU2XG6sGOmSgpUQkH3UkKJh_w-2NxpNqJaNYtb1MpTkZHO7N0PS49wDIeuAUI-CMvXbkPOUEU1qznQYk-_1RJ_OTKXkNi38YnX4yDKglEv6X-AdT3WvmWM=")
SESSION_NAME = os.environ.get("SESSION_NAME", "session")
DB_PATH = os.environ.get("DB_PATH", "users.db")
WELCOME_TEXT = os.environ.get("WELCOME_TEXT",
    "أهلًا! قبل أن ترسل رسالة، الرجاء اختيار أحد الخيارات:\n\n"
    "(قبول = سيتم السماح بالكتابة إليّ، رفض = سيتم حظرك وحذف المحادثة.)"
)
MAX_PENDING = int(os.environ.get("MAX_PENDING", "20")

if not API_ID or not API_HASH:
    raise SystemExit("You must set API_ID and API_HASH in environment variables.")

# --- تهيئة الـ client ---
if STRING_SESSION:
    client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
else:
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# --- قاعدة بيانات SQLite بسيطة ---
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL, -- 'accepted' | 'rejected'
    note TEXT,
    ts INTEGER DEFAULT (strftime('%s','now'))
)
""")
conn.commit()

# --- helper DB functions ---
def set_user_status(user_id: int, status: str, note: str = None):
    cur.execute("INSERT OR REPLACE INTO users(user_id, status, note) VALUES (?, ?, ?)",
                (user_id, status, note))
    conn.commit()

def get_user_status(user_id: int):
    cur.execute("SELECT status FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None

# pending map: user_id -> message_id of welcome
pending_asks = {}

def count_pending_requests():
    return len(pending_asks)

# --- إنشاء مجموعة لتسجيل الرسائل تلقائيًا ---
log_group_id = None  # سيتم تحديده بعد الإنشاء

async def ensure_log_group():
    global log_group_id
    if log_group_id:
        return log_group_id
    me = await client.get_me()
    try:
        # إنشاء مجموعة جديدة باسم "رسائل البوت"
        res = await client(CreateChatRequest(users=[me.id], title="رسائل البوت"))
        log_group_id = res.chats[0].id
        print(f"Log group created: {log_group_id}")
    except Exception as e:
        print("Log group creation failed:", e)
        # إذا فشل، يمكن استخدام مجموعة موجودة يدويًا
    return log_group_id

async def log_message_to_group(message_event):
    gid = await ensure_log_group()
    sender = await message_event.get_sender()
    sender_name = sender.first_name if sender else "Unknown"
    chat = await message_event.get_chat()
    chat_name = getattr(chat, 'title', 'Private Chat')
    text = message_event.text or "<non-text message>"
    log_text = f"📩 From: {sender_name} ({message_event.sender_id})\nChat: {chat_name}\nMessage: {text}"
    try:
        await client.send_message(gid, log_text)
    except Exception as e:
        print("Failed to log message:", e)

# --- handler for new private messages ---
@client.on(events.NewMessage(incoming=True))
async def handle_new_private(event):
    # --- Log all messages first ---
    await log_message_to_group(event)

    if not event.is_private:
        return

    uid = event.sender_id
    me_id = (await client.get_me()).id
    if uid == me_id:
        return

    status = get_user_status(uid)

    # --- Handle typed "رفض" ---
    if event.raw_text.strip().lower() in ["رفض", "❌ رفض", "no", "reject"]:
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.respond("تم رفضك وسيتم حظرك الآن ❌")
        await handle_reject_user(uid, reason="typed_reject")
        print(f"User {uid} rejected manually (typed).")
        return

    # --- Handle typed "قبول" ---
    if event.raw_text.strip().lower() in ["قبول", "✅ قبول", "yes", "accept"]:
        set_user_status(uid, "accepted")
        pending_asks.pop(uid, None)
        await event.respond("تم قبولك ✅ يمكنك الآن المراسلة بحرية.")
        print(f"User {uid} accepted manually (typed).")
        return

    # --- Delete any message from pending users ---
    if status is None or status not in ["accepted", "rejected"]:
        try:
            await event.delete()
        except Exception as e:
            print(f"Failed to delete message from {uid}: {e}")

    # --- If user is rejected ---
    if status == "rejected":
        await handle_reject_user(uid, reason="rejected_prev")
        return

    # --- Handle welcome message ---
    if uid in pending_asks:
        return

    if count_pending_requests() >= MAX_PENDING:
        await event.respond("حالياً هناك ازدحام بالطلبات 🙇‍♂️. سَأعود إليك لاحقًا.")
        pending_asks[uid] = None
        return

    try:
        welcome = await event.respond(
            WELCOME_TEXT,
            buttons=[
                [Button.inline("✅ قبول", b"accept"), Button.inline("❌ رفض", b"reject")]
            ]
        )
        pending_asks[uid] = welcome.id
    except FloodWaitError as e:
        print("Flood wait, sleeping", e.seconds)
        await asyncio.sleep(e.seconds)

# --- handle inline button clicks ---
@client.on(events.CallbackQuery)
async def callback_handler(event: events.CallbackQuery.Event):
    uid = event.sender_id
    data = event.data
    status = get_user_status(uid)

    if status == "accepted":
        await event.answer("أنت مُسجل مُسبقًا كمقبول ✅", alert=True)
        return
    if status == "rejected":
        await event.answer("لقد تم حظرك سابقًا.", alert=True)
        return

    if data == b"accept":
        set_user_status(uid, "accepted")
        pending_asks.pop(uid, None)
        try:
            await event.edit("شكرًا! تم قبولك — يمكنك الآن مراسلتي. ✅")
        except:
            await event.answer("تم قبولك ✅")
        print(f"User {uid} accepted via button.")
    elif data == b"reject":
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.answer("تم رفضك وسيتم حـظرك الآن.", alert=True)
        await handle_reject_user(uid, reason="clicked_reject", query_event=event)
        print(f"User {uid} rejected via button and blocked.")
    else:
        await event.answer("زر غير معروف.", alert=True)

# --- block and delete user ---
async def handle_reject_user(user_id: int, reason: str = None, query_event=None):
    try:
        await client(DeleteHistoryRequest(peer=user_id, max_id=0, revoke=True))
    except Exception as e:
        print("DeleteHistory failed:", e)
    try:
        await client(BlockRequest(id=user_id))
    except Exception as e:
        print("BlockRequest failed:", e)
    try:
        await client.delete_dialog(user_id)
    except Exception as e:
        print("delete_dialog failed:", e)
    cur.execute("UPDATE users SET note = ? WHERE user_id = ?", (reason, user_id))
    conn.commit()

# --- startup ---
async def main():
    print("Starting client...")
    await client.start()
    me = await client.get_me()
    print(f"Logged in as {me.username or me.first_name} (id {me.id})")
    await ensure_log_group()
    print("Listening for messages...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Stopping...")
