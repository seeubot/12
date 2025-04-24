from aria2p import API as Aria2API, Client as Aria2Client
import asyncio
from dotenv import load_dotenv
from datetime import datetime
import os
import logging
import math
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait
import time
import urllib.parse
from urllib.parse import urlparse
import requests
import json
from flask import Flask, render_template
from threading import Thread
import aiohttp
import aiofiles
import concurrent.futures
from requests_handler import register_request_handlers  # Import request handler

# Load environment variables
load_dotenv('config.env', override=True)
logging.basicConfig(
    level=logging.INFO,  
    format="[%(asctime)s - %(name)s - %(levelname)s] %(message)s - %(filename)s:%(lineno)d"
)

logger = logging.getLogger(__name__)

# Reduce unnecessary logging
logging.getLogger("pyrogram.session").setLevel(logging.ERROR)
logging.getLogger("pyrogram.connection").setLevel(logging.ERROR)
logging.getLogger("pyrogram.dispatcher").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

# Configure aria2 with optimized settings
aria2 = Aria2API(
    Aria2Client(
        host="http://localhost",
        port=6800,
        secret=""
    )
)
options = {
    "max-tries": "50",
    "retry-wait": "3",
    "continue": "true",
    "allow-overwrite": "true",
    "min-split-size": "1M",  # Reduced to enable more connections
    "split": "16",  # Increased for parallel downloads
    "max-connection-per-server": "16",  # Increased for better speed
    "max-concurrent-downloads": "10",
    "file-allocation": "none",  # Speeds up initial file creation
    "optimize-concurrent-downloads": "true"
}

aria2.set_global_options(options)

# Load environment variables
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

REQUEST_CHANNEL_ID = os.environ.get('REQUEST_CHANNEL_ID', '')
if len(REQUEST_CHANNEL_ID) == 0:
    logging.error("REQUEST_CHANNEL_ID variable is missing! Using default channel...")
    REQUEST_CHANNEL_ID = "@requestsids"
else:
    REQUEST_CHANNEL_ID = int(REQUEST_CHANNEL_ID)

ADMIN_IDS = os.environ.get('ADMIN_IDS', '').split(',')
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS if admin_id.strip()]
if not ADMIN_IDS:
    logging.warning("ADMIN_IDS variable is missing or invalid! Admin features will be limited.")

USER_SESSION_STRING = os.environ.get('USER_SESSION_STRING', '')
if len(USER_SESSION_STRING) == 0:
    logging.info("USER_SESSION_STRING variable is missing! Bot will split Files in 2Gb...")
    USER_SESSION_STRING = None

