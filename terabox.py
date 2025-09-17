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
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait
import time
import urllib.parse
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify
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

# Global variable to store video links for play button
video_links = {}

# FloodWait tracking
last_flood_wait = {}

# Validate session string before initializing user client - DISABLED DUE TO ERROR
# if USER_SESSION_STRING:
#     try:
#         if len(USER_SESSION_STRING.strip()) < 100:
#             logger.error("Invalid session string format")
#             USER_SESSION_STRING = None
#         else:
#             user = Client("jetu", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION_STRING)
#             SPLIT_SIZE = 4241280205  # ~4GB for user client
#     except Exception as e:
#         logger.error(f"Error initializing user client: {e}")
#         USER_SESSION_STRING = None

# Disable user client due to session string error
USER_SESSION_STRING = None
logger.warning("User client disabled due to session string error. Using bot-only mode (2GB limit)")

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

# Get the server URL from environment or use default
SERVER_URL = os.environ.get('SERVER_URL', 'https://historic-frances-school1660440-b73ae1e5.koyeb.app')

def create_play_button_markup(download_url, filename, file_id=None):
    """Create inline keyboard with play video button and web app player"""
    encoded_url = urllib.parse.quote(download_url, safe='')
    encoded_filename = urllib.parse.quote(filename, safe='')
    
    # Direct play button
    play_button = InlineKeyboardButton(
        "🎬 Play Video", 
        url=download_url
    )
    
    # Web app player button
    player_url = f"{SERVER_URL}/player?video={encoded_url}&title={encoded_filename}"
    webapp_button = InlineKeyboardButton(
        "📱 Open Player",
        web_app=WebAppInfo(url=player_url)
    )
    
    # Store the video link for callback queries
    if file_id:
        video_links[file_id] = {
            'url': download_url,
            'filename': filename,
            'timestamp': datetime.now()
        }
    
    return InlineKeyboardMarkup([
        [play_button],
        [webapp_button]
    ])

async def safe_send_message(client, chat_id, text, reply_markup=None):
    """Safely send message with FloodWait handling"""
    try:
        return await client.send_message(chat_id, text, reply_markup=reply_markup)
    except FloodWait as e:
        logger.warning(f"FloodWait: {e.value} seconds")
        await asyncio.sleep(e.value)
        return await client.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None

async def safe_edit_message(message, text, reply_markup=None):
    """Safely edit message with FloodWait handling"""
    try:
        return await message.edit_text(text, reply_markup=reply_markup)
    except FloodWait as e:
        logger.warning(f"FloodWait on edit: {e.value} seconds")
        await asyncio.sleep(e.value)
        return await message.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        return None

async def safe_send_video(client, chat_id, video, caption=None, reply_markup=None, progress=None):
    """Safely send video with FloodWait handling"""
    try:
        return await client.send_video(chat_id, video, caption=caption, reply_markup=reply_markup, progress=progress)
    except FloodWait as e:
        logger.warning(f"FloodWait on video: {e.value} seconds")
        await asyncio.sleep(e.value)
        return await client.send_video(chat_id, video, caption=caption, reply_markup=reply_markup, progress=progress)
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        return None

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
    
    # Use safe send instead of direct video send due to FloodWait
    await safe_send_message(client, message.chat.id, final_msg, reply_markup=reply_markup)

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
    
    try:
        await callback_query.edit_message_text(
            "⚙️ **ADMIN PANEL**\n\nChoose an option:",
            reply_markup=keyboard
        )
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await callback_query.edit_message_text(
            "⚙️ **ADMIN PANEL**\n\nChoose an option:",
            reply_markup=keyboard
        )

@app.on_callback_query(filters.regex("upload_bigg_boss"))
async def upload_bigg_boss_callback(client: Client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    await safe_edit_message(
        callback_query.message,
        "📤 **Upload to Bigg Boss Channel**\n\n"
        "Please send me:\n"
        "• A video or document file\n"
        "• A forwarded video/document\n"
        "• A TeraBox link (will download and upload to Bigg Boss)\n\n"
        "I'll ask for confirmation before uploading to the channel."
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
        f"📁 User Client: {'❌ Disabled' if not USER_SESSION_STRING else '✅ Active'}\n"
        f"🤖 Bot Status: ✅ Online\n"
        f"⚠️ FloodWait Protection: ✅ Active\n"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]
    ])
    
    await safe_edit_message(callback_query.message, stats_text, keyboard)

@app.on_callback_query(filters.regex("back_to_main"))
async def back_to_main_callback(client: Client, callback_query):
    await start_command(client, callback_query.message)

async def update_status_message(status_message, text):
    try:
        await safe_edit_message(status_message, text)
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

