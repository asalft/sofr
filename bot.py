# bot.py
"""
Telethon-based "approval gate" for private messages.
- Shows a welcome message with Inline buttons "قبول" و "رفض" on first private DM.
- If "قبول": يسجل المستخدم كمقبول ويُسمح له بالمراسلة.
- If "رفض": يُسجل كمُرفض، يُحظر (block)، ونحاول حذف التاريخ وإزالة الحوار محليًا.
- يخزن الحالات في SQLite.
- Uses StringSession via environment variable to be Heroku-friendly.
"""

import os
import asyncio
import sqlite3
from telethon import TelegramClient, events, Button, types
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest
from telethon.errors import FloodWaitError

# --- إعدادات (من environment) ---
API_ID = int(os.environ.get("API_ID", "27227913"))          # ضع هنا API ID
API_HASH = os.environ.get("API_HASH", "ba805b182eca99224403dbcd5d4f50aa")           # ضع هنا API HASH
STRING_SESSION = os.environ.get("STRING_SESSION", "1ApWapzMBu5v8ZCXS5VY2jGWQS8telT1luPammuF_yApdOY9wLfbBih6z6VDla5xzdmWJY7NfeW-d40tpMF4Oct9q2Y__p3lHTEMq_q_ieVB1Ix4ulGADTk3rzhQ9MsgNGlvB-sIBo3KxTH0MQyqNmcCQEe_EcCr2CGVQYT8tT-oht23WgBvC5px-dBRmdgdDesUM5DlAXTfWcWvXu8iq9R_5QuBZ4oXC0L1SYUQykSU2XG6sGOmSgpUQkH3UkKJh_w-2NxpNqJaNYtb1MpTkZHO7N0PS49wDIeuAUI-CMvXbkPOUEU1qznQYk-_1RJ_OTKXkNi38YnX4yDKglEv6X-AdT3WvmWM=")  # ضع هنا StringSession (لا ترفعها للـ GitHub)
SESSION_NAME = os.environ.get("SESSION_NAME", "session")
DB_PATH = os.environ.get("DB_PATH", "users.db")
WELCOME_TEXT = os.environ.get("WELCOME_TEXT", "أهلًا! قبل أن ترسل رسالة، الرجاء اختيار أحد الخيارات:\n\n(قبول = سيتم السماح بالكتابة إليّ، رفض = سيتم حظرك وحذف المحادثة.)")
MAX_PENDING = int(os.environ.get("MAX_PENDING", "20"))  # حد الطلبات المعلقة قبل أن نردّ "مشغول"

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

# helper DB functions
def set_user_status(user_id: int, status: str, note: str = None):
    cur.execute("INSERT OR REPLACE INTO users(user_id, status, note) VALUES (?, ?, ?)", (user_id, status, note))
    conn.commit()

def get_user_status(user_id: int):
    cur.execute("SELECT status FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None

def count_pending_requests():
    # pending considered as users neither accepted nor rejected but who were sent welcome?
    # For simplicity: count rows with status IS NULL doesn't apply. We'll track pending via in-memory dict.
    return len(pending_asks)

# In-memory pending map: user_id -> message_id of welcome
pending_asks = {}  # will be populated when we send welcome message

# --- handlers ---
@client.on(events.NewMessage(incoming=True))
async def handle_new_private(event):
    # only react to private, non-bot chats and not from ourselves
    if not event.is_private:
        return
    if event.sender_id == (await client.get_me()).id:
        return

    uid = event.sender_id

    # if user already accepted -> allow normal conversation (do nothing)
    status = get_user_status(uid)
    if status == "accepted":
        # Optional: nothing, allow messages through
        return
    if status == "rejected":
        # Block again just in case, try to clear history and delete dialog
        await handle_reject_user(uid, reason="rejected_prev")
        return

    # If we already sent welcome and it's pending, do not resend; optionally remind
    if uid in pending_asks:
        # optional: send a short reminder (or ignore)
        # await event.respond("لديك طلب قيد الانتظار. الرجاء الضغط على أحد الأزرار أدناه.")
        return

    # If server is busy (too many pending), send busy message and store pending (or decline)
    if count_pending_requests() >= MAX_PENDING:
        await event.respond("حالياً هناك ازدحام بالطلبات 🙇‍♂️. سَأعود إليك لاحقًا — تم تسجيل طلبك وسيتم الرد عليه عندما يتحسن الحمل.")
        # keep them in pending (but without sending buttons) or you may send buttons later
        pending_asks[uid] = None
        return

    # send welcome with inline buttons
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

# handle clicks on inline buttons (CallbackQuery)
@client.on(events.CallbackQuery)
async def callback_handler(event: events.CallbackQuery.Event):
    # Only handle callbacks from the same user who clicked (should be)
    uid = event.sender_id
    data = event.data  # bytes
    # guard: only respond if this user is pending OR not already accepted/rejected
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
            try:
                await event.answer("تم قبولك ✅")
            except:
                pass
        print(f"User {uid} accepted.")
    elif data == b"reject":
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.answer("تم رفضك وسيتم حـظرك الآن.", alert=True)
        await handle_reject_user(uid, reason="clicked_reject", query_event=event)
        print(f"User {uid} rejected and blocked.")
    else:
        await event.answer("زر غير معروف.", alert=True)

# function to block and try to delete history
async def handle_reject_user(user_id: int, reason: str = None, query_event=None):
    # try to revoke/delete history (may not remove other's messages on their side)
    try:
        # Delete history with revoke=True attempts to delete messages for both parties when allowed
        await client(DeleteHistoryRequest(peer=user_id, max_id=0, revoke=True))
    except Exception as e:
        print("DeleteHistory failed:", e)
    try:
        # Block the user
        await client(BlockRequest(id=user_id))
    except Exception as e:
        print("BlockRequest failed:", e)

    # delete dialog locally
    try:
        await client.delete_dialog(user_id)
    except Exception as e:
        print("delete_dialog failed:", e)

    # Optionally send a final message before blocking (we avoid as we block immediately)
    # store note with reason
    cur.execute("UPDATE users SET note = ? WHERE user_id = ?", (reason, user_id))
    conn.commit()

# safe startup
async def main():
    print("Starting client...")
    await client.start()
    me = await client.get_me()
    print(f"Logged in as {me.username or me.first_name} (id {me.id})")
    print("Listening for private messages... (CTRL+C to stop)")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Stopping...")
