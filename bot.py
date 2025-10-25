# bot.py
"""
Telethon-based approval gate + group reply logger.
Features:
- Handles private chats with "قبول" / "رفض".
- Blocks and deletes rejected users.
- Creates/uses a log group to store any messages that are replies to YOUR messages in groups.
"""

import os
import asyncio
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest, CreateChatRequest
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.errors import FloodWaitError, ChannelPrivateError

# ====== إعدادات الاتصال ======
API_ID = 27227913
API_HASH = "ba805b182eca99224403dbcd5d4f50aa"
STRING_SESSION = "1ApWapzMBu5v8ZCXS5VY2jGWQS8telT1luPammuF_yApdOY9wLfbBih6z6VDla5xzdmWJY7NfeW-d40tpMF4Oct9q2Y__p3lHTEMq_q_ieVB1Ix4ulGADTk3rzhQ9MsgNGlvB-sIBo3KxTH0MQyqNmcCQEe_EcCr2CGVQYT8tT-oht23WgBvC5px-dBRmdgdDesUM5DlAXTfWcWvXu8iq9R_5QuBZ4oXC0L1SYUQykSU2XG6sGOmSgpUQkH3UkKJh_w-2NxpNqJaNYtb1MpTkZHO7N0PS49wDIeuAUI-CMvXbkPOUEU1qznQYk-_1RJ_OTKXkNi38YnX4yDKglEv6X-AdT3WvmWM="# ضع StringSession هنا
SESSION_NAME = os.environ.get("SESSION_NAME", "session")
DB_PATH = os.environ.get("DB_PATH", "users.db")
WELCOME_TEXT = os.environ.get("WELCOME_TEXT", "أهلًا! قبل أن ترسل رسالة، اختر أحد الخيارين:\n\n(قبول = سيتم السماح بالكتابة إليّ، رفض = سيتم حظرك وحذف المحادثة.)")
MAX_PENDING = int(os.environ.get("MAX_PENDING", "20"))

if not API_ID or not API_HASH:
    raise SystemExit("❌ يجب تحديد API_ID و API_HASH في البيئة أو داخل الكود.")

# ====== تهيئة العميل ======
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# ====== قاعدة بيانات ======
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
LOG_GROUP_ID = None  # سيتم إنشاؤها تلقائيًا لاحقًا

# ====== إنشاء مجموعة السجلات ======
async def ensure_log_group():
    global LOG_GROUP_ID
    me = await client.get_me()
    title = f"LogGroup_{me.id}"
    try:
        result = await client(CreateChannelRequest(
            title=title,
            about="مجموعة لتخزين الرسائل التي يتم الرد عليها من حسابي.",
            megagroup=True
        ))
        LOG_GROUP_ID = result.chats[0].id
        print(f"✅ تم إنشاء مجموعة السجلات: {LOG_GROUP_ID}")
    except Exception as e:
        print("⚠️ فشل إنشاء المجموعة:", e)
        # حاول البحث عن مجموعة قديمة بنفس الاسم
        async for dialog in client.iter_dialogs():
            if dialog.name == title:
                LOG_GROUP_ID = dialog.id
                print(f"📁 تم العثور على مجموعة السجلات الموجودة مسبقًا: {LOG_GROUP_ID}")
                break
    if LOG_GROUP_ID is None:
        print("❌ لم يتم العثور على أو إنشاء مجموعة السجلات.")

# ====== دوال المساعدة ======
def set_user_status(user_id: int, status: str, note: str = None):
    cur.execute("INSERT OR REPLACE INTO users(user_id, status, note) VALUES (?, ?, ?)", (user_id, status, note))
    conn.commit()

def get_user_status(user_id: int):
    cur.execute("SELECT status FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None

# ====== التعامل مع الرسائل الخاصة ======
@client.on(events.NewMessage(incoming=True))
async def handle_private_and_groups(event):
    global LOG_GROUP_ID

    if event.is_private:
        uid = event.sender_id
        me = await client.get_me()
        if uid == me.id:
            return  # تجاهل رسائلك أنت
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
                try:
                    msg = await event.respond(
                        WELCOME_TEXT,
                        buttons=[[Button.inline("✅ قبول", b"accept"), Button.inline("❌ رفض", b"reject")]]
                    )
                    pending_asks[uid] = msg.id
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
            return

    # ====== رسائل المجموعات ======
    if event.is_group and LOG_GROUP_ID:
        try:
            me = await client.get_me()
            if not event.is_reply:
                return
            reply_msg = await event.get_reply_message()
            if reply_msg and reply_msg.sender_id == me.id:
                sender = await event.get_sender()
                chat = await event.get_chat()
                text = (
                    f"💬 *رد في مجموعة: {chat.title}*\n"
                    f"👤 من: [{sender.first_name}](tg://user?id={sender.id})\n\n"
                    f"📩 **الرسالة:**\n{event.raw_text}"
                )
                await client.send_message(LOG_GROUP_ID, text, link_preview=False)
        except ChannelPrivateError:
            print("⚠️ لا يمكن إرسال الرسالة إلى مجموعة السجلات (قد تكون خاصة أو محذوفة).")

# ====== الأزرار (قبول / رفض) ======
@client.on(events.CallbackQuery)
async def callback_handler(event):
    uid = event.sender_id
    data = event.data
    status = get_user_status(uid)
    if data == b"accept":
        set_user_status(uid, "accepted")
        pending_asks.pop(uid, None)
        await event.edit("تم قبولك ✅ يمكنك الآن المراسلة.")
    elif data == b"reject":
        set_user_status(uid, "rejected")
        pending_asks.pop(uid, None)
        await event.answer("تم رفضك وسيتم حظرك الآن.", alert=True)
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
    await ensure_log_group()
    print("🚀 يعمل الآن وينتظر الرسائل...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 تم الإيقاف.")
