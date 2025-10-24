from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
import os, asyncio

API_ID = int(os.environ.get("27227913"))
API_HASH = os.environ.get("ba805b182eca99224403dbcd5d4f50aa")
STRING_SESSION = os.environ.get("1ApWapzMBu5v8ZCXS5VY2jGWQS8telT1luPammuF_yApdOY9wLfbBih6z6VDla5xzdmWJY7NfeW-d40tpMF4Oct9q2Y__p3lHTEMq_q_ieVB1Ix4ulGADTk3rzhQ9MsgNGlvB-sIBo3KxTH0MQyqNmcCQEe_EcCr2CGVQYT8tT-oht23WgBvC5px-dBRmdgdDesUM5DlAXTfWcWvXu8iq9R_5QuBZ4oXC0L1SYUQykSU2XG6sGOmSgpUQkH3UkKJh_w-2NxpNqJaNYtb1MpTkZHO7N0PS49wDIeuAUI-CMvXbkPOUEU1qznQYk-_1RJ_OTKXkNi38YnX4yDKglEv6X-AdT3WvmWM=")

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
