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
from pyrogram import idle
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
            
        # Clean up downloaded file
        try:
            os.remove(download_path)
        except Exception as e:
            logger.warning(f"Error removing file {download_path}: {e}")
            
        # Final success message
        await status_msg.edit_text("✅ **ᴘʀᴏᴄᴇss ᴄᴏᴍᴘʟᴇᴛᴇ!** ʏᴏᴜʀ ғɪʟᴇ ʜᴀs ʙᴇᴇɴ sᴇɴᴛ ᴀʙᴏᴠᴇ.")
        
    except Exception as e:
        logger.error(f"Error processing URL: {e}")
        try:
            await status_msg.edit_text(f"❌ **ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ ᴘʀᴏᴄᴇssɪɴɢ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ.**")
        except:
            pass  # In case the status message can't be edited

@app.on_message(filters.text & filters.private)
async def handle_links(client: Client, message: Message):
    """Handle incoming messages with links"""
    text = message.text.strip()
    
    # Check if it's a valid TeraBox URL
    if is_valid_url(text):
        await process_url(client, message, text)
    else:
        await message.reply_text("❌ **Invalid link.** Please send a valid TeraBox link.")

@app.on_message(filters.command("request"))
async def request_video(client: Client, message: Message):
    """Handle video request command"""
    await client.send_message(
        chat_id=message.chat.id,
        text="📽️ **Send a screenshot or image of the video you want to request.**\n\n"
        "Please include the following details in the caption:\n"
        "1. Video name/title\n"
        "2. Source (if any)\n"
        "3. Any additional information\n\n"
        "Example: `Avengers Endgame (2019) | HD Quality | Marvel`"
    )

@app.on_message(filters.photo & filters.private)
async def handle_request_image(client: Client, message: Message):
    """Process video request with image"""
    user_id = message.from_user.id
    
    # Check if user is subscribed
    is_member = await is_user_member(client, user_id)
    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
        reply_markup = InlineKeyboardMarkup([[join_button]])
        await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
        return
    
    # Check if caption is provided
    if not message.caption:
        await message.reply_text("❌ **Please provide details about the video in the caption.**")
        return
    
    try:
        # Forward the request to the request channel
        await message.forward(REQUEST_CHANNEL_ID)
        
        # Send confirmation to user
        await message.reply_text(
            "✅ **Your request has been submitted!**\n\n"
            "We will try to fulfill your request as soon as possible.\n"
            "Please be patient while we process it."
        )
    except Exception as e:
        logger.error(f"Error handling request: {e}")
        await message.reply_text("❌ **Error submitting your request.** Please try again later.")

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    """Display help information"""
    help_text = (
        "📚 **ᴄᴏᴍᴍᴀɴᴅs & ᴜsᴀɢᴇ**\n\n"
        "• Send any TeraBox link to download directly\n"
        "• `/start` - Start the bot\n"
        "• `/help` - Show this help message\n"
        "• `/request` - Request a video\n\n"
        "🔗 **sᴜᴘᴘᴏʀᴛᴇᴅ ᴅᴏᴍᴀɪɴs**\n"
        "• terabox.com\n"
        "• nephobox.com\n"
        "• 4funbox.com\n"
        "• mirrobox.com\n"
        "• teraboxapp.com\n"
        "• And many more alternative domains\n\n"
        "💡 For any issues or feedback, contact @rtx5069"
    )
    
    help_button = InlineKeyboardButton("ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url="https://t.me/jetmirror")
    reply_markup = InlineKeyboardMarkup([[help_button]])
    
    await message.reply_text(help_text, reply_markup=reply_markup)

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats_command(client: Client, message: Message):
    """Show bot statistics to admins"""
    if not ADMIN_IDS or message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        # Get aria2 stats
        aria_stats = aria2.get_global_stat()
        download_speed = format_size(int(aria_stats.get('downloadSpeed', 0)))
        active_downloads = aria_stats.get('numActive', '0')
        waiting_downloads = aria_stats.get('numWaiting', '0')
        
        # Get system stats
        total_memory, used_memory, _ = [format_size(int(x) * 1024) for x in os.popen('free -t -m').readlines()[-1].split()[1:]]
        cpu_usage = os.popen("top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'").read().strip()
        disk_usage = os.popen("df -h / | awk 'NR==2 {print $5}'").read().strip()
        
        stats_text = (
            "📊 **ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs**\n\n"
            f"**ᴅᴏᴡɴʟᴏᴀᴅ sᴘᴇᴇᴅ:** `{download_speed}/s`\n"
            f"**ᴀᴄᴛɪᴠᴇ ᴅᴏᴡɴʟᴏᴀᴅs:** `{active_downloads}`\n"
            f"**ǫᴜᴇᴜᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅs:** `{waiting_downloads}`\n\n"
            f"**ᴄᴘᴜ ᴜsᴀɢᴇ:** `{cpu_usage}%`\n"
            f"**ᴍᴇᴍᴏʀʏ ᴜsᴀɢᴇ:** `{used_memory}/{total_memory}`\n"
            f"**ᴅɪsᴋ ᴜsᴀɢᴇ:** `{disk_usage}`\n"
            f"**ᴜᴘᴛɪᴍᴇ:** `{format_time(time.time() - psutil.boot_time())}`"
        )
        
        await message.reply_text(stats_text)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await message.reply_text("❌ **Error getting stats.**")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast_command(client: Client, message: Message):
    """Broadcast a message to all users"""
    if not ADMIN_IDS or message.from_user.id not in ADMIN_IDS:
        return
    
    # Check if there's a message to broadcast
    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply_text("❌ **Please provide a message to broadcast or reply to a message.**")
        return
    
    confirm_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data="confirm_broadcast"),
            InlineKeyboardButton("❌ No", callback_data="cancel_broadcast")
        ]
    ])
    
    # Store the message to broadcast
    if message.reply_to_message:
        app.broadcast_message = message.reply_to_message
    else:
        broadcast_text = message.text.split(None, 1)[1]
        app.broadcast_message = broadcast_text
    
    await message.reply_text(
        "⚠️ **Are you sure you want to broadcast this message to all users?**\n\n"
        "This action cannot be undone.",
        reply_markup=confirm_keyboard
    )

