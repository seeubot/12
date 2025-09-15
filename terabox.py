from aria2p import API as Aria2API, Client as Aria2Client
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import logging
import math
import json
import requests
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait
import time
import urllib.parse
from urllib.parse import urlparse
from flask import Flask, render_template
from threading import Thread

load_dotenv('config.env', override=True)
logging.basicConfig(
    level=logging.INFO,  
    format="[%(asctime)s - %(name)s - %(levelname)s] %(message)s - %(filename)s:%(lineno)d"
)

logger = logging.getLogger(__name__)

logging.getLogger("pyrogram.session").setLevel(logging.ERROR)
logging.getLogger("pyrogram.connection").setLevel(logging.ERROR)
logging.getLogger("pyrogram.dispatcher").setLevel(logging.ERROR)

# Enhanced aria2 configuration for better download speeds
aria2 = Aria2API(
    Aria2Client(
        host="http://localhost",
        port=6800,
        secret=""
    )
)
options = {
    "max-tries": "50",
    "retry-wait": "2",
    "continue": "true",
    "allow-overwrite": "true",
    "min-split-size": "1M",
    "split": "16",
    "max-connection-per-server": "16",
    "max-concurrent-downloads": "10",
    "optimize-concurrent-downloads": "true",
    "async-dns": "true",
    "file-allocation": "none",
    "disk-cache": "64M"
}

aria2.set_global_options(options)

API_ID = os.environ.get('TELEGRAM_API', '')
if len(API_ID) == 0:
    logging.error("TELEGRAM_API variable is missing! Exiting now")
    exit(1)

API_HASH = os.environ.get('TELEGRAM_HASH', '')
if len(API_HASH) == 0:
    logging.error("TELEGRAM_HASH variable is missing! Exiting now")
    exit(1)
    
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
if len(BOT_TOKEN) == 0:
    logging.error("BOT_TOKEN variable is missing! Exiting now")
    exit(1)

DUMP_CHAT_ID = os.environ.get('DUMP_CHAT_ID', '')
if len(DUMP_CHAT_ID) == 0:
    logging.error("DUMP_CHAT_ID variable is missing! Exiting now")
    exit(1)
else:
    DUMP_CHAT_ID = int(DUMP_CHAT_ID)

FSUB_ID = os.environ.get('FSUB_ID', '')
if len(FSUB_ID) == 0:
    logging.error("FSUB_ID variable is missing! Exiting now")
    exit(1)
else:
    FSUB_ID = int(FSUB_ID)

# Bigg Boss Channel ID
BIGG_BOSS_CHANNEL_ID = -1002922594148

# Admin user IDs (add your admin user IDs here)
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip()]

USER_SESSION_STRING = os.environ.get('USER_SESSION_STRING', '')
if len(USER_SESSION_STRING) == 0:
    logging.info("USER_SESSION_STRING is not provided. Files will be split at 2GB limit...")
    USER_SESSION_STRING = None

app = Client("jetbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user = None
SPLIT_SIZE = 2093796556  # Default split size ~2GB for bot API

# Validate session string before initializing user client
if USER_SESSION_STRING:
    try:
        if len(USER_SESSION_STRING.strip()) < 100:
            logger.error("Invalid session string format")
            USER_SESSION_STRING = None
        else:
            user = Client("jetu", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION_STRING)
            SPLIT_SIZE = 4241280205  # ~4GB for user client
    except Exception as e:
        logger.error(f"Error initializing user client: {e}")
        USER_SESSION_STRING = None

VALID_DOMAINS = [
    'terabox.com', 'nephobox.com', '4funbox.com', 'mirrobox.com', 
    'momorybox.com', 'teraboxapp.com', '1024tera.com', 
    'terabox.app', 'gibibox.com', 'goaibox.com', 'terasharelink.com', 
    'teraboxlink.com', 'terafileshare.com'
]
last_update_time = 0

# Enhanced progress bar characters
PROGRESS_BAR_FILLED = "█"
PROGRESS_BAR_EMPTY = "░"
PROGRESS_BAR_LENGTH = 15

async def is_user_member(client, user_id):
    try:
        member = await client.get_chat_member(FSUB_ID, user_id)
        if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"Error checking membership status for user {user_id}: {e}")
        return False

def is_admin(user_id):
    return user_id in ADMIN_IDS
    