app = Client("jetbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Register request handlers
app = register_request_handlers(app, FSUB_ID)

user = None
SPLIT_SIZE = 2093796556
if USER_SESSION_STRING:
    user = Client("jetu", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION_STRING)
    SPLIT_SIZE = 4241280205

VALID_DOMAINS = [
    'terabox.com', 'nephobox.com', '4funbox.com', 'mirrobox.com', 
    'momerybox.com', 'teraboxapp.com', '1024tera.com', 
    'terabox.app', 'gibibox.com', 'goaibox.com', 'terasharelink.com', 
    'teraboxlink.com', 'terafileshare.com'
]
last_update_time = 0

# New API endpoint
TERABOX_API = "https://teraboxapi-phi.vercel.app/api?url="

# Alternative API endpoints for load balancing
TERABOX_APIs = [
    "https://teraboxapi-phi.vercel.app/api?url=",
    "https://terabox-dl-api.vercel.app/api?url=",
    # Add more API endpoints as needed
]

# Connection pool for aiohttp
session = None

async def setup_aiohttp_session():
    global session
    if session is None or session.closed:
        connector = aiohttp.TCPConnector(limit=20, force_close=True, enable_cleanup_closed=True)
        timeout = aiohttp.ClientTimeout(total=60)
        session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return session

async def close_aiohttp_session():
    global session
    if session and not session.closed:
        await session.close()

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
    if isinstance(size, str):
        try:
            # Convert string like "66.78 MB" to bytes
            parts = size.split()
            if len(parts) != 2:
                return size  # Return original if format isn't recognized
            
            value = float(parts[0])
            unit = parts[1].upper()
            
            if unit == "B":
                return value
            elif unit == "KB":
                return value * 1024
            elif unit == "MB":
                return value * 1024 * 1024
            elif unit == "GB":
                return value * 1024 * 1024 * 1024
            else:
                return size  # Return original if unit isn't recognized
        except:
            return size  # Return original on any error
    
    # If input is a number, format it
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

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
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
    request_button = InlineKeyboardButton("ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏ 🎬", callback_data="video_request")
    developer_button = InlineKeyboardButton("ᴅᴇᴠᴇʟᴏᴘᴇʀ ⚡️", url="https://t.me/rtx5069")
    repo69 = InlineKeyboardButton("ʀᴇᴘᴏ 🌐", url="https://github.com/Hrishi2861/Terabox-Downloader-Bot")
    user_mention = message.from_user.mention
    reply_markup = InlineKeyboardMarkup([[join_button, developer_button], [request_button], [repo69]])
    final_msg = f"ᴡᴇʟᴄᴏᴍᴇ, {user_mention}.\n\n🌟 ɪ ᴀᴍ ᴀ ᴛᴇʀᴀʙᴏx ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ. sᴇɴᴅ ᴍᴇ ᴀɴʏ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ ɪ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴡɪᴛʜɪɴ ғᴇᴡ sᴇᴄᴏɴᴅs ᴀɴᴅ sᴇɴᴅ ɪᴛ ᴛᴏ ʏᴏᴜ ✨.\n\n🎬 ʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏs ʙʏ ᴄʟɪᴄᴋɪɴɢ ᴛʜᴇ ʀᴇǫᴜᴇsᴛ ʙᴜᴛᴛᴏɴ ᴏʀ ᴜsɪɴɢ /request ᴄᴏᴍᴍᴀɴᴅ."
    video_file_id = "/app/Jet-Mirror.mp4"
    if os.path.exists(video_file_id):
        await client.send_video(
            chat_id=message.chat.id,
            video=video_file_id,
            caption=final_msg,
            reply_markup=reply_markup
            )
    else:
        await message.reply_text(final_msg, reply_markup=reply_markup)

@app.on_callback_query(filters.regex("video_request"))
async def video_request_callback(client, callback_query):
    await callback_query.answer()
    await client.send_message(
        chat_id=callback_query.message.chat.id,
        text="📽️ **Send a screenshot or image of the video you want to request.**\n\n"
        "Please include the following details in the caption:\n"
        "1. Video name/title\n"
        "2. Source (if any)\n"
        "3. Any additional information\n\n"
        "Example: `Avengers Endgame (2019) | HD Quality | Marvel`"
    )

async def get_direct_link(url, api_index=0):
    """Get direct download link using multiple APIs for load balancing"""
    try:
        if api_index >= len(TERABOX_APIs):
            logger.error("All APIs failed, giving up")
            return None, None, None

        current_api = TERABOX_APIs[api_index]
        encoded_url = urllib.parse.quote(url)
        api_url = f"{current_api}{encoded_url}"
        
        session = await setup_aiohttp_session()
        async with session.get(api_url, timeout=30) as response:
            if response.status != 200:
                logger.warning(f"API {api_index} failed with status {response.status}, trying next API")
                return await get_direct_link(url, api_index + 1)
            
            data = await response.json()
            
            if data.get("status") != "success":
                logger.warning(f"API {api_index} returned error: {data.get('message', 'Unknown error')}")
                return await get_direct_link(url, api_index + 1)
                
            file_name = data.get("file_name", "unknown_file")
            file_size = data.get("size", "Unknown size")
            download_url = data.get("dlink", "")
            
            if not download_url:
                logger.warning(f"API {api_index} returned no download URL")
                return await get_direct_link(url, api_index + 1)
                
            return file_name, file_size, download_url
            
    except asyncio.TimeoutError:
        logger.warning(f"API {api_index} timeout, trying next API")
        return await get_direct_link(url, api_index + 1)
    except Exception as e:
        logger.error(f"Error getting direct link from API {api_index}: {e}")
        return await get_direct_link(url, api_index + 1)

async def download_file(url, file_path, progress_callback=None):
    """Download file with optimized chunking and retry logic"""
    try:
        start_time = time.time()
        session = await setup_aiohttp_session()
        
        # Use a large chunk size for better throughput
        chunk_size = 1024 * 1024  # 1MB chunks
        
        # Set a timeout for the initial connection
        timeout = aiohttp.ClientTimeout(total=60, connect=20)
        
        # Headers to optimize connection
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }
        
        # Retry logic for robust downloads
        max_retries = 5
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                async with session.get(url, timeout=timeout, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"HTTP error: {response.status}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return False
                    
                    # Get file size for progress tracking
                    total_size = int(response.headers.get('Content-Length', 0))
                    downloaded_size = 0
                    
                    # Create directory if it doesn't exist
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    
                    # Use aiofiles for non-blocking file operations
                    async with aiofiles.open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            await f.write(chunk)
                            downloaded_size += len(chunk)
                            
                            # Calculate speed and ETA
                            elapsed = time.time() - start_time
                            speed = downloaded_size / elapsed if elapsed > 0 else 0
                            eta = (total_size - downloaded_size) / speed if speed > 0 else 0
                            
                            # Call progress callback if provided
                            if progress_callback:
                                await progress_callback(
                                    downloaded_size, 
                                    total_size,
                                    speed,
                                    eta
                                )
                    
                    logger.info(f"Download completed: {file_path}")
                    return True
                    
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Download attempt {attempt+1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Download failed after {max_retries} attempts")
                    return False
                    
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False
        
async def progress_callback(current, total, speed, eta, message=None, start_time=None):
    """Display download/upload progress"""
    if not message or not start_time:
        return
    
    now = time.time()
    elapsed_time = now - start_time
    
    # Update progress every 3 seconds to avoid flood
    global last_update_time
    if now - last_update_time < 3:
        return
    last_update_time = now

    try:
        percentage = current * 100 / total if total else 0
        progress_bar = generate_progress_bar(percentage)
        
        speed_str = format_size(speed) + "/s"
        eta_str = format_time(eta)
        current_str = format_size(current)
        total_str = format_size(total)
        
        text = f"**⬇️ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ**\n\n"
        text += f"{progress_bar}\n\n"
        text += f"**» ᴘʀᴏɢʀᴇss**: `{percentage:.1f}%`\n"
        text += f"**» ᴘʀᴏᴄᴇssᴇᴅ**: `{current_str} / {total_str}`\n"
        text += f"**» sᴘᴇᴇᴅ**: `{speed_str}`\n"
        text += f"**» ᴇᴛᴀ**: `{eta_str}`\n"
        
        await message.edit_text(text)
        
    except Exception as e:
        pass  # Ignore errors in progress update

def generate_progress_bar(percentage):
    """Generate a beautiful progress bar"""
    filled_blocks = int(percentage / 5)  # 20 blocks for 100%
    empty_blocks = 20 - filled_blocks
    
    return "■" * filled_blocks + "□" * empty_blocks

async def upload_to_telegram(client, chat_id, file_path, caption=None, progress=None, file_name=None):
    """Upload file to Telegram with optimized settings"""
    try:
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None
            
        file_size = os.path.getsize(file_path)
        logger.info(f"Starting upload of {file_path} ({format_size(file_size)})")
        
        # Use custom file name if provided
        if not file_name:
            file_name = os.path.basename(file_path)
            
        # For large files, use the user client if available
        if file_size > SPLIT_SIZE and user:
            return await upload_large_file(file_path, chat_id, caption, progress, file_name)
        
        # Set appropriate upload method based on file type
        if file_path.lower().endswith(('.mkv', '.mp4', '.avi', '.mov', '.flv', '.webm')):
            return await client.send_video(
                chat_id=chat_id,
                video=file_path,
                caption=caption,
                progress=progress,
                file_name=file_name,
                supports_streaming=True
            )
        elif file_path.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.ogg')):
            return await client.send_audio(
                chat_id=chat_id,
                audio=file_path,
                caption=caption,
                progress=progress,
                file_name=file_name
            )
        elif file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            return await client.send_photo(
                chat_id=chat_id,
                photo=file_path,
                caption=caption,
                progress=progress,
                file_name=file_name
            )
        else:
            return await client.send_document(
                chat_id=chat_id,
                document=file_path,
                caption=caption,
                progress=progress,
                file_name=file_name,
                force_document=True
            )
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None

async def upload_large_file(file_path, chat_id, caption=None, progress=None, file_name=None):
    """Handle large file uploads with splitting"""
    try:
        if not user:
            logger.error("User session not available for large file upload")
            return None
            
        # TODO: Implement file splitting for large uploads
        # For now, attempt to upload with user session
        if file_path.lower().endswith(('.mkv', '.mp4', '.avi', '.mov', '.flv', '.webm')):
            return await user.send_video(
                chat_id=chat_id,
                video=file_path,
                caption=caption,
                progress=progress,
                file_name=file_name,
                supports_streaming=True
            )
        else:
            return await user.send_document(
                chat_id=chat_id,
                document=file_path,
                caption=caption,
                progress=progress,
                file_name=file_name,
                force_document=True
            )
    except Exception as e:
        logger.error(f"Large file upload error: {e}")
        return None

async def process_url(client, message, url):
    """Process a Terabox URL from start to finish"""
    try:
        user_id = message.from_user.id
        
        # Check if user is subscribed
        is_member = await is_user_member(client, user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Send initial processing message
        status_msg = await message.reply_text("🔍 **ᴘʀᴏᴄᴇssɪɴɢ ʏᴏᴜʀ ʟɪɴᴋ...**")
        
        # Get direct download link
        file_name, file_size, download_url = await get_direct_link(url)
        
        if not download_url:
            await status_msg.edit_text("❌ **ғᴀɪʟᴇᴅ ᴛᴏ ᴘʀᴏᴄᴇss ʟɪɴᴋ.** ᴘʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ɪғ ᴛʜᴇ ʟɪɴᴋ ɪs ᴠᴀʟɪᴅ ᴏʀ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.")
            return
            
        # Sanitize file name
        clean_filename = file_name.replace(" ", "_").replace(",", "").replace("(", "").replace(")", "")
        download_path = f"downloads/{user_id}/{clean_filename}"
        
        # Create download directory
        os.makedirs(os.path.dirname(download_path), exist_ok=True)
        
        # Update status message
        await status_msg.edit_text(
            f"🔗 **ʟɪɴᴋ ғᴏᴜɴᴅ!**\n\n"
            f"📁 **ғɪʟᴇ ɴᴀᴍᴇ:** `{file_name}`\n"
            f"💾 **ғɪʟᴇ sɪᴢᴇ:** `{file_size}`\n\n"
            f"⬇️ **sᴛᴀʀᴛɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ...**"
        )
        
        # Start download
        start_time = time.time()
        
        async def progress_for_pyrogram(current, total, message, start):
            await progress_callback(current, total, current/(time.time()-start) if time.time()!=start else 0, 
                                    (total-current)/(current/(time.time()-start)) if current/(time.time()-start)>0 else 0, 
                                    message, start)
        
        # Download file
        download_success = await download_file(
            download_url, 
            download_path,
            lambda current, total, speed, eta: progress_callback(current, total, speed, eta, status_msg, start_time)
        )
        
        if not download_success:
            await status_msg.edit_text("❌ **ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ.** ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.")
            return
            
        # Update status for upload
        await status_msg.edit_text("✅ **ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ!** ⬆️ **ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ...**")
        
        # Upload file to Telegram
        caption = f"📁 **ғɪʟᴇ ɴᴀᴍᴇ:** `{file_name}`\n💾 **sɪᴢᴇ:** `{file_size}`\n\n🚀 **ᴘᴏᴡᴇʀᴇᴅ ʙʏ @jetmirror**"
        
        # Reset start time for upload progress
        start_time = time.time()
        
        # Upload to Telegram
        uploaded_message = await upload_to_telegram(
            client if not user else user,
            message.chat.id,
            download_path,
            caption=caption,
            progress=lambda current, total: progress_for_pyrogram(current, total, status_msg, start_time),
            file_name=file_name
        )
        
        if not uploaded_message:
            await status_msg.edit_text("❌ **ᴜᴘʟᴏᴀᴅ ғᴀɪʟᴇᴅ.** ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.")
            return
            
        # Clean up after successful upload
        try:
            os.remove(download_path)
            await status_msg.delete()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            
    except Exception as e:
        logger.error(f"Process URL error: {e}")
        await message.reply_text(f"❌ **ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ:** `{str(e)}`")
@app.on_message(filters.text & filters.private & ~filters.command)
async def handle_message(client, message):
    """Handle incoming messages with URLs"""
    text = message.text.strip()
    
    # Check if it's a valid Terabox URL
    if is_valid_url(text):
        await process_url(client, message, text)
    else:
        await message.reply_text("❌ **ɪɴᴠᴀʟɪᴅ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ!** ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ʟɪɴᴋ.")
    # Web UI for status (optional)
app_flask = Flask(__name__)

@app_flask.route('/')
def index():
    return render_template('index.html', status="Bot is running")

def run_flask():
    app_flask.run(host='0.0.0.0', port=8080)

@app.on_message(filters.command("help"))
async def help_command(client, message):
    help_text = (
        "🔰 **Available Commands** 🔰\n\n"
        "• `/start` - Start the bot\n"
        "• `/help` - Show this help message\n"
        "• `/request` - Request a video\n"
        "• `/myrequests` - Check your request status\n"
        "• `/stats` - Show bot statistics (Admin only)\n\n"
        "📌 **How to use:**\n"
        "Simply send a Terabox link, and I'll download and send the file to you.\n\n"
        "For video requests, use the `/request` command or the button in the start message."
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats_command(client, message):
    """Show bot statistics for admins"""
    try:
        # Get aria2 stats
        global_stats = aria2.get_global_stat()
        download_speed = format_size(int(global_stats['downloadSpeed']))
        upload_speed = format_size(int(global_stats['uploadSpeed']))
        active_downloads = global_stats['numActive']
        waiting_downloads = global_stats['numWaiting']
        stopped_downloads = global_stats['numStopped']
        
        # Get system stats
        import psutil
        cpu_usage = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        memory_usage = f"{memory.percent}% ({format_size(memory.used)} / {format_size(memory.total)})"
        disk = psutil.disk_usage('/')
        disk_usage = f"{disk.percent}% ({format_size(disk.used)} / {format_size(disk.total)})"
        
        # Uptime
        import time
        start_time = os.path.getmtime("/proc/1")
        uptime_seconds = time.time() - start_time
        uptime = format_time(uptime_seconds)
        
        stats_text = (
            "📊 **Bot Statistics**\n\n"
            f"⏱️ **Uptime:** `{uptime}`\n"
            f"🔄 **Active Downloads:** `{active_downloads}`\n"
            f"⏳ **Waiting Downloads:** `{waiting_downloads}`\n"
            f"⏹️ **Stopped Downloads:** `{stopped_downloads}`\n"
            f"⬇️ **Download Speed:** `{download_speed}/s`\n"
            f"⬆️ **Upload Speed:** `{upload_speed}/s`\n\n"
            f"💻 **System Stats:**\n"
            f"CPU Usage: `{cpu_usage}%`\n"
            f"Memory Usage: `{memory_usage}`\n"
            f"Disk Usage: `{disk_usage}`"
        )
        
        await message.reply_text(stats_text)
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await message.reply_text(f"❌ **Error fetching stats:** `{str(e)}`")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast_command(client, message):
    """Broadcast message to all users who have interacted with the bot"""
    if len(message.command) < 2:
        await message.reply_text("❌ **Please provide a message to broadcast.**\n\nUsage: `/broadcast Your message here`")
        return
        
    broadcast_text = message.text.split("/broadcast ", 1)[1]
    
    # Get user list - for a real implementation, you would need to store user IDs
    # This is a simplified version using a in-memory set
    try:
        # Get user list from sample file (create this file with user IDs)
        user_ids = set()
        if os.path.exists("users.txt"):
            with open("users.txt", "r") as f:
                for line in f:
                    try:
                        user_ids.add(int(line.strip()))
                    except:
                        continue
        
        if not user_ids:
            await message.reply_text("❌ **No users found for broadcast.**")
            return
            
        # Send confirmation message
        confirm_msg = await message.reply_text(
            f"🔊 **About to broadcast to {len(user_ids)} users:**\n\n{broadcast_text}\n\n"
            "Are you sure you want to continue?"
        )
        
        # Add confirmation buttons
        confirm_button = InlineKeyboardButton("✅ Confirm", callback_data="broadcast_confirm")
        cancel_button = InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")
        confirm_markup = InlineKeyboardMarkup([[confirm_button, cancel_button]])
        
        await confirm_msg.edit_text(
            f"🔊 **About to broadcast to {len(user_ids)} users:**\n\n{broadcast_text}\n\n"
            "Are you sure you want to continue?",
            reply_markup=confirm_markup
        )
        
        # Store broadcast data for callback
        app.broadcast_data = {
            "text": broadcast_text,
            "users": user_ids
        }
        
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        await message.reply_text(f"❌ **Error preparing broadcast:** `{str(e)}`")

@app.on_callback_query(filters.regex(r"^broadcast_(confirm|cancel)$"))
async def broadcast_action(client, callback_query):
    """Handle broadcast confirmation or cancellation"""
    user_id = callback_query.from_user.id
    
    # Verify admin
    if user_id not in ADMIN_IDS:
        await callback_query.answer("You are not authorized to perform this action!", show_alert=True)
        return
        
    action = callback_query.data.split("_")[1]
    
    if action == "cancel":
        await callback_query.edit_message_text("🚫 **Broadcast cancelled.**")
        return
        
    if action == "confirm":
        # Check if broadcast data exists
        if not hasattr(app, "broadcast_data"):
            await callback_query.answer("Broadcast data not found. Please try again.", show_alert=True)
            return
            
        broadcast_text = app.broadcast_data["text"]
        users = app.broadcast_data["users"]
        
        # Update message
        await callback_query.edit_message_text(f"🔄 **Broadcasting to {len(users)} users...**")
        
        # Start broadcasting
        success = 0
        failed = 0
        
        progress_msg = await callback_query.message.reply_text("📊 **Broadcast Progress:** 0%")
        
        for i, user_id in enumerate(users):
            try:
                await client.send_message(user_id, broadcast_text)
                success += 1
            except Exception as e:
                logger.error(f"Failed to broadcast to {user_id}: {e}")
                failed += 1
                
            # Update progress every 20 users or at the end
            if (i + 1) % 20 == 0 or i + 1 == len(users):
                progress = ((i + 1) / len(users)) * 100
                await progress_msg.edit_text(
                    f"📊 **Broadcast Progress:** {progress:.1f}%\n"
                    f"✅ Success: {success}\n"
                    f"❌ Failed: {failed}"
                )
                
                # Sleep to avoid Telegram limits
                await asyncio.sleep(0.5)
                
        # Final update
        await callback_query.edit_message_text(
            f"✅ **Broadcast completed!**\n\n"
            f"📨 Total users: {len(users)}\n"
            f"✅ Successful: {success}\n"
            f"❌ Failed: {failed}"
        )
        
        # Clear broadcast data
        delattr(app, "broadcast_data")

@app.on_message(filters.command("restart") & filters.user(ADMIN_IDS))
async def restart_command(client, message):
    """Restart the bot (requires proper system setup)"""
    await message.reply_text("🔄 **Restarting bot...**")
    # Close resources
    await close_aiohttp_session()
    # Use os.execl to restart the process
    import sys
    os.execl(sys.executable, sys.executable, *sys.argv)

@app.on_message(filters.command("ping"))
async def ping_command(client, message):
    """Check bot's response time"""
    start_time = time.time()
    ping_msg = await message.reply_text("🏓 **Pinging...**")
    end_time = time.time()
    
    ping_time = round((end_time - start_time) * 1000, 2)
    
    await ping_msg.edit_text(f"🏓 **Pong!** `{ping_time}ms`")

@app.on_message(filters.command("cleancache") & filters.user(ADMIN_IDS))
async def clean_cache(client, message):
    """Clean download cache"""
    try:
        import shutil
        if os.path.exists("downloads"):
            shutil.rmtree("downloads")
            os.makedirs("downloads", exist_ok=True)
            
        await message.reply_text("✅ **Download cache cleaned successfully!**")
    except Exception as e:
        logger.error(f"Clean cache error: {e}")
        await message.reply_text(f"❌ **Error cleaning cache:** `{str(e)}`")

# Enhanced error handling
@app.on_message(filters.regex(r'https?://.*') & filters.private & ~filters.command)
async def url_handler(client, message):
    """Handle URLs that might not be Terabox links"""
    url = message.text.strip()
    
    if is_valid_url(url):
        await process_url(client, message, url)
    else:
        domains = ', '.join(VALID_DOMAINS[:5]) + '...'
        await message.reply_text(
            f"❌ **Not a valid Terabox link!**\n\n"
            f"I only support links from: {domains}\n\n"
            f"Please send a valid Terabox link."
        )

# Function to track user interactions
@app.on_message(filters.private)
async def track_user(client, message):
    """Track users who interact with the bot"""
    user_id = message.from_user.id
    
    # Simple tracking - append to file
    try:
        with open("users.txt", "a+") as f:
            f.seek(0)
            user_ids = set(line.strip() for line in f)
            if str(user_id) not in user_ids:
                f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Error tracking user: {e}")

# Start the bot
async def start_bot():
    global session
    
    # Setup AIOHTTP session
    session = await setup_aiohttp_session()
    
    # Start user client if available
    if user:
        await user.start()
        logger.info("User client started")
    
    # Start Flask server in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start bot
    await app.start()
    logger.info("Bot started!")
    
    # Keep the bot running
    await asyncio.Event().wait()

# Close resources on shutdown
async def shutdown():
    # Close sessions
    await close_aiohttp_session()
    
    # Stop clients
    if user:
        await user.stop()
    await app.stop()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(start_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped!")
        loop.run_until_complete(shutdown())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
