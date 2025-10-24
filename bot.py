from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
import os, asyncio

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
STRING_SESSION = os.environ.get("STRING_SESSION")

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if event.is_private and not event.out:
        await client.send_message(
            event.chat_id,
            "اختبار أزرار إنلاين:",
            buttons=[
                [Button.inline("زر 1", b"b1"), Button.inline("زر 2", b"b2")]
            ]
        )

@client.on(events.CallbackQuery)
async def callback(event):
    await event.answer(f"ضغطت على الزر {event.data.decode()} ✅", alert=True)

async def main():
    await client.start()
    print("جاهز، جرّب تبعث رسالة من حساب ثاني.")
    await client.run_until_disconnected()

asyncio.run(main())