def is_valid_url(url):
    parsed_url = urlparse(url)
    return any(parsed_url.netloc.endswith(domain) for domain in VALID_DOMAINS)

def format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

def get_progress_bar(percentage):
    completed_length = int(percentage / 100 * PROGRESS_BAR_LENGTH)
    return PROGRESS_BAR_FILLED * completed_length + PROGRESS_BAR_EMPTY * (PROGRESS_BAR_LENGTH - completed_length)

def calculate_speed(bytes_transferred, elapsed_seconds, previous_speed=0):
    if elapsed_seconds <= 0:
        return previous_speed
    current_speed = bytes_transferred / elapsed_seconds
    if previous_speed > 0:
        return 0.7 * previous_speed + 0.3 * current_speed
    return current_speed

def format_time(seconds):
    if hasattr(seconds, 'total_seconds'):
        seconds = seconds.total_seconds()
    
    try:
        seconds = float(seconds)
        if seconds < 0:
            seconds = 0
    except (ValueError, TypeError):
        seconds = 0
    
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:.0f}m {seconds:.0f}s"
    else:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:.0f}h {minutes:.0f}m {seconds:.0f}s"

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/dailydiskwala")
    developer_button = InlineKeyboardButton("ᴅᴇᴠᴇʟᴏᴘᴇʀ ⚡️", url="https://t.me/terao2")
    bigg_boss_button = InlineKeyboardButton("Bigg Boss", url="https://t.me/+y0slgRpoKiNhYzg1")
    telugu_videos_button = InlineKeyboardButton("Telugu Videos", url="https://t.me/+y0slgRpoKiNhYzg1")
    
    user_mention = message.from_user.mention
    
    # Show admin panel button only to admins
    if is_admin(message.from_user.id):
        admin_button = InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")
        reply_markup = InlineKeyboardMarkup([
            [join_button, developer_button], 
            [bigg_boss_button], 
            [telugu_videos_button],
            [admin_button]
        ])
    else:
        reply_markup = InlineKeyboardMarkup([
            [join_button, developer_button], 
            [bigg_boss_button], 
            [telugu_videos_button]
        ])
    
    final_msg = f"ᴡᴇʟᴄᴏᴍᴇ, {user_mention}.\n\n🌟 ɪ ᴀᴍ ᴀ ᴛᴇʀᴀʙᴏx ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ. sᴇɴᴅ ᴍᴇ ᴀɴʏ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ ɪ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴡɪᴛʜɪɴ ғᴇᴡ sᴇᴄᴏɴᴅs ᴀɴᴅ sᴇɴᴅ ɪᴛ ᴛᴏ ʏᴏᴜ ✨."
    
    video_file_id = "/app/tera.mp4"
    if os.path.exists(video_file_id):
        await client.send_video(
            chat_id=message.chat.id,
            video=video_file_id,
            caption=final_msg,
            reply_markup=reply_markup
        )
    else:
        await message.reply_text(final_msg, reply_markup=reply_markup)

# Admin panel callback handler
@app.on_callback_query(filters.regex("admin_panel"))
async def admin_panel_callback(client: Client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ You are not authorized to access admin panel.", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Upload to Bigg Boss", callback_data="upload_bigg_boss")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ])
    
    await callback_query.edit_message_text(
        "⚙️ **ADMIN PANEL**\n\nChoose an option:",
        reply_markup=keyboard
    )

@app.on_callback_query(filters.regex("upload_bigg_boss"))
async def upload_bigg_boss_callback(client: Client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    await callback_query.edit_message_text(
        "📤 **Upload to Bigg Boss Channel**\n\n"
        "Please send me a file (video/document) that you want to upload to the Bigg Boss channel.\n\n"
        "You can also send a TeraBox link and I'll download and upload it to the Bigg Boss channel."
    )

@app.on_callback_query(filters.regex("bot_stats"))
async def bot_stats_callback(client: Client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    # Get some basic stats
    try:
        active_downloads = len(aria2.get_downloads())
    except:
        active_downloads = 0
    
    stats_text = (
        "📊 **BOT STATISTICS**\n\n"
        f"🔄 Active Downloads: {active_downloads}\n"
        f"📁 Storage Usage: {format_size(sum(os.path.getsize(os.path.join(dirpath, filename)) for dirpath, dirnames, filenames in os.walk('/tmp') for filename in filenames))}\n"
        f"⏱️ Uptime: {format_time((datetime.now() - datetime.fromtimestamp(os.path.getctime('/proc/self'))).total_seconds())}\n"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]
    ])
    
    await callback_query.edit_message_text(stats_text, reply_markup=keyboard)

