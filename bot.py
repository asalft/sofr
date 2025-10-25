# bot.py
"""
Telegram approval gate for private messages using Telethon.
Features:
- Deletes messages from unapproved users
- Allows "قبول" / "رفض" via buttons or text
- Blocks rejected users and clears conversation
- Whitelist: users in this list bypass approval
"""

import os
import asyncio
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest
from telethon.errors import FloodWaitError

# ====== إعدادات الاتصال ======
API_ID = int(os.environ.get("API_ID", "27227913"))  # ضع API_ID هنا أو كمتغير بيئة
API_HASH = os.environ.get("API_HASH", "ba805b182eca99224403dbcd5d4f50aa")  # ضع API_HASH هنا
STRING_SESSION = os.environ.get("STRING_SESSION", "1ApWapzMBu5v8ZCXS5VY2jGWQS8telT1luPammuF_yApdOY9wLfbBih6z6VDla5xzdmWJY7NfeW-d40tpMF4Oct9q2Y__p3lHTEMq_q_ieVB1Ix4ulGADTk3rzhQ9MsgNGlvB-sIBo3KxTH0MQyqNmcCQEe_EcCr2CGVQYT8tT-oht23WgBvC5px-dBRmdgdDesUM5DlAXTfWcWvXu8iq9R_5QuBZ4oXC0L1SYUQykSU2XG6sGOmSgpUQkH3UkKJh_w-2NxpNqJaNYtb1MpTkZHO7N0PS49wDIeuAUI-CMvXbkPOUEU1qznQYk-_1RJ_OTKXkNi38YnX4yDKglEv6X-AdT3WvmWM=")  # ضع StringSession هنا
DB_PATH = os.environ.get("DB_PATH", "users.db")
WELCOME_TEXT = os.environ.get(
    "WELCOME_TEXT",
    "أهلًا! قبل أن ترسل رسالة، اختر أحد الخيارين:\n\n(قبول = سيتم السماح بالكتابة إليّ، رفض = سيتم حظرك وحذف المحادثة.)"
)
MAX_PENDING = int(os.environ.get("MAX_PENDING", "20"))

# ====== قائمة المسموحين مسبقًا ======
WHITELIST = [
    8466640160,  # ضع هنا أيديات الأشخاص المسموح لهم
    8060903976,
]

if not API_ID or not API_HASH:
    raise SystemExit("❌ يجب تحديد API_ID و API_HASH في البيئة أو داخل الكود.")

# ====== تهيئة العميل ======
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# ====== قاعدة البيانات ======
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    note TEXT,
    ts INTEGER DEFAULT (strftime('%s','now'))
)
""")
conn.commit()

pending_asks = {}

# ====== دوال المساعدة ======
def set_user_status(user_id: int, status: str, note: str = None):
    cur.execute("INSERT OR REPLACE INTO users(user_id, status, note) VALUES (?, ?, ?)", (user_id, status, note))
    conn.commit()

def get_user_status(user_id: int):
    cur.execute("SELECT status FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None

def count_pending_requests():
    return len(pending_asks)

# ====== التعامل مع الرسائل الخاصة ======
@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handle_private(event):
    uid = event.sender_id
    me = await client.get_me()
    if uid == me.id:
        return  # تجاهل رسائلك أنت

    # ====== تحقق Whitelist ======
    if uid in WHITELIST:
        return  # يسمح له بالمراسلة مباشرة بدون عرض قبول/رفض

    status = get_user_status(uid)

    # رفض يدوي
    if event.raw_text.strip().lower() in ["رفض", "❌ رفض", "no", "reject"]:
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.respond("تم رفضك وسيتم حظرك الآن ❌")
        await handle_reject_user(uid, reason="typed_reject")
        return

    # قبول يدوي
    if event.raw_text.strip().lower() in ["قبول", "✅ قبول", "yes", "accept"]:
        set_user_status(uid, "accepted")
        pending_asks.pop(uid, None)
        await event.respond("تم قبولك ✅ يمكنك الآن المراسلة بحرية.")
        return

    # حذف أي رسالة قبل القبول
    if status not in ["accepted", "rejected"]:
        try:
            await event.delete()
        except Exception:
            pass

        if uid not in pending_asks:
            # إرسال رسالة الترحيب مع الأزرار
            try:
                msg = await event.respond(
                    WELCOME_TEXT,
                    buttons=[[Button.inline("✅ قبول", b"accept"), Button.inline("❌ رفض", b"reject")]]
                )
                pending_asks[uid] = msg.id
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
        return

# ====== التعامل مع أزرار القبول والرفض ======
@client.on(events.CallbackQuery)
async def callback_handler(event):
    uid = event.sender_id
    data = event.data
    status = get_user_status(uid)

    if status == "accepted":
        await event.answer("✅ أنت مقبول بالفعل.", alert=True)
        return
    if status == "rejected":
        await event.answer("🚫 لقد تم حظرك سابقًا.", alert=True)
        return

    if data == b"accept":
        set_user_status(uid, "accepted")
        pending_asks.pop(uid, None)
        try:
            await event.edit("✅ تم قبولك ويمكنك الآن المراسلة بحرية.")
        except:
            await event.answer("✅ تم قبولك.", alert=True)

    elif data == b"reject":
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.answer("❌ تم رفضك وسيتم حظرك الآن.", alert=True)
        await handle_reject_user(uid, reason="clicked_reject")

# ====== حظر المستخدم وحذف المحادثة ======
async def handle_reject_user(user_id: int, reason: str = None):
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

# ====== بدء التشغيل ======
async def main():
    await client.start()
    me = await client.get_me()
    print(f"✅ تم تسجيل الدخول كـ: {me.first_name} (ID: {me.id})")
    print("🚀 يعمل الآن وينتظر الرسائل الخاصة...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 تم الإيقاف.")
