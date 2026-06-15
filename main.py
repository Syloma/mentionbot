import asyncio
import html
import os
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import ChatAdminRequiredError, FloodWaitError
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
SESSION_NAME = str(DATA_DIR / "mentionbot")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError(
        "TG_API_ID, TG_API_HASH ve TG_BOT_TOKEN ortam degiskenleri ayarlanmali.\n"
        "Ornek:\n"
        "$env:TG_API_ID='123456'\n"
        "$env:TG_API_HASH='abcdef...'\n"
        "$env:TG_BOT_TOKEN='123:ABC'"
    )


client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)


def clean_text(value: str | None, fallback: str) -> str:
    value = (value or "").strip()
    return html.escape(value or fallback)


def user_name(user) -> str:
    full_name = " ".join(
        part for part in [getattr(user, "first_name", None), getattr(user, "last_name", None)] if part
    ).strip()
    if full_name:
        return full_name
    if getattr(user, "username", None):
        return f"@{user.username}"
    return f"Kullanici {user.id}"


def mention_html(user) -> str:
    return f'<a href="tg://user?id={user.id}">{clean_text(user_name(user), str(user.id))}</a>'


def command_text(event) -> str:
    parts = (event.raw_text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def chunk_mentions(prefix: str, users: list, limit: int = 3600) -> list[str]:
    chunks: list[str] = []
    current = clean_text(prefix, "Duyuru")
    if current:
        current += "\n\n"

    for user in users:
        mention = mention_html(user)
        candidate = f"{current} {mention}".strip()
        if len(candidate) > limit and current.strip():
            chunks.append(current.strip())
            current = mention
        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks


async def is_group_admin(event) -> bool:
    if not event.is_group:
        return False

    try:
        participant = await client.get_permissions(event.chat_id, event.sender_id)
    except Exception:
        return False

    return isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator))


async def get_group_users(chat_id: int) -> list:
    users = []
    async for user in client.iter_participants(chat_id):
        if not getattr(user, "bot", False) and not getattr(user, "deleted", False):
            users.append(user)
    return users


@client.on(events.NewMessage(pattern=r"^/(start|baslat)(@\w+)?$"))
async def start_handler(event):
    await event.reply(
        "Etiket botu hazir.\n\n"
        "/herkes mesaj - gruptaki herkesi etiketler\n"
        "/etiketle mesaj - /herkes ile ayni\n"
        "/liste - cekilebilen uye sayisini gosterir\n\n"
        "Botun grupta admin olmasi gerekir."
    )


@client.on(events.NewMessage(pattern=r"^/(liste|uyeler)(@\w+)?$"))
async def list_handler(event):
    if not event.is_group:
        await event.reply("Bu komut grup veya supergroup icinde kullanilmali.")
        return

    if not await is_group_admin(event):
        await event.reply("Bu komutu sadece grup yoneticileri kullanabilir.")
        return

    try:
        users = await get_group_users(event.chat_id)
    except ChatAdminRequiredError:
        await event.reply("Uyeleri cekemedim. Botu grupta admin yapman gerekiyor.")
        return

    await event.reply(f"Cekilebilen uye sayisi: {len(users)}")


@client.on(events.NewMessage(pattern=r"^/(herkes|etiketle)(@\w+)?(?:\s|$)"))
async def mention_all_handler(event):
    if not event.is_group:
        await event.reply("Bu komut grup veya supergroup icinde kullanilmali.")
        return

    if not await is_group_admin(event):
        await event.reply("Bu komutu sadece grup yoneticileri kullanabilir.")
        return

    status_message = await event.reply("Uyeler cekiliyor...")

    try:
        users = await get_group_users(event.chat_id)
    except ChatAdminRequiredError:
        await status_message.edit("Uyeleri cekemedim. Botu grupta admin yapman gerekiyor.")
        return

    if not users:
        await status_message.edit("Etiketlenecek uye bulunamadi.")
        return

    await status_message.edit(f"{len(users)} uye bulundu, etiketleniyor...")

    prefix = command_text(event) or "Duyuru"
    for chunk in chunk_mentions(prefix, users):
        try:
            await client.send_message(event.chat_id, chunk, parse_mode="html", link_preview=False)
            await asyncio.sleep(0.8)
        except FloodWaitError as exc:
            await asyncio.sleep(exc.seconds + 1)
            await client.send_message(event.chat_id, chunk, parse_mode="html", link_preview=False)

    await status_message.delete()


async def main() -> None:
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    print(f"Etiket botu aktif: @{me.username or me.id}")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