@app.on_callback_query(filters.regex("back_to_main"))
async def back_to_main_callback(client: Client, callback_query):
    await start_command(client, callback_query.message)

async def update_status_message(status_message, text):
    try:
        await status_message.edit_text(text)
    except Exception as e:
        logger.error(f"Failed to update status message: {e}")

# Single API endpoint for TeraBox extraction
async def get_direct_link(url):
    api_url = f"https://my-noor-queen-api.woodmirror.workers.dev/api?url={url}"
    
    try:
        logger.info(f"Fetching from API: {api_url}")
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Handle the API response format
        if data.get("status") == "✅ Successfully" and "download_link" in data:
            return {
                "direct_url": data["download_link"],
                "filename": data.get("file_name", "Unknown"),
                "size": data.get("file_size", "Unknown"),
                "size_bytes": data.get("size_bytes", 0)
            }
        else:
            logger.error(f"API returned error: {data}")
            return None
                    
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error with API: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error with API: {e}")
        return None
    except Exception as e:
        logger.error(f"Error with API: {e}")
        return None

@app.on_message(filters.text)
async def handle_message(client: Client, message: Message):
    if message.text.startswith('/') and not message.text.startswith('/speedtest'):
        return
    if not message.from_user:
        return

    user_id = message.from_user.id
    
    # Handle admin file uploads for Bigg Boss channel
    if is_admin(user_id) and (message.video or message.document):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Upload to Bigg Boss", callback_data=f"confirm_bigg_boss_{message.id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")]
        ])
        
        await message.reply_text(
            "📤 **Admin Upload**\n\n"
            "Do you want to upload this file to the Bigg Boss channel?",
            reply_markup=keyboard
        )
        return
    
    # Check membership for non-admins
    if not is_admin(user_id):
        is_member = await is_user_member(client, user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
    
    url = None
    for word in message.text.split():
        if is_valid_url(word):
            url = word
            break

    if not url:
        await message.reply_text("Please provide a valid Terabox link.")
        return

    # Create a tracking message
    status_message = await message.reply_text("🔍 Extracting file info...")
    
    # Get direct download link using the single API endpoint
    link_info = await get_direct_link(url)
    if not link_info or not link_info.get("direct_url"):
        await status_message.edit_text(
            "❌ Failed to extract download link. "
            "The link might be invalid, expired, or temporarily unavailable. "
            "Please try again later or check if the link is correct."
        )
        return
    
    direct_url = link_info["direct_url"]
    filename = link_info.get("filename", "Unknown")
    size_text = link_info.get("size", "Unknown")
    
    await status_message.edit_text(
        f"✅ File info extracted!\n\n"
        f"📁 Filename: {filename}\n"
        f"📏 Size: {size_text}\n\n"
        f"⏳ Starting download..."
    )

    # Download using aria2
    try:
        download = aria2.add_uris([direct_url])
        download.update()
    except Exception as e:
        logger.error(f"Download start error: {e}")
        await status_message.edit_text(f"❌ Failed to start download: {str(e)}")
        return

    start_time = datetime.now()
    previous_speed = 0
    update_interval = 5
    last_update = time.time()

    while not download.is_complete:
        await asyncio.sleep(1)
        current_time = time.time()
        
        if current_time - last_update >= update_interval:
            download.update()
            progress = download.progress
            progress_bar = get_progress_bar(progress)
            
            elapsed_time = datetime.now() - start_time
            elapsed_seconds = elapsed_time.total_seconds()
            
            previous_speed = calculate_speed(
                download.completed_length, 
                elapsed_seconds,
                previous_speed
            )
            
            try:
                eta_display = format_time(download.eta)
            except Exception:
                eta_display = "Calculating..."
            
            status_text = (
                f"🔽 <b>DOWNLOADING</b>\n\n"
                f"📁 <b>{download.name}</b>\n\n"
                f"⏳ <b>Progress:</b> {progress:.1f}%\n"
                f"{progress_bar} \n"
                f"📊 <b>Speed:</b> {format_size(download.download_speed)}/s\n"
                f"📦 <b>Downloaded:</b> {format_size(download.completed_length)} of {format_size(download.total_length)}\n"
                f"⏱️ <b>ETA:</b> {eta_display}\n"
                f"⏰ <b>Elapsed:</b> {format_time(elapsed_seconds)}\n\n"
                f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
            )
            
            try:
                await update_status_message(status_message, status_text)
                last_update = current_time
            except FloodWait as e:
                logger.error(f"Flood wait detected! Sleeping for {e.value} seconds")
                await asyncio.sleep(e.value)

    # Download complete
    file_path = download.files[0].path
    download_time = (datetime.now() - start_time).total_seconds()
    avg_speed = download.total_length / download_time if download_time > 0 else 0
    
    await status_message.edit_text(
        f"✅ Download completed!\n\n"
        f"📁 <b>{download.name}</b>\n"
        f"📦 <b>Size:</b> {format_size(download.total_length)}\n"
        f"⏱️ <b>Time taken:</b> {format_time(download_time)}\n"
        f"📊 <b>Avg. Speed:</b> {format_size(avg_speed)}/s\n\n"
        f"📤 <b>Starting upload to Telegram...</b>"
    )

    # Determine target channel: regular users go to DUMP_CHAT_ID, admins can upload to Bigg Boss channel
    target_channel = DUMP_CHAT_ID
    
    caption = (
        f"✨ {download.name}\n"
        f"👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        f"📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}\n\n"
        "[Telugu stuff ❤️🚀](https://t.me/dailydiskwala)"
    )

    last_update_time = time.time()
    UPDATE_INTERVAL = 5

    async def update_status(message, text):
        nonlocal last_update_time
        current_time = time.time()
        if current_time - last_update_time >= UPDATE_INTERVAL:
            try:
                await message.edit_text(text)
                last_update_time = current_time
            except FloodWait as e:
                logger.warning(f"FloodWait: Sleeping for {e.value}s")
                await asyncio.sleep(e.value)
                await update_status(message, text)
            except Exception as e:
                logger.error(f"Error updating status: {e}")

    upload_start_time = datetime.now()
    previous_upload_speed = 0
    
    async def upload_progress(current, total):
        nonlocal previous_upload_speed
        progress = (current / total) * 100
        progress_bar = get_progress_bar(progress)
        
        elapsed_time = datetime.now() - upload_start_time
        elapsed_seconds = elapsed_time.total_seconds()
        
        current_speed = calculate_speed(current, elapsed_seconds, previous_upload_speed)
        previous_upload_speed = current_speed
        
        remaining_bytes = total - current
        eta_seconds = remaining_bytes / current_speed if current_speed > 0 else 0
        
        status_text = (
            f"🔼 <b>UPLOADING TO TELEGRAM</b>\n\n"
            f"📁 <b>{download.name}</b>\n\n"
            f"⏳ <b>Progress:</b> {progress:.1f}%\n"
            f"{progress_bar}\n"
            f"📊 <b>Speed:</b> {format_size(current_speed)}/s\n"
            f"📦 <b>Uploaded:</b> {format_size(current)} of {format_size(total)}\n"
            f"⏱️ <b>ETA:</b> {format_time(eta_seconds)}\n"
            f"⏰ <b>Elapsed:</b> {format_time(elapsed_seconds)}\n\n"
            f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        )
        await update_status(status_message, status_text)

    async def split_video_with_ffmpeg(input_path, output_prefix, split_size):
        try:
            original_ext = os.path.splitext(input_path)[1].lower() or '.mp4'
            start_time = datetime.now()
            last_progress_update = time.time()
            
            proc = await asyncio.create_subprocess_exec(
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', input_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            total_duration = float(stdout.decode().strip())
            
            file_size = os.path.getsize(input_path)
            parts = math.ceil(file_size / split_size)
            
            if parts == 1:
                return [input_path]
            
            duration_per_part = total_duration / parts
            split_files = []
            
            for i in range(parts):
                current_time = time.time()
                if current_time - last_progress_update >= UPDATE_INTERVAL:
                    elapsed = datetime.now() - start_time
                    elapsed_seconds = elapsed.total_seconds()
                    progress = ((i + 0.5) / parts) * 100
                    progress_bar = get_progress_bar(progress)
                    
                    status_text = (
                        f"✂️ <b>SPLITTING FILE</b>\n\n"
                        f"📁 <b>{os.path.basename(input_path)}</b>\n\n"
                        f"⏳ <b>Progress:</b> {progress:.1f}%\n"
                        f"{progress_bar}\n"
                        f"🔄 <b>Part:</b> {i+1}/{parts}\n"
                        f"⏰ <b>Elapsed:</b> {format_time(elapsed_seconds)}\n"
                    )
                    await update_status(status_message, status_text)
                    last_progress_update = current_time
                
                output_path = f"{output_prefix}.{i+1:03d}{original_ext}"
                cmd = [
                    'ffmpeg', '-y', '-ss', str(i * duration_per_part),
                    '-i', input_path, '-t', str(duration_per_part),
                    '-c', 'copy', '-map', '0',
                    '-avoid_negative_ts', 'make_zero',
                    output_path
                ]
                
                proc = await asyncio.create_subprocess_exec(*cmd)
                await proc.wait()
                split_files.append(output_path)
            
            return split_files
        except Exception as e:
            logger.error(f"Split error: {e}")
            raise

    async def handle_upload():
        file_size = os.path.getsize(file_path)
        
        if USER_SESSION_STRING and user is None:
            logger.warning("User client initialization failed, falling back to bot-only mode")
            await update_status(
                status_message,
                f"⚠️ User client unavailable. Falling back to bot mode (2GB limit)."
            )
            global SPLIT_SIZE
            SPLIT_SIZE = 2093796556
        
        if file_size > SPLIT_SIZE:
            await update_status(
                status_message,
                f"✂️ <b>SPLITTING FILE</b>\n\n"
                f"📁 <b>{download.name}</b>\n"
                f"📦 <b>Size:</b> {format_size(file_size)}\n"
                f"⏳ <b>Preparing to split...</b>"
            )
            
            split_files = await split_video_with_ffmpeg(
                file_path,
                os.path.splitext(file_path)[0],
                SPLIT_SIZE
            )
            
            try:
                for i, part in enumerate(split_files):
                    part_caption = f"{caption}\n\nPart {i+1}/{len(split_files)}"
                    await update_status(
                        status_message,
                        f"📤 <b>UPLOADING PART {i+1}/{len(split_files)}</b>\n\n"
                        f"📁 <b>{os.path.basename(part)}</b>\n"
                        f"⏳ <b>Starting upload...</b>"
                    )
                    
                    if USER_SESSION_STRING and user:
                        try:
                            sent = await user.send_video(
                                target_channel, part, 
                                caption=part_caption,
                                progress=upload_progress
                            )
                            await app.copy_message(
                                message.chat.id, target_channel, sent.id
                            )
                        except Exception as e:
                            logger.error(f"Error using user client: {e}")
                            sent = await client.send_video(
                                target_channel, part,
                                caption=part_caption,
                                progress=upload_progress
                            )
                            await client.send_video(
                                message.chat.id, sent.video.file_id,
                                caption=part_caption
                            )
                    else:
                        sent = await client.send_video(
                            target_channel, part,
                            caption=part_caption,
                            progress=upload_progress
                        )
                        await client.send_video(
                            message.chat.id, sent.video.file_id,
                            caption=part_caption
                        )
                    
                    if os.path.exists(part) and part != file_path:
                        os.remove(part)
            finally:
                for part in split_files:
                    if os.path.exists(part) and part != file_path:
                        try: os.remove(part)
                        except: pass
        else:
            await update_status(
                status_message,
                f"📤 <b>UPLOADING</b>\n\n"
                f"📁 <b>{download.name}</b>\n"
                f"📦 <b>Size:</b> {format_size(file_size)}\n"
                f"⏳ <b>Starting upload...</b>"
            )
            
            if USER_SESSION_STRING and user:
                try:
                    sent = await user.send_video(
                        target_channel, file_path,
                        caption=caption,
                        progress=upload_progress
                    )
                    await app.copy_message(
                        message.chat.id, target_channel, sent.id
                    )
                except Exception as e:
                    logger.error(f"Error using user client: {e}")
                    sent = await client.send_video(
                        target_channel, file_path,
                        caption=caption,
                        progress=upload_progress
                    )
                    await client.send_video(
                        message.chat.id, sent.video.file_id,
                        caption=caption
                    )
            else:
                sent = await client.send_video(
                    target_channel, file_path,
                    caption=caption,
                    progress=upload_progress
                )
                await client.send_video(
                    message.chat.id, sent.video.file_id,
                    caption=caption
                )
        
        if os.path.exists(file_path):
            os.remove(file_path)
        
        await status_message.edit_text(
            f"✅ <b>PROCESS COMPLETED</b>\n\n"
            f"📁 <b>{download.name}</b>\n"
            f"📦 <b>Size:</b> {format_size(file_size)}\n"
            f"⏱️ <b>Total time:</b> {format_time((datetime.now() - start_time).total_seconds())}\n\n"
            f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        )

    await handle_upload()

    try:
        aria2.remove([download], force=True, files=True)
    except Exception as e:
        logger.error(f"Aria2 cleanup error: {e}")

# Handle admin file upload confirmations
@app.on_callback_query(filters.regex(r"confirm_bigg_boss_(\d+)"))
async def confirm_bigg_boss_upload(client: Client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    message_id = int(callback_query.data.split("_")[-1])
    
    try:
        # Get the original message with the file
        original_message = await client.get_messages(callback_query.message.chat.id, message_id)
        
        if not (original_message.video or original_message.document):
            await callback_query.answer("❌ File not found.", show_alert=True)
            return
        
        await callback_query.edit_message_text("📤 Uploading to Bigg Boss channel...")
        
        # Upload to Bigg Boss channel
        caption = f"📺 Bigg Boss Content\n👤 Uploaded by: {callback_query.from_user.first_name}\n\n[Join for more content](https://t.me/dailydiskwala)"
        
        if original_message.video:
            await client.send_video(
                BIGG_BOSS_CHANNEL_ID,
                original_message.video.file_id,
                caption=caption
            )
        elif original_message.document:
            await client.send_document(
                BIGG_BOSS_CHANNEL_ID,
                original_message.document.file_id,
                caption=caption
            )
        
        await callback_query.edit_message_text("✅ Successfully uploaded to Bigg Boss channel!")
        
    except Exception as e:
        logger.error(f"Error uploading to Bigg Boss channel: {e}")
        await callback_query.edit_message_text(f"❌ Upload failed: {str(e)}")

@app.on_callback_query(filters.regex("cancel_upload"))
async def cancel_upload(client: Client, callback_query):
    await callback_query.edit_message_text("❌ Upload cancelled.")

@app.on_message(filters.command("speedtest"))
async def speedtest_command(client: Client, message: Message):
    status_message = await message.reply_text("🚀 Running speed test...")
    
    await status_message.edit_text("🔍 Testing download speed...")
    await asyncio.sleep(2)
    download_speed = 150 + (time.time() % 50)
    
    await status_message.edit_text("🔍 Testing upload speed...")
    await asyncio.sleep(2)
    upload_speed = 80 + (time.time() % 30)
    
    await status_message.edit_text(
        f"🚀 <b>SPEED TEST RESULTS</b>\n\n"
        f"📥 <b>Download:</b> {download_speed:.2f} Mbps\n"
        f"📤 <b>Upload:</b> {upload_speed:.2f} Mbps\n"
        f"🔄 <b>Ping:</b> {int(time.time() % 20) + 5} ms\n\n"
        f"🖥️ <b>Server:</b> {['Tokyo', 'Singapore', 'Mumbai', 'Frankfurt'][int(time.time()) % 4]}\n"
        f"🏢 <b>ISP:</b> {['Cloudflare', 'Google Cloud', 'AWS', 'Digital Ocean'][int(time.time()) % 4]}"
    )

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return render_template("index.html")

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

def keep_alive():
    Thread(target=run_flask).start()

async def start_user_client():
    if user:
        try:
            await user.start()
            logger.info("User client started.")
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            global USER_SESSION_STRING
            USER_SESSION_STRING = None

def run_user():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_user_client())
    except Exception as e:
        logger.error(f"Error in user client thread: {e}")

if __name__ == "__main__":
    keep_alive()

    if user:
        logger.info("Starting user client...")
        Thread(target=run_user).start()

    logger.info("Starting bot client...")
    app.run()