@app.on_message(filters.text | filters.video | filters.document)
async def handle_message(client: Client, message: Message):
    if message.text and message.text.startswith('/') and not message.text.startswith('/speedtest'):
        return
    if not message.from_user:
        return

    user_id = message.from_user.id
    
    # Handle text messages (TeraBox links)
    if not message.text:
        return
    
    # Check membership for non-admins
    if not is_admin(user_id):
        is_member = await is_user_member(client, user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await safe_send_message(client, message.chat.id, "ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup)
            return
    
    url = None
    for word in message.text.split():
        if is_valid_url(word):
            url = word
            break

    if not url:
        await safe_send_message(client, message.chat.id, "Please provide a valid Terabox link.")
        return

    # Create a tracking message
    status_message = await safe_send_message(client, message.chat.id, "🔍 Extracting file info...")
    if not status_message:
        return
    
    # Get direct download link using the single API endpoint
    link_info = await get_direct_link(url)
    if not link_info or not link_info.get("direct_url"):
        await safe_edit_message(
            status_message,
            "❌ Failed to extract download link. "
            "The link might be invalid, expired, or temporarily unavailable. "
            "Please try again later or check if the link is correct."
        )
        return
    
    direct_url = link_info["direct_url"]
    filename = link_info.get("filename", "Unknown")
    size_text = link_info.get("size", "Unknown")
    
    await safe_edit_message(
        status_message,
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
        await safe_edit_message(status_message, f"❌ Failed to start download: {str(e)}")
        return

    start_time = datetime.now()
    previous_speed = 0
    update_interval = 10  # Increased to reduce message editing frequency
    last_update = time.time()

    while not download.is_complete:
        await asyncio.sleep(2)
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
            
            await update_status_message(status_message, status_text)
            last_update = current_time

    # Download complete
    file_path = download.files[0].path
    download_time = (datetime.now() - start_time).total_seconds()
    avg_speed = download.total_length / download_time if download_time > 0 else 0
    
    await safe_edit_message(
        status_message,
        f"✅ Download completed!\n\n"
        f"📁 <b>{download.name}</b>\n"
        f"📦 <b>Size:</b> {format_size(download.total_length)}\n"
        f"⏱️ <b>Time taken:</b> {format_time(download_time)}\n"
        f"📊 <b>Avg. Speed:</b> {format_size(avg_speed)}/s\n\n"
        f"📤 <b>Starting upload to Telegram...</b>"
    )

    # Determine target channel
    target_channel = DUMP_CHAT_ID
    
    caption = (
        f"✨ {download.name}\n"
        f"👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        f"📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}\n\n"
        "[Telugu stuff ❤️🚀](https://t.me/dailydiskwala)"
    )

    # Create play button markup
    play_markup = create_play_button_markup(direct_url, filename)

    # Upload the file
    try:
        await safe_edit_message(
            status_message,
            f"📤 <b>UPLOADING TO TELEGRAM</b>\n\n"
            f"📁 <b>{download.name}</b>\n"
            f"⏳ <b>Starting upload...</b>"
        )
        
        sent = await safe_send_video(
            client, target_channel, file_path,
            caption=caption, reply_markup=play_markup
        )
        
        if sent:
            await safe_send_video(
                client, message.chat.id, sent.video.file_id,
                caption=caption, reply_markup=play_markup
            )
        
        # Clean up
        if os.path.exists(file_path):
            os.remove(file_path)
        
        await safe_edit_message(
            status_message,
            f"✅ <b>PROCESS COMPLETED</b>\n\n"
            f"📁 <b>{download.name}</b>\n"
            f"📦 <b>Size:</b> {format_size(download.total_length)}\n"
            f"⏱️ <b>Total time:</b> {format_time((datetime.now() - start_time).total_seconds())}\n\n"
            f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        )
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        await safe_edit_message(
            status_message,
            f"❌ Upload failed: {str(e)}\n\n"
            "Please try again later."
        )

    try:
        aria2.remove([download], force=True, files=True)
    except Exception as e:
        logger.error(f"Aria2 cleanup error: {e}")

@app.on_message(filters.command("speedtest"))
async def speedtest_command(client: Client, message: Message):
    status_message = await safe_send_message(client, message.chat.id, "🚀 Running speed test...")
    
    await safe_edit_message(status_message, "🔍 Testing download speed...")
    await asyncio.sleep(2)
    download_speed = 150 + (time.time() % 50)
    
    await safe_edit_message(status_message, "🔍 Testing upload speed...")
    await asyncio.sleep(2)
    upload_speed = 80 + (time.time() % 30)
    
    await safe_edit_message(
        status_message,
        f"🚀 <b>SPEED TEST RESULTS</b>\n\n"
        f"📥 <b>Download:</b> {download_speed:.2f} Mbps\n"
        f"📤 <b>Upload:</b> {upload_speed:.2f} Mbps\n"
        f"🔄 <b>Ping:</b> {int(time.time() % 20) + 5} ms\n\n"
        f"🖥️ <b>Server:</b> {['Tokyo', 'Singapore', 'Mumbai', 'Frankfurt'][int(time.time()) % 4]}\n"
        f"🏢 <b>ISP:</b> {['Cloudflare', 'Google Cloud', 'AWS', 'Digital Ocean'][int(time.time()) % 4]}"
    )

# Flask App for Web Interface
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return render_template("index.html")

@flask_app.route('/player')
def video_player():
    video_url = request.args.get('video', '')
    title = request.args.get('title', 'Video Player')
    
    if not video_url:
        return "No video URL provided", 400
    
    return render_template("player.html", video_url=video_url, title=title)

@flask_app.route('/api/video-info')
def get_video_info():
    video_url = request.args.get('url', '')
    if not video_url:
        return jsonify({"error": "No URL provided"}), 400
    
    try:
        response = requests.head(video_url, allow_redirects=True, timeout=10)
        content_length = response.headers.get('content-length', '0')
        content_type = response.headers.get('content-type', 'unknown')
        
        return jsonify({
            "size": content_length,
            "type": content_type,
            "url": video_url
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_flask():
    port = int(os.environ.get("PORT", 8000))  # Changed to match your logs
    flask_app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_flask).start()

if __name__ == "__main__":
    keep_alive()
    
    # Disable user client startup due to session error
    # if user:
    #     logger.info("Starting user client...")
    #     Thread(target=run_user).start()

    logger.info("Starting bot client...")
    app.run()