@app.on_callback_query(filters.regex("confirm_broadcast"))
async def confirm_broadcast(client, callback_query):
    """Process broadcast confirmation"""
    if not ADMIN_IDS or callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("You are not authorized to use this feature.", show_alert=True)
        return
    
    await callback_query.answer("Broadcasting message...")
    await callback_query.edit_message_text("🔄 **Broadcasting in progress...**")
    
    # Placeholder for user database
    # In a real implementation, you would get users from a database
    users = [callback_query.from_user.id]  # Just for testing
    
    success = 0
    failed = 0
    
    for user_id in users:
        try:
            if isinstance(app.broadcast_message, str):
                await client.send_message(user_id, app.broadcast_message)
            else:
                await app.broadcast_message.copy(user_id)
            success += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            failed += 1
        
        # Sleep to avoid flood limits
        await asyncio.sleep(0.1)
    
    await callback_query.edit_message_text(
        f"✅ **Broadcast completed**\n\n"
        f"**Success:** `{success}`\n"
        f"**Failed:** `{failed}`"
    )
    
    # Clear the stored broadcast message
    app.broadcast_message = None

@app.on_callback_query(filters.regex("cancel_broadcast"))
async def cancel_broadcast(client, callback_query):
    """Cancel broadcast operation"""
    if not ADMIN_IDS or callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("You are not authorized to use this feature.", show_alert=True)
        return
    
    app.broadcast_message = None
    await callback_query.answer("Broadcast cancelled.")
    await callback_query.edit_message_text("❌ **Broadcast cancelled.**")

@app.on_message(filters.command("clear") & filters.user(ADMIN_IDS))
async def clear_downloads(client: Client, message: Message):
    """Clear all downloads"""
    if not ADMIN_IDS or message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        # Clear aria2 downloads
        aria2.remove_all()
        
        # Clear downloads folder
        if os.path.exists("downloads"):
            for root, dirs, files in os.walk("downloads", topdown=False):
                for file in files:
                    os.remove(os.path.join(root, file))
                for dir in dirs:
                    os.rmdir(os.path.join(root, dir))
        
        await message.reply_text("✅ **All downloads cleared successfully.**")
    except Exception as e:
        logger.error(f"Error clearing downloads: {e}")
        await message.reply_text(f"❌ **Error clearing downloads: {e}**")

# Create a simple web server to keep the bot alive
app_server = Flask(__name__)

@app_server.route('/')
def index():
    return "Bot is running!"

def run_server():
    app_server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

async def start_bot():
    global user
    
    # Start aria2 client
    logger.info("Starting aria2 client...")
    
    # Start user client if available
    if USER_SESSION_STRING:
        try:
            await user.start()
            logger.info("User client started successfully")
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            user = None
    
    # Start the bot
    await app.start()
    logger.info("Bot started successfully")
    
    # Start aiohttp session
    await setup_aiohttp_session()
    
    # Create downloads directory
    os.makedirs("downloads", exist_ok=True)
    
    # Keep the bot running
    await idle()
    
    # Stop everything when the bot stops
    await app.stop()
    if user:
        await user.stop()
    await close_aiohttp_session()

if __name__ == "__main__":
    # Start the web server in a separate thread
    server_thread = Thread(target=run_server)
    server_thread.start()
    
    # Start the bot
    loop = asyncio.get_event_loop()
    
    try:
        loop.run_until_complete(start_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
    finally:
        loop.close()
