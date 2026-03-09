import asyncio
import os
import logging
import yt_dlp
from PIL import Image
from mutagen.mp4 import MP4, MP4Cover
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# ==============================
# CONFIG
# ==============================

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
THUMB_PATH = os.path.join(BASE_DIR, "nx.jpeg")
COOKIES_PATH = os.path.join(BASE_DIR, "cookies.txt")  # если нужен для авторизации

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==============================
# BOT INIT
# ==============================

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

search_cache = {}
music_cache = {}

# ==============================
# YTDLP SETTINGS
# ==============================

YDL_OPTIONS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "cookiefile": COOKIES_PATH,
    "quiet": True,
    "no_warnings": True,
    "nocheckcertificate": True,
    "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
    "retries": 10,
    "fragment_retries": 10,
    "concurrent_fragment_downloads": 5,
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
            "preferredquality": "192",
        }
    ],
}

# ==============================
# CLEANUP
# ==============================

def cleanup_downloads():
    files = os.listdir(DOWNLOAD_DIR)
    if len(files) > 50:
        for f in files[:20]:
            try:
                os.remove(os.path.join(DOWNLOAD_DIR, f))
            except:
                pass

# ==============================
# DOWNLOAD AND PREPARE
# ==============================

async def download_and_prepare(url, video_id):
    loop = asyncio.get_event_loop()

    def process():
        opt_thumb = os.path.join(DOWNLOAD_DIR, f"{video_id}_thumb.jpg")

        # Обработка обложки
        if os.path.exists(THUMB_PATH):
            with Image.open(THUMB_PATH) as img:
                img = img.convert("RGB")
                img = img.resize((600, 600), Image.LANCZOS)
                img.save(opt_thumb, "JPEG", quality=95)

        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=True)
            final_file = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".m4a"
            title = info.get("title", "Music")

            if os.path.exists(final_file) and os.path.exists(opt_thumb):
                try:
                    audio = MP4(final_file)
                    with open(opt_thumb, "rb") as f:
                        audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
                    audio["\xa9nam"] = title
                    audio["\xa9ART"] = "Nexis Music"
                    audio.save()
                except Exception as e:
                    logging.error(f"Metadata error: {e}")

            return final_file, title, opt_thumb

    return await loop.run_in_executor(None, process)

# ==============================
# PAGINATION KEYBOARD
# ==============================

def get_pagination_keyboard(items, page: int, query_id: str):
    items_per_page = 5
    start = page * items_per_page
    end = start + items_per_page
    builder = InlineKeyboardBuilder()

    for item in items[start:end]:
        title = item["title"]
        if len(title) > 40:
            title = title[:40] + "..."
        builder.row(types.InlineKeyboardButton(text=f"🎵 {title}", callback_data=f"dl_{item['id']}"))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{query_id}_{page-1}"))

    total_pages = (len(items) - 1) // items_per_page + 1
    nav.append(types.InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))

    if end < len(items):
        nav.append(types.InlineKeyboardButton(text="➡️ Вперед", callback_data=f"page_{query_id}_{page+1}"))

    builder.row(*nav)
    return builder.as_markup()

# ==============================
# START COMMAND
# ==============================

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🎧 <b>Nexis Music</b>\n\nОтправь название песни — я найду её.")

# ==============================
# SEARCH SONG
# ==============================

@dp.message(F.text & ~F.text.startswith("/"))
async def search_song(message: types.Message):
    status = await message.answer("🔎 <b>Ищу...</b>")
    try:
        with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True}) as ydl:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch20:{message.text}", download=False))

        if not info or not info.get("entries"):
            await status.edit_text("❌ Ничего не найдено")
            return

        query_id = str(message.message_id)
        search_cache[query_id] = info["entries"]

        await status.delete()

        results_msg = await message.answer(
            f"✨ <b>Результаты для:</b> {message.text}",
            reply_markup=get_pagination_keyboard(info["entries"], 0, query_id)
        )

        search_cache[f"msg_{query_id}"] = results_msg.message_id

    except Exception:
        await status.edit_text("⚠️ Ошибка поиска")

# ==============================
# PAGINATION
# ==============================

@dp.callback_query(F.data.startswith("page_"))
async def pages(callback: types.CallbackQuery):
    _, query_id, page = callback.data.split("_")
    page = int(page)
    if query_id not in search_cache:
        await callback.answer("Результаты устарели", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=get_pagination_keyboard(search_cache[query_id], page, query_id))
    await callback.answer(cache_time=5)

# ==============================
# DOWNLOAD SONG
# ==============================

@dp.callback_query(F.data.startswith("dl_"))
async def download(callback: types.CallbackQuery):
    video_id = callback.data.replace("dl_", "")
    url = f"https://youtube.com/watch?v={video_id}"
    await callback.answer("🎧 Скачиваю...")

    # удаляем сообщение с результатами поиска
    for key in list(search_cache.keys()):
        if key.startswith("msg_"):
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=search_cache[key])
            except:
                pass
            del search_cache[key]

    msg = await callback.message.answer("📥 <b>Загрузка...</b>")

    try:
        path, title, thumb = await download_and_prepare(url, video_id)

        await msg.edit_text("📤 <b>Отправляю...</b>")

        await callback.message.answer_audio(
            audio=FSInputFile(path),
            title=title,
            performer="Nexis Music by arimski",
            thumbnail=FSInputFile(thumb) if os.path.exists(thumb) else None
        )

        await msg.delete()

        # удаляем файлы с сервера
        try:
            if os.path.exists(path):
                os.remove(path)
            if os.path.exists(thumb):
                os.remove(thumb)
        except Exception as e:
            logging.error(f"Cleanup error: {e}")

    except Exception as e:
        logging.error(e)
        await msg.edit_text("❌ Ошибка загрузки")

# ==============================
# MAIN
# ==============================

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Nexis Music bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())