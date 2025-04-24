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
if len(USER_SESSION_STRING) == 0:
    logging.info("USER_SESSION_STRING variable is missing! Bot will split Files in 2Gb...")
    USER_SESSION_STRING = None

app = Client("jetbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

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

# Track users in request mode
users_in_request_mode = {}

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
    
    # Regular URL processing
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

    encoded_url = urllib.parse.quote(url)
    final_url = f"https://teradlrobot.cheemsbackup.workers.dev/?url={encoded_url}"

    download = aria2.add_uris([final_url])
    status_message = await message.reply_text("sᴇɴᴅɪɴɢ ʏᴏᴜ ᴛʜᴇ ᴍᴇᴅɪᴀ...🤤")

    start_time = datetime.now()

    while not download.is_complete:
        await asyncio.sleep(15)
        download.update()
        progress = download.progress

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
        
        while True:
            try:
                await update_status_message(status_message, status_text)
                break
            except FloodWait as e:
                logger.error(f"Flood wait detected! Sleeping for {e.value} seconds")
                await asyncio.sleep(e.value)

    file_path = download.files[0].path
    caption = (
        f"✨ {download.name}\n"
        f"👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>\n"
        f"📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}\n\n"
        "[ᴘᴏᴡᴇʀᴇᴅ ʙʏ ᴊᴇᴛ-ᴍɪʀʀᴏʀ ❤️🚀](https://t.me/JetMirror)"
    )

    last_update_time = time.time()
    UPDATE_INTERVAL = 15

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
            f"**{download.name}**\n\n"
            f"{progress_bar} `{progress:.1f}%`\n\n"
            f"⚡️ **sᴘᴇᴇᴅ:** {format_size(current / elapsed_time.seconds if elapsed_time.seconds > 0 else 0)}/s\n"
            f"💾 **sɪᴢᴇ:** {format_size(current)}/{format_size(total)}\n"
            f"⏰ **ᴇʟᴀᴘsᴇᴅ:** {elapsed_minutes}m {elapsed_seconds}s\n\n"
            f"👤 {message.from_user.mention}"
        )
        await update_status(status_message, status_text)

    def generate_progress_bar(percentage, length=10):
        # Modern, clean progress bar with emojis
        filled_length = int(length * percentage // 100)
        empty_length = length - filled_length
        
        # Unicode blocks for a cleaner look
        bar = '█' * filled_length + '░' * empty_length
        return f"`{bar}`"

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
                cmd = [
                    'xtra', '-y', '-ss', str(i * duration_per_part),
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
            # Clean splitting notification
            progress_bar = generate_progress_bar(0)  # 0% progress to start
            
            await update_status(
                status_message,
                f"✂️ **sᴘʟɪᴛᴛɪɴɢ ᴠɪᴅᴇᴏ**\n\n"
                f"**{download.name}** ({format_size(file_size)})\n\n"
                f"{progress_bar} `0.0%`\n\n"
                f"🔄 **ᴘʀᴇᴘᴀʀɪɴɢ...**"
            )
            
            split_files = await split_video_with_ffmpeg(
                file_path,
                os.path.splitext(file_path)[0],
                SPLIT_SIZE
            )
            
            try:
                for i, part in enumerate(split_files):
                    part_caption = f"{caption}\n\nPart {i+1}/{len(split_files)}"
                    
                    # Clean part upload notification
                    progress_bar = generate_progress_bar(0)  # 0% progress to start
                    
                    await update_status(
                        status_message,
                        f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ ᴘᴀʀᴛ {i+1}/{len(split_files)}**\n\n"
                        f"**{os.path.basename(part)}**\n\n"
                        f"{progress_bar} `0.0%`\n\n"
                        f"🔄 **ᴘʀᴇᴘᴀʀɪɴɢ...**"
                    )
                    
                    if USER_SESSION_STRING:
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
                    os.remove(part)
            finally:
                for part in split_files:
                    try: os.remove(part)
                    except: pass
        else:
            # Clean upload notification
            progress_bar = generate_progress_bar(0)  # 0% progress to start
            
            await update_status(
                status_message,
                f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ**\n\n"
                f"**{download.name}**\n\n"
                f"{progress_bar} `0.0%`\n\n"
                f"💾 **sɪᴢᴇ:** {format_size(file_size)}\n"
                f"🔄 **ᴘʀᴇᴘᴀʀɪɴɢ...**"
            )
            
            if USER_SESSION_STRING:
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
        if os.path.exists(file_path):
            os.remove(file_path)

    start_time = datetime.now()
    await handle_upload()

    try:
        await status_message.delete()
        await message.delete()
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

# Command to check user's requests
@app.on_message(filters.command("myrequests"))
async def my_requests_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.from_user:
        return

    # Check for force subscription
    is_member = await is_user_member(client, user_id)
    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
        reply_markup = InlineKeyboardMarkup([[join_button]])
        await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
        return
    
    await message.reply_text(
        "🔍 ᴛᴏ ᴄʜᴇᴄᴋ ᴛʜᴇ sᴛᴀᴛᴜs ᴏғ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛs, ᴘʟᴇᴀsᴇ ᴠɪsɪᴛ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ:\n"
        "https://t.me/jetmirror\n\n"
        "ᴡᴇ ᴘᴏsᴛ ᴜᴘᴅᴀᴛᴇs ᴏɴ ᴘʀᴏᴄᴇssᴇᴅ ʀᴇǫᴜᴇsᴛs ᴛʜᴇʀᴇ."
    )

# Command to request a video
@app.on_message(filters.command("request"))
async def request_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.from_user:
        return

    # Check for force subscription
    is_member = await is_user_member(client, user_id)
    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
        reply_markup = InlineKeyboardMarkup([[join_button]])
        await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
        return
    
    # Set user in request mode
    users_in_request_mode[user_id] = {"state": "waiting_for_image"}
    
    # Send instructions
    cancel_button = InlineKeyboardButton("ᴄᴀɴᴄᴇʟ ❌", callback_data="cancel_request")
    reply_markup = InlineKeyboardMarkup([[cancel_button]])
    
    await message.reply_text(
        "📸 ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ sᴄʀᴇᴇɴsʜᴏᴛ ᴏʀ ɪᴍᴀɢᴇ ᴏғ ᴛʜᴇ ᴠɪᴅᴇᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʀᴇǫᴜᴇsᴛ.",
        reply_markup=reply_markup
    )

# Admin command to list pending requests
@app.on_message(filters.command("pendingrequests") & filters.user([int(os.environ.get('ADMIN_ID', 0))]))
async def pending_requests(client: Client, message: Message):
    await message.reply_text("📊 ᴄʜᴇᴄᴋɪɴɢ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs ɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ...")
    
    try:
        # You can implement a more sophisticated pending requests system here
        # For now, just redirect admin to the requests channel
        await message.reply_text(f"ᴘʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ᴛʜᴇ ʀᴇǫᴜᴇsᴛs ᴄʜᴀɴɴᴇʟ ғᴏʀ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs.")
    except Exception as e:
        logger.error(f"Error retrieving pending requests: {e}")
        await message.reply_text("❌ ᴇʀʀᴏʀ ʀᴇᴛʀɪᴇᴠɪɴɢ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs.")

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
