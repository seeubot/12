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
from pyrogram.errors import FloodWait, SessionPasswordNeeded, BadRequest
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

try:
    # Setup aria2 client
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
        "min-split-size": "4M",
        "split": "10"
    }
    aria2.set_global_options(options)
except Exception as e:
    logger.error(f"Failed to initialize aria2: {e}")
    aria2 = None

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
    logging.error("REQUEST_CHANNEL_ID variable is missing! Exiting now")
    exit(1)
else:
    REQUEST_CHANNEL_ID = int(REQUEST_CHANNEL_ID)

USER_SESSION_STRING = os.environ.get('USER_SESSION_STRING', '')
SPLIT_SIZE = 2093796556  # Default 2GB limit

# Updated valid terabox domains
VALID_DOMAINS = [
    'terabox.com', 'nephobox.com', '4funbox.com', 'mirrobox.com', 
    'momerybox.com', 'teraboxapp.com', '1024tera.com', 
    'terabox.app', 'gibibox.com', 'goaibox.com', 'terasharelink.com', 
    'teraboxlink.com', 'terafileshare.com'
]
last_update_time = 0

# Track users in request mode
users_in_request_mode = {}

app = Client("jetbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Initialize user client safely
user = None
if USER_SESSION_STRING:
    try:
        # Using safer initialization
        user = Client(
            "jetu", 
            api_id=API_ID, 
            api_hash=API_HASH, 
            session_string=USER_SESSION_STRING,
            in_memory=True  # Use in-memory session to avoid corrupt file
        )
        SPLIT_SIZE = 4241280205  # ~ 4GB limit with user client
    except Exception as e:
        logger.error(f"Failed to initialize user client: {e}")
        USER_SESSION_STRING = None
        user = None

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

def generate_progress_bar(percentage, length=10):
    # Modern, clean progress bar with Unicode blocks
    filled_length = int(length * percentage // 100)
    empty_length = length - filled_length
    
    bar = '█' * filled_length + '░' * empty_length
    return f"`{bar}`"

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    # Reset any request mode for the user
    if message.from_user.id in users_in_request_mode:
        del users_in_request_mode[message.from_user.id]
        
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
    developer_button = InlineKeyboardButton("ᴅᴇᴠᴇʟᴏᴘᴇʀ ⚡️", url="https://t.me/rtx5069")
    repo69 = InlineKeyboardButton("ʀᴇᴘᴏ 🌐", url="https://github.com/Hrishi2861/Terabox-Downloader-Bot")
    request_button = InlineKeyboardButton("ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏ 🎬", callback_data="request_video")
    
    user_mention = message.from_user.mention
    reply_markup = InlineKeyboardMarkup([
        [join_button, developer_button], 
        [repo69],
        [request_button]
    ])
    
    final_msg = f"ᴡᴇʟᴄᴏᴍᴇ, {user_mention}.\n\n🌟 ɪ ᴀᴍ ᴀ ᴛᴇʀᴀʙᴏx ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ. sᴇɴᴅ ᴍᴇ ᴀɴʏ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ ɪ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴡɪᴛʜɪɴ ғᴇᴡ sᴇᴄᴏɴᴅs ᴀɴᴅ sᴇɴᴅ ɪᴛ ᴛᴏ ʏᴏᴜ ✨."
    final_msg += "\n\n📸 ʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏs ʙʏ sᴇɴᴅɪɴɢ sᴄʀᴇᴇɴsʜᴏᴛs!"
    
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

@app.on_callback_query()
async def handle_callback(client, callback_query):
    user_id = callback_query.from_user.id
    
    # Check for force subscription
    is_member = await is_user_member(client, user_id)
    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
        reply_markup = InlineKeyboardMarkup([[join_button]])
        await callback_query.answer("You must join my channel to use this feature!", show_alert=True)
        await callback_query.message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
        return
    
    if callback_query.data == "request_video":
        # Set user in request mode
        users_in_request_mode[user_id] = {"state": "waiting_for_image"}
        
        # Send instructions
        cancel_button = InlineKeyboardButton("ᴄᴀɴᴄᴇʟ ❌", callback_data="cancel_request")
        reply_markup = InlineKeyboardMarkup([[cancel_button]])
        
        await callback_query.message.reply_text(
            "📸 ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ sᴄʀᴇᴇɴsʜᴏᴛ ᴏʀ ɪᴍᴀɢᴇ ᴏғ ᴛʜᴇ ᴠɪᴅᴇᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʀᴇǫᴜᴇsᴛ.",
            reply_markup=reply_markup
        )
        await callback_query.answer("Please send a screenshot of the video you want.")
    
    elif callback_query.data == "cancel_request":
        if user_id in users_in_request_mode:
            del users_in_request_mode[user_id]
        await callback_query.message.reply_text("❌ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ.")
        await callback_query.answer("Request cancelled")

async def update_status_message(status_message, text):
    try:
        await status_message.edit_text(text)
    except Exception as e:
        logger.error(f"Failed to update status message: {e}")

@app.on_message(filters.photo)
async def handle_photo(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Check if user is in request mode
    if user_id in users_in_request_mode and users_in_request_mode[user_id]["state"] == "waiting_for_image":
        # Update user state
        users_in_request_mode[user_id] = {"state": "waiting_for_description"}
        
        # Save the photo_id for later
        users_in_request_mode[user_id]["photo_id"] = message.photo.file_id
        
        # Ask for description
        cancel_button = InlineKeyboardButton("ᴄᴀɴᴄᴇʟ ❌", callback_data="cancel_request")
        reply_markup = InlineKeyboardMarkup([[cancel_button]])
        
        await message.reply_text(
            "✍️ ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴏʀ ɴᴀᴍᴇ ᴏғ ᴛʜᴇ ᴠɪᴅᴇᴏ ʏᴏᴜ'ʀᴇ ʀᴇǫᴜᴇsᴛɪɴɢ.",
            reply_markup=reply_markup
        )
        return

@app.on_message(filters.text)
async def handle_message(client: Client, message: Message):
    if message.text.startswith('/'):
        if not message.text.startswith('/start'):
            return
    
    user_id = message.from_user.id
    if not message.from_user:
        return

    # Check if user is in request mode and waiting for description
    if user_id in users_in_request_mode and users_in_request_mode[user_id]["state"] == "waiting_for_description":
        # Process the video request
        photo_id = users_in_request_mode[user_id]["photo_id"]
        description = message.text
        
        # Reset user state
        del users_in_request_mode[user_id]
        
        # Check for force subscription
        is_member = await is_user_member(client, user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Forward the request to the request channel
        try:
            # Send the photo with description to the request channel
            await client.send_photo(
                chat_id=REQUEST_CHANNEL_ID,
                photo=photo_id,
                caption=f"🎬 **ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ**\n\n"
                        f"📝 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {description}\n\n"
                        f"👤 **ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ:** {message.from_user.mention} (`{user_id}`)\n"
                        f"⏰ **ᴛɪᴍᴇ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            # Notify user that request was sent
            await message.reply_text(
                "✅ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜʙᴍɪᴛᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!\n\n"
                "ᴏᴜʀ ᴛᴇᴀᴍ ᴡɪʟʟ ʀᴇᴠɪᴇᴡ ɪᴛ ᴀɴᴅ ᴘʀᴏᴄᴇss ɪᴛ ᴀs sᴏᴏɴ ᴀs ᴘᴏssɪʙʟᴇ."
            )
        except Exception as e:
            logger.error(f"Error sending request to channel: {e}")
            await message.reply_text("❌ sᴏʀʀʏ, ᴛʜᴇʀᴇ ᴡᴀs ᴀɴ ᴇʀʀᴏʀ ᴘʀᴏᴄᴇssɪɴɢ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ. ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.")
        
        return
    
    # Regular URL processing for Terabox links
    is_member = await is_user_member(client, user_id)

    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
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

    # Check if aria2 is initialized
    if aria2 is None:
        await message.reply_text("❌ Download service is currently unavailable. Please try again later.")
        return

    encoded_url = urllib.parse.quote(url)
    final_url = f"https://teradlrobot.cheemsbackup.workers.dev/?url={encoded_url}"

    try:
        download = aria2.add_uris([final_url])
        status_message = await message.reply_text("sᴇɴᴅɪɴɢ ʏᴏᴜ ᴛʜᴇ ᴍᴇᴅɪᴀ...🤤")
    except Exception as e:
        logger.error(f"Failed to add download: {e}")
        await message.reply_text("❌ Failed to start download. The download service might be down. Please try again later.")
        return

    start_time = datetime.now()
    download_error = False

    try:
        # Monitor download progress
        while not download.is_complete:
            await asyncio.sleep(15)
            
            try:
                download.update()
                progress = download.progress
            except Exception as e:
                logger.error(f"Error updating download status: {e}")
                download_error = True
                break

            elapsed_time = datetime.now() - start_time
            elapsed_minutes, elapsed_seconds = divmod(elapsed_time.seconds, 60)
            
            # Improved cleaner progress bar with emojis
            progress_bar = generate_progress_bar(progress)
            
            status_text = (
                f"📥 **ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ**\n\n"
                f"**{download.name}**\n\n"
                f"{progress_bar} `{progress:.1f}%`\n\n"
                f"⚡️ **sᴘᴇᴇᴅ:** {format_size(download.download_speed)}/s\n"
                f"💾 **sɪᴢᴇ:** {format_size(download.completed_length)}/{format_size(download.total_length)}\n"
                f"⏱️ **ᴇᴛᴀ:** {download.eta}\n"
                f"⏰ **ᴇʟᴀᴘsᴇᴅ:** {elapsed_minutes}m {elapsed_seconds}s\n\n"
                f"👤 {message.from_user.mention}"
            )
            
            # Handle update message with flood protection
            try:
                await update_status_message(status_message, status_text)
            except FloodWait as e:
                logger.error(f"Flood wait detected! Sleeping for {e.value} seconds")
                await asyncio.sleep(e.value)
                await update_status_message(status_message, status_text)

        if download_error:
            await status_message.edit_text("❌ Download failed. Please try again later.")
            return

        file_path = download.files[0].path
        caption = (
            f"✨ {download.name}\n"
            f"👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
            f"📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}\n\n"
            "[ᴘᴏᴡᴇʀᴇᴅ ʙʏ ᴊᴇᴛ-ᴍɪʀʀᴏʀ ❤️🚀](https://t.me/JetMirror)"
        )

        await handle_upload(client, message, status_message, file_path, caption, user_id)

    except Exception as e:
        logger.error(f"Download error: {e}")
        await status_message.edit_text(f"❌ Download failed: {str(e)[:100]}... Please try again later.")

async def handle_upload(client, message, status_message, file_path, caption, user_id):
    last_update_time = time.time()
    UPDATE_INTERVAL = 15
    start_time = datetime.now()

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

    async def upload_progress(current, total):
        progress = (current / total) * 100
        elapsed_time = datetime.now() - start_time
        elapsed_minutes, elapsed_seconds = divmod(elapsed_time.seconds, 60)
        
        # Clean upload progress bar
        progress_bar = generate_progress_bar(progress)
        
        status_text = (
            f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ**\n\n"
            f"**{os.path.basename(file_path)}**\n\n"
            f"{progress_bar} `{progress:.1f}%`\n\n"
            f"⚡️ **sᴘᴇᴇᴅ:** {format_size(current / elapsed_time.seconds if elapsed_time.seconds > 0 else 0)}/s\n"
            f"💾 **sɪᴢᴇ:** {format_size(current)}/{format_size(total)}\n"
            f"⏰ **ᴇʟᴀᴘsᴇᴅ:** {elapsed_minutes}m {elapsed_seconds}s\n\n"
            f"👤 {message.from_user.mention}"
        )
        await update_status(status_message, status_text)

    async def split_video_with_ffmpeg(input_path, output_prefix, split_size):
        try:
            original_ext = os.path.splitext(input_path)[1].lower() or '.mp4'
            start_time = datetime.now()
            last_progress_update = time.time()
            
            try:
                proc = await asyncio.create_subprocess_exec(
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', input_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                total_duration = float(stdout.decode().strip())
            except Exception as e:
                logger.error(f"ffprobe error: {e}")
                # Default to a reasonable duration if ffprobe fails
                total_duration = 3600  # 1 hour as fallback
            
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
                    
                    # Clean split progress display
                    progress_percentage = ((i+1) / parts) * 100
                    progress_bar = generate_progress_bar(progress_percentage)
                    
                    status_text = (
                        f"✂️ **sᴘʟɪᴛᴛɪɴɢ ᴠɪᴅᴇᴏ**\n\n"
                        f"**{os.path.basename(input_path)}**\n\n"
                        f"{progress_bar} `{progress_percentage:.1f}%`\n\n"
                        f"🔄 **ᴘᴀʀᴛ:** {i+1}/{parts}\n"
                        f"⏰ **ᴇʟᴀᴘsᴇᴅ:** {elapsed.seconds // 60}m {elapsed.seconds % 60}s"
                    )
                    await update_status(status_message, status_text)
                    last_progress_update = current_time
                
                output_path = f"{output_prefix}.{i+1:03d}{original_ext}"
                
                # Try using ffmpeg first, if it fails fall back to xtra
                try:
                    cmd = [
                        'ffmpeg', '-y', '-ss', str(i * duration_per_part),
                        '-i', input_path, '-t', str(duration_per_part),
                        '-c', 'copy', '-map', '0',
                        '-avoid_negative_ts', 'make_zero',
                        output_path
                    ]
                    
                    proc = await asyncio.create_subprocess_exec(*cmd)
                    await proc.wait()
                except Exception:
                    try:
                        # Try with xtra as fallback
                        cmd = [
                            'xtra', '-y', '-ss', str(i * duration_per_part),
                            '-i', input_path, '-t', str(duration_per_part),
                            '-c', 'copy', '-map', '0',
                            '-avoid_negative_ts', 'make_zero',
                            output_path
                        ]
                        
                        proc = await asyncio.create_subprocess_exec(*cmd)
                        await proc.wait()
                    except Exception as e:
                        logger.error(f"Splitting error with both ffmpeg and xtra: {e}")
                        return [input_path]  # Return original if splitting fails
                
                split_files.append(output_path)
            
            return split_files
        except Exception as e:
            logger.error(f"Split error: {e}")
            return [input_path]  # Return original file path in case of error

    try:
        file_size = os.path.getsize(file_path)
        
        if file_size > SPLIT_SIZE:
            # Clean splitting notification
            progress_bar = generate_progress_bar(0)  # 0% progress to start
            
            await update_status(
                status_message,
                f"✂️ **sᴘʟɪᴛᴛɪɴɢ ᴠɪᴅᴇᴏ**\n\n"
                f"**{os.path.basename(file_path)}**\n\n"
                f"{progress_bar} `0%`\n\n"
                f"💾 **sɪᴢᴇ:** {format_size(file_size)}\n"
                f"⏱️ **ᴇsᴛ. ᴛɪᴍᴇ:** Computing...\n\n"
                f"👤 {message.from_user.mention}"
            )
            
            # Split the file
            split_dir = os.path.dirname(file_path)
            output_prefix = os.path.join(split_dir, os.path.splitext(os.path.basename(file_path))[0])
            split_files = await split_video_with_ffmpeg(file_path, output_prefix, SPLIT_SIZE)
            
            uploaded_parts = []
            for i, part_path in enumerate(split_files):
                part_size = os.path.getsize(part_path)
                part_base_name = os.path.basename(part_path)
                part_caption = f"{caption}\n\n📑 **ᴘᴀʀᴛ {i+1}/{len(split_files)}**"
                
                await update_status(
                    status_message,
                    f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ ᴘᴀʀᴛ {i+1}/{len(split_files)}**\n\n"
                    f"**{part_base_name}**\n\n"
                    f"{generate_progress_bar(0)} `0%`\n\n"
                    f"💾 **sɪᴢᴇ:** {format_size(part_size)}\n"
                    f"⏱️ **ᴇsᴛ. ᴛɪᴍᴇ:** Computing...\n\n"
                    f"👤 {message.from_user.mention}"
                )
                
                # Upload each part to Telegram
                try:
                    # Get file mimetype
                    ext = os.path.splitext(part_path)[1].lower()
                    is_video = ext in ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']
                    is_audio = ext in ['.mp3', '.m4a', '.flac', '.wav', '.ogg']
                    is_image = ext in ['.jpg', '.jpeg', '.png', '.webp']
                    
                    # Upload based on file type
                    if is_video:
                        uploaded_file = await client.send_video(
                            chat_id=DUMP_CHAT_ID,
                            video=part_path,
                            caption=part_caption,
                            progress=upload_progress,
                            file_name=part_base_name,
                            supports_streaming=True
                        )
                    elif is_audio:
                        uploaded_file = await client.send_audio(
                            chat_id=DUMP_CHAT_ID,
                            audio=part_path,
                            caption=part_caption,
                            progress=upload_progress,
                            file_name=part_base_name
                        )
                    elif is_image:
                        uploaded_file = await client.send_photo(
                            chat_id=DUMP_CHAT_ID,
                            photo=part_path,
                            caption=part_caption,
                            progress=upload_progress
                        )
                    else:
                        uploaded_file = await client.send_document(
                            chat_id=DUMP_CHAT_ID,
                            document=part_path,
                            caption=part_caption,
                            progress=upload_progress,
                            file_name=part_base_name
                        )
                    
                    # Forward to the user
                    await client.forward_messages(
                        chat_id=message.chat.id,
                        from_chat_id=DUMP_CHAT_ID,
                        message_ids=uploaded_file.id
                    )
                    
                    uploaded_parts.append(part_path)
                except Exception as e:
                    logger.error(f"Upload error for part {i+1}: {e}")
                    await message.reply_text(f"❌ Failed to upload part {i+1}: {str(e)[:100]}...")
            
            # Clean up split files after upload
            for part_path in uploaded_parts:
                try:
                    if part_path != file_path:  # Don't delete original file
                        os.remove(part_path)
                except Exception as e:
                    logger.error(f"Error removing split file {part_path}: {e}")
            
            # Final success message
            await status_message.edit_text(
                f"✅ **ᴜᴘʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!**\n\n"
                f"📚 **ғɪʟᴇ:** {os.path.basename(file_path)}\n"
                f"📑 **ᴘᴀʀᴛs:** {len(split_files)}\n"
                f"💾 **ᴛᴏᴛᴀʟ sɪᴢᴇ:** {format_size(file_size)}\n\n"
                f"👤 {message.from_user.mention}"
            )
        else:
            # Upload single file
            filename = os.path.basename(file_path)
            
            # Determine file type based on extension
            ext = os.path.splitext(file_path)[1].lower()
            is_video = ext in ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']
            is_audio = ext in ['.mp3', '.m4a', '.flac', '.wav', '.ogg']
            is_image = ext in ['.jpg', '.jpeg', '.png', '.webp']
            
            try:
                # Upload to dump chat first
                if is_video:
                    uploaded_file = await client.send_video(
                        chat_id=DUMP_CHAT_ID,
                        video=file_path,
                        caption=caption,
                        progress=upload_progress,
                        file_name=filename,
                        supports_streaming=True
                    )
                elif is_audio:
                    uploaded_file = await client.send_audio(
                        chat_id=DUMP_CHAT_ID,
                        audio=file_path,
                        caption=caption,
                        progress=upload_progress,
                        file_name=filename
                    )
                elif is_image:
                    uploaded_file = await client.send_photo(
                        chat_id=DUMP_CHAT_ID,
                        photo=file_path,
                        caption=caption,
                        progress=upload_progress
                    )
                else:
                    uploaded_file = await client.send_document(
                        chat_id=DUMP_CHAT_ID,
                        document=file_path,
                        caption=caption,
                        progress=upload_progress,
                        file_name=filename
                    )
                
                # Forward to the user
                await client.forward_messages(
                    chat_id=message.chat.id,
                    from_chat_id=DUMP_CHAT_ID,
                    message_ids=uploaded_file.id
                )
                
                # Final success message
                await status_message.edit_text(
                    f"✅ **ᴜᴘʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!**\n\n"
                    f"📚 **ғɪʟᴇ:** {filename}\n"
                    f"💾 **sɪᴢᴇ:** {format_size(file_size)}\n\n"
                    f"👤 {message.from_user.mention}"
                )
            except Exception as e:
                logger.error(f"Upload error: {e}")
                await message.reply_text(f"❌ Upload failed: {str(e)[:100]}...")
                await status_message.edit_text("❌ Upload failed. Please try again later.")
    except Exception as e:
        logger.error(f"Error in handle_upload: {e}")
        await status_message.edit_text(f"❌ An error occurred: {str(e)[:100]}...")
    finally:
        # Clean up the downloaded file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.error(f"Error removing file {file_path}: {e}")

# Simple web interface to keep the bot alive on hosted platforms
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return render_template('index.html', title="Terabox Downloader Bot")

def run_web_server():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# Create a simple index.html template in the templates folder
os.makedirs('templates', exist_ok=True)
with open('templates/index.html', 'w') as f:
    f.write('''
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <style>
        body {
            font-family: 'Arial', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #1e3c72, #2a5298);
            color: white;
            text-align: center;
        }
        .container {
            padding: 2rem;
            border-radius: 10px;
            background-color: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
            max-width: 600px;
        }
        h1 {
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }
        p {
            font-size: 1.2rem;
            margin-bottom: 2rem;
        }
        .status {
            padding: 0.5rem 1rem;
            background-color: #4CAF50;
            border-radius: 5px;
            display: inline-block;
        }
        a {
            color: #4CAF50;
            text-decoration: none;
            font-weight: bold;
        }
        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Terabox Downloader Bot</h1>
        <p>This server keeps the Telegram bot running. Go to Telegram and search for your bot to use it.</p>
        <div class="status">Bot is Running</div>
        <p style="margin-top: 2rem;">Made with ❤️ by <a href="https://t.me/rtx5069" target="_blank">RTX</a></p>
    </div>
</body>
</html>
    ''')

async def main():
    try:
        # Start the web server in a separate thread
        web_server = Thread(target=run_web_server)
        web_server.daemon = True
        web_server.start()
        
        # Start the Telegram clients
        await app.start()
        
        if user:
            try:
                await user.start()
                logger.info("User client started successfully.")
            except Exception as e:
                logger.error(f"Failed to start user client: {e}")
                global SPLIT_SIZE
                SPLIT_SIZE = 2093796556  # Revert to default 2GB limit
        
        logger.info("Bot is running!")
        
        # Keep the main thread alive
        await asyncio.Event().wait()
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        # Properly close clients
        await app.stop()
        if user:
            await user.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Stopping the bot...")
        loop.run_until_complete(app.stop())
        if user:
            loop.run_until_complete(user.stop())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        loop.close()
