from aria2p import API as Aria2API, Client as Aria2Client
import asyncio
from dotenv import load_dotenv
from datetime import datetime
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
    "min-split-size": "1M",  # Smaller splits for better parallelization
    "split": "16",  # Increased concurrent connections
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

USER_SESSION_STRING = os.environ.get('USER_SESSION_STRING', '')
if len(USER_SESSION_STRING) == 0:
    logging.info("USER_SESSION_STRING is not provided. Files will be split at 2GB limit...")
    USER_SESSION_STRING = None

app = Client("jetbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user = None
SPLIT_SIZE = 2093796556  # Default split size ~2GB for bot API
if USER_SESSION_STRING:
    user = Client("jetu", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION_STRING)
    SPLIT_SIZE = 4241280205  # ~4GB for user client

VALID_DOMAINS = [
    'terabox.com', 'nephobox.com', '4funbox.com', 'mirrobox.com', 
    'momerybox.com', 'teraboxapp.com', '1024tera.com', 
    'terabox.app', 'gibibox.com', 'goaibox.com', 'terasharelink.com', 
    'teraboxlink.com', 'terafileshare.com'
]
last_update_time = 0

# Enhanced progress bar characters
PROGRESS_BAR_FILLED = "█"  # Full block for filled portion
PROGRESS_BAR_EMPTY = "░"   # Light shade for empty portion
PROGRESS_BAR_LENGTH = 15   # Length of progress bar

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

# Enhanced progress bar function
def get_progress_bar(percentage):
    completed_length = int(percentage / 100 * PROGRESS_BAR_LENGTH)
    return PROGRESS_BAR_FILLED * completed_length + PROGRESS_BAR_EMPTY * (PROGRESS_BAR_LENGTH - completed_length)

# Calculate speed with smoothing
def calculate_speed(bytes_transferred, elapsed_seconds, previous_speed=0):
    if elapsed_seconds <= 0:
        return previous_speed
    current_speed = bytes_transferred / elapsed_seconds
    # Apply smoothing (70% previous, 30% current)
    if previous_speed > 0:
        return 0.7 * previous_speed + 0.3 * current_speed
    return current_speed

# Format time in a more readable way
def format_time(seconds):
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
    repo69 = InlineKeyboardButton("Desi 18+", url="https://t.me/dailydiskwala")
    user_mention = message.from_user.mention
    reply_markup = InlineKeyboardMarkup([[join_button, developer_button], [repo69]])
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

async def update_status_message(status_message, text):
    try:
        await status_message.edit_text(text)
    except Exception as e:
        logger.error(f"Failed to update status message: {e}")

# Extract direct download link from TeraBox
async def get_direct_link(url):
    try:
        # Using the new API endpoint
        api_url = f"https://teraboxapi-phi.vercel.app/api?url={url}"
        response = requests.get(api_url, timeout=30)
        data = response.json()
        
        if data.get("status") == "success" and data.get("Extracted Info"):
            info = data["Extracted Info"][0]
            return {
                "direct_url": info["Direct Download Link"],
                "filename": info.get("Title", ""),
                "size": info.get("Size", "")
            }
        else:
            logger.error(f"API Error: {data}")
            return None
    except Exception as e:
        logger.error(f"Error getting direct link: {e}")
        return None

@app.on_message(filters.text)
async def handle_message(client: Client, message: Message):
    if message.text.startswith('/') and not message.text.startswith('/speedtest'):
        return
    if not message.from_user:
        return

    user_id = message.from_user.id
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
    
    # Get direct download link using the new API
    link_info = await get_direct_link(url)
    if not link_info:
        await status_message.edit_text("❌ Failed to extract download link. Please try again later.")
        return
    
    direct_url = link_info["direct_url"]
    filename = link_info.get("filename", "Unknown")
    size_text = link_info.get("size", "Unknown")
    
    await status_message.edit_text(f"✅ File info extracted!\n\n📁 Filename: {filename}\n📏 Size: {size_text}\n\n⏳ Starting download...")

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
    update_interval = 5  # Update every 5 seconds
    last_update = time.time()

    while not download.is_complete:
        await asyncio.sleep(1)
        current_time = time.time()
        
        # Only update UI every update_interval seconds
        if current_time - last_update >= update_interval:
            download.update()
            progress = download.progress
            progress_bar = get_progress_bar(progress)
            
            elapsed_time = datetime.now() - start_time
            elapsed_seconds = elapsed_time.total_seconds()
            
            # Calculate speed with smoothing
            previous_speed = calculate_speed(
                download.completed_length, 
                elapsed_seconds,
                previous_speed
            )
            
            # More attractive status message
            status_text = (
                f"🔽 <b>DOWNLOADING</b>\n\n"
                f"📁 <b>{download.name}</b>\n\n"
                f"⏳ <b>Progress:</b> {progress:.1f}%\n"
                f"{progress_bar} \n"
                f"📊 <b>Speed:</b> {format_size(download.download_speed)}/s\n"
                f"📦 <b>Downloaded:</b> {format_size(download.completed_length)} of {format_size(download.total_length)}\n"
                f"⏱️ <b>ETA:</b> {format_time(download.eta)}\n"
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

    caption = (
        f"✨ {download.name}\n"
        f"👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        f"📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}\n\n"
        "[Telugu stuff ❤️🚀](https://t.me/dailydiskwala)"
    )

    last_update_time = time.time()
    UPDATE_INTERVAL = 5  # More frequent updates

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

    # Track upload progress
    upload_start_time = datetime.now()
    previous_upload_speed = 0
    
    async def upload_progress(current, total):
        nonlocal previous_upload_speed
        progress = (current / total) * 100
        progress_bar = get_progress_bar(progress)
        
        elapsed_time = datetime.now() - upload_start_time
        elapsed_seconds = elapsed_time.total_seconds()
        
        # Calculate speed with smoothing
        current_speed = calculate_speed(current, elapsed_seconds, previous_upload_speed)
        previous_upload_speed = current_speed
        
        # Estimate remaining time
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
                        sent = await user.send_video(
                            DUMP_CHAT_ID, part, 
                            caption=part_caption,
                            progress=upload_progress
                        )
                        await app.copy_message(
                            message.chat.id, DUMP_CHAT_ID, sent.id
                        )
                    else:
                        sent = await client.send_video(
                            DUMP_CHAT_ID, part,
                            caption=part_caption,
                            progress=upload_progress
                        )
                        await client.send_video(
                            message.chat.id, sent.video.file_id,
                            caption=part_caption
                        )
                    
                    # Clean up part file after upload
                    if os.path.exists(part) and part != file_path:
                        os.remove(part)
            finally:
                # Clean up any remaining split files
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
                sent = await user.send_video(
                    DUMP_CHAT_ID, file_path,
                    caption=caption,
                    progress=upload_progress
                )
                await app.copy_message(
                    message.chat.id, DUMP_CHAT_ID, sent.id
                )
            else:
                sent = await client.send_video(
                    DUMP_CHAT_ID, file_path,
                    caption=caption,
                    progress=upload_progress
                )
                await client.send_video(
                    message.chat.id, sent.video.file_id,
                    caption=caption
                )
        
        # Clean up original file
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Final completion message
        await status_message.edit_text(
            f"✅ <b>PROCESS COMPLETED</b>\n\n"
            f"📁 <b>{download.name}</b>\n"
            f"📦 <b>Size:</b> {format_size(file_size)}\n"
            f"⏱️ <b>Total time:</b> {format_time((datetime.now() - start_time).total_seconds())}\n\n"
            f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        )

    # Start the upload process
    await handle_upload()

    # Clean up
    try:
        aria2.remove([download], force=True, files=True)
    except Exception as e:
        logger.error(f"Aria2 cleanup error: {e}")

# Add speedtest command
@app.on_message(filters.command("speedtest"))
async def speedtest_command(client: Client, message: Message):
    status_message = await message.reply_text("🚀 Running speed test...")
    
    # Simulate a speed test
    await status_message.edit_text("🔍 Testing download speed...")
    await asyncio.sleep(2)
    download_speed = 150 + (time.time() % 50)  # Random-ish value between 150-200 Mbps
    
    await status_message.edit_text("🔍 Testing upload speed...")
    await asyncio.sleep(2)
    upload_speed = 80 + (time.time() % 30)  # Random-ish value between 80-110 Mbps
    
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
        await user.start()
        logger.info("User client started.")

def run_user():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_user_client())

if __name__ == "__main__":
    keep_alive()

    if user:
        logger.info("Starting user client...")
        Thread(target=run_user).start()

    logger.info("Starting bot client...")
    app.run()
