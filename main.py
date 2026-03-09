import asyncio
import os
import logging
import yt_dlp
import subprocess
from PIL import Image
from mutagen.mp4 import MP4, MP4Cover
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Загрузка настроек
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(BASE_DIR, 'cookies.txt')
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
THUMB_PATH = os.path.join(BASE_DIR, "nx.jpeg")

logging.basicConfig(level=logging.INFO)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

search_cache = {}

# Оптимизированные настройки скачивания
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'cookiefile': COOKIES_PATH, 
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'extract_flat': False,
    'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s.%(ext)s'),
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '192',
    }],
}

async def download_and_prepare(url):
    loop = asyncio.get_event_loop()
    
    def process():
        opt_thumb = os.path.join(DOWNLOAD_DIR, "opt_thumb.jpg")
        
        # Обработка обложки
        if os.path.exists(THUMB_PATH):
            with Image.open(THUMB_PATH) as img:
                img = img.convert("RGB")
                img = img.resize((600, 600), Image.LANCZOS)
                img.save(opt_thumb, "JPEG", quality=100)

        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=True)
            # После post-processing расширение будет .m4a
            final_file = ydl.prepare_filename(info).rsplit('.', 1)[0] + ".m4a"
            title = info.get('title', 'Music')
            
            # Накладываем метаданные и обложку
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

def get_pagination_keyboard(items, page: int, query_id: str):
    items_per_page = 5
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_items = items[start_idx:end_idx]
    
    builder = InlineKeyboardBuilder()
    for item in current_items:
        builder.row(types.InlineKeyboardButton(
            text=f"🎵 {item['title'][:40]}...", 
            callback_data=f"dl_{item['id']}")
        )
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{query_id}_{page-1}"))
    
    total_pages = (len(items) - 1) // items_per_page + 1
    nav_buttons.append(types.InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    
    if end_idx < len(items):
        nav_buttons.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page_{query_id}_{page+1}"))
    
    builder.row(*nav_buttons)
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🚀 <b>Nexis Music</b>\nПришли название песни, и я найду её!")

@dp.message(F.text & ~F.text.startswith("/"))
async def search_song(message: types.Message):
    status_msg = await message.answer("🔎 <b>Ищу песни...</b>")
    try:
        with yt_dlp.YoutubeDL({'extract_flat': True, 'quiet': True}) as ydl:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch20:{message.text}", download=False))
            
            if not info or not info.get('entries'):
                return await status_msg.edit_text("❌ <b>Ничего не найдено.</b>")

            query_id = str(message.message_id)
            search_cache[query_id] = info['entries']
            
            await status_msg.delete()
            await message.answer(
                f"✨ <b>Результаты для: {message.text}</b>", 
                reply_markup=get_pagination_keyboard(info['entries'], 0, query_id)
            )
    except Exception as e:
        await status_msg.edit_text("⚠️ <b>Ошибка поиска.</b>")

@dp.callback_query(F.data.startswith("page_"))
async def handle_pagination(callback: types.CallbackQuery):
    _, query_id, page = callback.data.split("_")
    page = int(page)
    if query_id not in search_cache:
        return await callback.answer("Результаты устарели.", show_alert=True)
    
    await callback.message.edit_reply_markup(
        reply_markup=get_pagination_keyboard(search_cache[query_id], page, query_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("dl_"))
async def handle_download(callback: types.CallbackQuery):
    video_id = callback.data.replace("dl_", "")
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Безопасное удаление сообщения
    try:
        await callback.message.delete()
    except:
        pass

    await callback.answer("Качаю... ✨")
    loading_msg = await callback.message.answer("📥 <b>Обработка аудио...</b>")
    
    try:
        path, title, opt_thumb = await download_and_prepare(url)
        await loading_msg.edit_text("📤 <b>Отправка файла...</b>")
        
        await callback.message.answer_audio(
            audio=FSInputFile(path),
            title=title,
            performer="Nexis Music",
            thumbnail=FSInputFile(opt_thumb) if os.path.exists(opt_thumb) else None,
        )
        
        # Чистка файлов
        if os.path.exists(path): os.remove(path)
        if os.path.exists(opt_thumb): os.remove(opt_thumb)
        await loading_msg.delete()
        
    except Exception as e:
        logging.error(f"Download error: {e}")
        await callback.message.answer(f"❌ <b>Ошибка:</b> {str(e)[:100]}")

async def main():
    # Сброс вебхуков и старых обновлений
    await bot.delete_webhook(drop_pending_updates=True)
    print("--- БОТ NEXIS MUSIC ЗАПУЩЕН ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())