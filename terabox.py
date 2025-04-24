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

# Get admin IDs from environment variables
ADMIN_IDS = os.environ.get('ADMIN_IDS', '')
if len(ADMIN_IDS) == 0:
    logging.warning("ADMIN_IDS variable is missing! Only bot owner will have admin privileges")
    ADMIN_IDS = []
else:
    try:
        ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS.split(',')]
    except Exception as e:
        logging.error(f"Error parsing ADMIN_IDS: {e}")
        ADMIN_IDS = []

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

# Track pending requests
pending_requests = {}

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

async def is_admin(user_id):
    """Check if a user is an admin"""
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

def format_eta(seconds):
    """Format ETA in a human-readable format, handling invalid values"""
    if not seconds or seconds < 0 or seconds > 86400 * 365:  # Cap at 1 year
        return "calculating..."
    
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 0:
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    elif minutes > 0:
        return f"{int(minutes)}m {int(seconds)}s"
    else:
        return f"{int(seconds)}s"

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
        
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/dailydiskwala")
    developer_button = InlineKeyboardButton("Backup", url="https://t.me/terao2")
    repo69 = InlineKeyboardButton("Requested videos", url="https://t.me/dailydiskwala")
    request_button = InlineKeyboardButton("ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏ 🎬", callback_data="request_video")
    
    user_mention = message.from_user.mention
    reply_markup = InlineKeyboardMarkup([
        [join_button, developer_button], 
        [repo69],
        [request_button]
    ])
    
    # Check if user is admin and add admin commands button
    if await is_admin(message.from_user.id):
        admin_button = InlineKeyboardButton("ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs 🛠️", callback_data="admin_commands")
        reply_markup = InlineKeyboardMarkup([
            [join_button, developer_button], 
            [repo69],
            [request_button],
            [admin_button]
        ])
    
    final_msg = f"ᴡᴇʟᴄᴏᴍᴇ, {user_mention}.\n\n🌟 ɪ ᴀᴍ ᴀ ᴛᴇʀᴀʙᴏx ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ. sᴇɴᴅ ᴍᴇ ᴀɴʏ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ ɪ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴡɪᴛʜɪɴ ғᴇᴡ sᴇᴄᴏɴᴅs ᴀɴᴅ sᴇɴᴅ ɪᴛ ᴛᴏ ʏᴏᴜ ✨."
    final_msg += "\n\n📸 ʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏs ʙʏ sᴇɴᴅɪɴɢ sᴄʀᴇᴇɴsʜᴏᴛs!"
    
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

@app.on_message(filters.command("admin"))
async def admin_commands(client: Client, message: Message):
    """Display admin commands"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use admin commands.")
        return
    
    admin_text = (
        "**📋 ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs:**\n\n"
        "• `/pending` - View pending video requests\n"
        "• `/notify [user_id] [message]` - Send notification to a user\n"
        "• `/broadcast [message]` - Send message to all users who requested videos\n"
        "• `/stats` - View bot statistics"
    )
    await message.reply_text(admin_text)

@app.on_message(filters.command("pending"))
async def pending_requests_command(client: Client, message: Message):
    """Show pending video requests to admins"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    if not pending_requests:
        await message.reply_text("🔍 No pending video requests found.")
        return
    
    pending_text = "**📋 ᴘᴇɴᴅɪɴɢ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛs:**\n\n"
    
    for request_id, request_data in pending_requests.items():
        pending_text += (
            f"**ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
            f"**ᴜsᴇʀ:** {request_data['user_mention']} (`{request_data['user_id']}`)\n"
            f"**ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {request_data['description']}\n"
            f"**ᴛɪᴍᴇ:** {request_data['time']}\n\n"
        )
    
    # Add instructions for approval/rejection
    pending_text += (
        "📌 **ᴛᴏ ᴀᴘᴘʀᴏᴠᴇ/ʀᴇᴊᴇᴄᴛ:**\n"
        "• Reply to this message with: `/approve [request_id] [optional_message]`\n"
        "• Reply to this message with: `/reject [request_id] [reason]`"
    )
    
    await message.reply_text(pending_text)

@app.on_message(filters.command("approve"))
async def approve_request(client: Client, message: Message):
    """Approve a video request"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    command_parts = message.text.split(' ', 2)
    if len(command_parts) < 2:
        await message.reply_text("⚠️ Please provide a request ID to approve.\nFormat: `/approve [request_id] [optional_message]`")
        return
    
    request_id = command_parts[1]
    approval_message = command_parts[2] if len(command_parts) > 2 else "Your video request has been approved! We'll process it soon."
    
    if request_id not in pending_requests:
        await message.reply_text(f"⚠️ Request ID `{request_id}` not found.")
        return
    
    request_data = pending_requests[request_id]
    user_id = request_data['user_id']
    
    try:
        # Send approval notification to user
        await client.send_message(
            chat_id=user_id,
            text=f"✅ **ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ᴀᴘᴘʀᴏᴠᴇᴅ!**\n\n"
                 f"🎬 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {request_data['description']}\n\n"
                 f"📝 **ᴍᴇssᴀɢᴇ:** {approval_message}"
        )
        
        # Send confirmation to admin
        await message.reply_text(f"✅ Request `{request_id}` approved and user has been notified.")
        
        # Keep the request in pending_requests but mark it as approved
        pending_requests[request_id]['status'] = 'approved'
        
    except Exception as e:
        logger.error(f"Error sending approval notification: {e}")
        await message.reply_text(f"⚠️ Failed to send notification to user: {str(e)[:100]}...")

@app.on_message(filters.command("reject"))
async def reject_request(client: Client, message: Message):
    """Reject a video request"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    command_parts = message.text.split(' ', 2)
    if len(command_parts) < 3:
        await message.reply_text("⚠️ Please provide a request ID and reason.\nFormat: `/reject [request_id] [reason]`")
        return
    
    request_id = command_parts[1]
    rejection_reason = command_parts[2]
    
    if request_id not in pending_requests:
        await message.reply_text(f"⚠️ Request ID `{request_id}` not found.")
        return
    
    request_data = pending_requests[request_id]
    user_id = request_data['user_id']
    
    try:
        # Send rejection notification to user
        await client.send_message(
            chat_id=user_id,
            text=f"❌ **ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ʀᴇᴊᴇᴄᴛᴇᴅ**\n\n"
                 f"🎬 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {request_data['description']}\n\n"
                 f"📝 **ʀᴇᴀsᴏɴ:** {rejection_reason}"
        )
        
        # Send confirmation to admin
        await message.reply_text(f"❌ Request `{request_id}` rejected and user has been notified.")
        
        # Remove the request from pending_requests
        del pending_requests[request_id]
        
    except Exception as e:
        logger.error(f"Error sending rejection notification: {e}")
        await message.reply_text(f"⚠️ Failed to send notification to user: {str(e)[:100]}...")

@app.on_message(filters.command("notify"))
async def notify_user(client: Client, message: Message):
    """Send notification to a user"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    command_parts = message.text.split(' ', 2)
    if len(command_parts) < 3:
        await message.reply_text("⚠️ Please provide a user ID and message.\nFormat: `/notify [user_id] [message]`")
        return
    
    try:
        user_id = int(command_parts[1])
        notification_message = command_parts[2]
        
        # Try to send the notification
        await client.send_message(
            chat_id=user_id,
            text=f"📢 **ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴ ғʀᴏᴍ ᴀᴅᴍɪɴ**\n\n{notification_message}"
        )
        
        await message.reply_text(f"✅ Notification sent to user `{user_id}`.")
    except ValueError:
        await message.reply_text("⚠️ Invalid user ID. Please provide a valid numeric user ID.")
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        await message.reply_text(f"⚠️ Failed to send notification: {str(e)[:100]}...")

@app.on_message(filters.command("file_ready"))
async def file_ready_notification(client: Client, message: Message):
    """Notify user that their requested file is ready"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    command_parts = message.text.split(' ', 2)
    if len(command_parts) < 2:
        await message.reply_text("⚠️ Please provide a user ID.\nFormat: `/file_ready [user_id] [optional_message]`")
        return
    
    try:
        user_id = int(command_parts[1])
        custom_message = ""
        if len(command_parts) > 2:
            custom_message = command_parts[2]
        
        # Check if there's a forwarded message (the actual file)
        file_message = None
        if message.reply_to_message:
            file_message = message.reply_to_message
        
        # Prepare notification message
        notification = (
            f"🎉 **ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛᴇᴅ ғɪʟᴇ ɪs ʀᴇᴀᴅʏ!**\n\n"
        )
        
        if custom_message:
            notification += f"📝 **ᴍᴇssᴀɢᴇ:** {custom_message}\n\n"
        
        notification += "📥 ᴄʜᴇᴄᴋ ʙᴇʟᴏᴡ ғᴏʀ ʏᴏᴜʀ ғɪʟᴇ. ᴛʜᴀɴᴋ ʏᴏᴜ ғᴏʀ ᴜsɪɴɢ ᴏᴜʀ sᴇʀᴠɪᴄᴇ!"
        
        # Send notification message
        await client.send_message(
            chat_id=user_id,
            text=notification
        )
        
        # Forward the file if available
        if file_message:
            await file_message.forward(user_id)
        
        await message.reply_text(f"✅ File ready notification sent to user `{user_id}`.")
        
    except ValueError:
        await message.reply_text("⚠️ Invalid user ID. Please provide a valid numeric user ID.")
    except Exception as e:
        logger.error(f"Error sending file ready notification: {e}")
        await message.reply_text(f"⚠️ Failed to send notification: {str(e)[:100]}...")

@app.on_callback_query()
async def handle_callback(client, callback_query):
    user_id = callback_query.from_user.id
    
    # Check for force subscription
    is_member = await is_user_member(client, user_id)
    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
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
    
    elif callback_query.data == "admin_commands":
        # Check if user is admin
        if await is_admin(user_id):
            admin_text = (
                "**📋 ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs:**\n\n"
                "• `/pending` - View pending video requests\n"
                "• `/approve [request_id] [message]` - Approve a request\n"
                "• `/reject [request_id] [reason]` - Reject a request\n"
                "• `/notify [user_id] [message]` - Send notification to a user\n"
                "• `/file_ready [user_id] [message]` - Notify user their file is ready\n"
                "• `/stats` - View bot statistics"
            )
            await callback_query.message.reply_text(admin_text)
            await callback_query.answer("Admin commands displayed")
        else:
            await callback_query.answer("You are not authorized to access admin commands", show_alert=True)

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
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Generate a unique request ID
        request_id = f"REQ{len(pending_requests) + 1:03d}"
        
       # Store request details
        pending_requests[request_id] = {
            'user_id': user_id,
            'user_mention': message.from_user.mention,
            'photo_id': photo_id,
            'description': description,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'pending'
        }
        
        # Forward the request to admin channel
        try:
            # Send the screenshot with description
            await client.send_photo(
                chat_id=REQUEST_CHANNEL_ID,
                photo=photo_id,
                caption=f"📝 **ɴᴇᴡ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ**\n\n"
                       f"**ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
                       f"**ᴜsᴇʀ:** {message.from_user.mention} (`{user_id}`)\n"
                       f"**ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {description}\n\n"
                       f"**ᴄᴏᴍᴍᴀɴᴅs:**\n"
                       f"`/approve {request_id} [message]`\n"
                       f"`/reject {request_id} [reason]`"
            )
            
            # Confirm to user
            await message.reply_text(
                "✅ **ʏᴏᴜʀ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜʙᴍɪᴛᴛᴇᴅ!**\n\n"
                f"🆔 **ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
                "⏳ Please be patient while admins review your request."
            )
            
        except Exception as e:
            logger.error(f"Error processing video request: {e}")
            await message.reply_text("❌ Error submitting your request. Please try again later.")
        
        return
    
    # Handle TeraBox links
    if is_valid_url(message.text):
        # Check for force subscription
        is_member = await is_user_member(client, user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Send initial status message
        status_message = await message.reply_text("🔍 Analyzing your TeraBox link...")
        
        try:
            # Get URL components
            terabox_url = message.text.strip()
            
            # Begin download process
            await update_status_message(status_message, "📥 Starting download from Sever.....")
            
            # Use aria2 to download the file
            if aria2:
                try:
                    # Add the download to aria2
                    download = aria2.add_uris([terabox_url])
                    
                    # Track download progress
                    last_progress = -1
                    last_update_time = time.time()
                    
                    while download.is_active or download.is_waiting:
                        download.update()
                        
                        # Calculate progress
                        try:
                            total_length = int(download.total_length)
                            completed_length = int(download.completed_length)
                            
                            if total_length > 0:
                                progress = (completed_length / total_length) * 100
                                download_speed = int(download.download_speed)
                                
                                # Only update message if progress changes significantly or time passed
                                current_time = time.time()
                                if (abs(progress - last_progress) > 1 or current_time - last_update_time > 5):
                                    last_progress = progress
                                    last_update_time = current_time
                                    
                                    # Calculate ETA
                                    eta = (total_length - completed_length) / download_speed if download_speed > 0 else 0
                                    
                                    # Format progress message
                                    progress_bar = generate_progress_bar(progress)
                                    progress_text = (
                                        f"📥 **ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**\n\n"
                                        f"**ғɪʟᴇ ɴᴀᴍᴇ:** `{download.name}`\n"
                                        f"**ᴘʀᴏɢʀᴇss:** {progress_bar} `{progress:.1f}%`\n"
                                        f"**sᴘᴇᴇᴅ:** `{format_size(download_speed)}/s`\n"
                                        f"**ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ:** `{format_size(completed_length)}`/`{format_size(total_length)}`\n"
                                        f"**ᴇᴛᴀ:** `{format_eta(eta)}`"
                                    )
                                    await update_status_message(status_message, progress_text)
                        except Exception as e:
                            logger.error(f"Error updating progress: {e}")
                        
                        await asyncio.sleep(1)
                    
                    # Check if download completed successfully
                    download.update()
                    if download.is_complete:
                        await update_status_message(status_message, f"✅ Download completed: `{download.name}`\n\nPreparing to upload...")
                        
                        # Get the file path
                        file_path = os.path.join(download.dir, download.name)
                        
                        # Get file size
                        file_size = os.path.getsize(file_path)
                        
                        # Check if file exists
                        if not os.path.exists(file_path):
                            await update_status_message(status_message, "❌ File not found after download. Please try again.")
                            return
                        
                        # Upload the file
                        if file_size > SPLIT_SIZE:
                            await update_status_message(status_message, f"⚠️ File size {format_size(file_size)} exceeds limit. Splitting and uploading in parts...")
                            
                            # Upload as multiple files
                            parts = math.ceil(file_size / SPLIT_SIZE)
                            for i in range(parts):
                                start_byte = i * SPLIT_SIZE
                                end_byte = min((i + 1) * SPLIT_SIZE, file_size)
                                
                                part_name = f"{download.name}.part{i+1:03d}"
                                
                                # Update status
                                await update_status_message(status_message, f"📤 Uploading part {i+1}/{parts}: {part_name}...")
                                
                                # Create a caption for the file
                                caption = f"📁 **ғɪʟᴇ ɴᴀᴍᴇ:** `{download.name}`\n**ᴘᴀʀᴛ:** {i+1}/{parts}"
                                
                                # Upload using the most appropriate method
                                try:
                                    if user:
                                        # Use user client for larger files
                                        await user.send_document(
                                            chat_id=DUMP_CHAT_ID,
                                            document=file_path,
                                            caption=caption,
                                            file_name=part_name,
                                            progress=lambda c, t: asyncio.get_event_loop().create_task(
                                                update_status_message(status_message, 
                                                f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ ᴘᴀʀᴛ {i+1}/{parts}**\n\n"
                                                f"**ᴘʀᴏɢʀᴇss:** {generate_progress_bar((c/t)*100)} `{(c/t)*100:.1f}%`\n"
                                                f"**ᴜᴘʟᴏᴀᴅᴇᴅ:** `{format_size(c)}`/`{format_size(t)}`")
                                            )
                                        )
                                    else:
                                        # Use bot client
                                        await client.send_document(
                                            chat_id=DUMP_CHAT_ID,
                                            document=file_path,
                                            caption=caption,
                                            file_name=part_name,
                                            progress=lambda c, t: asyncio.get_event_loop().create_task(
                                                update_status_message(status_message, 
                                                f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ ᴘᴀʀᴛ {i+1}/{parts}**\n\n"
                                                f"**ᴘʀᴏɢʀᴇss:** {generate_progress_bar((c/t)*100)} `{(c/t)*100:.1f}%`\n"
                                                f"**ᴜᴘʟᴏᴀᴅᴇᴅ:** `{format_size(c)}`/`{format_size(t)}`")
                                            )
                                        )
                                except Exception as e:
                                    logger.error(f"Error uploading file part: {e}")
                                    await update_status_message(status_message, f"❌ Error uploading file part {i+1}: {str(e)[:100]}...")
                                    continue
                                
                                # Forward the file to the user
                                try:
                                    # Get the last message from dump chat
                                    async for msg in client.get_chat_history(DUMP_CHAT_ID, limit=1):
                                        await msg.forward(message.chat.id)
                                        break
                                except Exception as e:
                                    logger.error(f"Error forwarding file part: {e}")
                                    await update_status_message(status_message, f"❌ Error forwarding file part {i+1}. Please check @{DUMP_CHAT_ID} for your files.")
                        else:
                            # Upload as single file
                            await update_status_message(status_message, f"📤 Uploading `{download.name}`...")
                            
                            # Create a caption for the file
                            caption = f"📁 **ғɪʟᴇ ɴᴀᴍᴇ:** `{download.name}`"
                            
                            # Upload using the most appropriate method
                            try:
                                if user and file_size > 50 * 1024 * 1024:  # Use user client for files > 50MB
                                    await user.send_document(
                                        chat_id=DUMP_CHAT_ID,
                                        document=file_path,
                                        caption=caption,
                                        progress=lambda c, t: asyncio.get_event_loop().create_task(
                                            update_status_message(status_message, 
                                            f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ**\n\n"
                                            f"**ᴘʀᴏɢʀᴇss:** {generate_progress_bar((c/t)*100)} `{(c/t)*100:.1f}%`\n"
                                            f"**ᴜᴘʟᴏᴀᴅᴇᴅ:** `{format_size(c)}`/`{format_size(t)}`")
                                        )
                                    )
                                else:
                                    # Use bot client
                                    await client.send_document(
                                        chat_id=DUMP_CHAT_ID,
                                        document=file_path,
                                        caption=caption,
                                        progress=lambda c, t: asyncio.get_event_loop().create_task(
                                            update_status_message(status_message, 
                                            f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ**\n\n"
                                            f"**ᴘʀᴏɢʀᴇss:** {generate_progress_bar((c/t)*100)} `{(c/t)*100:.1f}%`\n"
                                            f"**ᴜᴘʟᴏᴀᴅᴇᴅ:** `{format_size(c)}`/`{format_size(t)}`")
                                        )
                                    )
                            except Exception as e:
                                logger.error(f"Error uploading file: {e}")
                                await update_status_message(status_message, f"❌ Error uploading file: {str(e)[:100]}...")
                                return
                            
                            # Forward the file to the user
                            try:
                                # Get the last message from dump chat
                                async for msg in client.get_chat_history(DUMP_CHAT_ID, limit=1):
                                    await msg.forward(message.chat.id)
                                    break
                            except Exception as e:
                                logger.error(f"Error forwarding file: {e}")
                                await update_status_message(status_message, f"❌ Error forwarding file. Please check @{DUMP_CHAT_ID} for your file.")
                        
                        # Clean up
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            logger.error(f"Error removing file: {e}")
                        
                        # Final message
                        await update_status_message(status_message, "✅ **ᴘʀᴏᴄᴇss ᴄᴏᴍᴘʟᴇᴛᴇᴅ!**")
                        
                    else:
                        await update_status_message(status_message, f"❌ Download failed: {download.error_message}")
                        
                except Exception as e:
                    logger.error(f"Error in download process: {e}")
                    await update_status_message(status_message, f"❌ Error processing download: {str(e)[:100]}...")
            else:
                await update_status_message(status_message, "❌ aria2 service is not available. Please try again later.")
                
        except Exception as e:
            logger.error(f"Error processing TeraBox link: {e}")
            await update_status_message(status_message, f"❌ Error processing your link: {str(e)[:100]}...")

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    """Display bot statistics"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    # Calculate statistics
    total_pending = len([r for r in pending_requests.values() if r['status'] == 'pending'])
    total_approved = len([r for r in pending_requests.values() if r['status'] == 'approved'])
    
    # Get aria2 stats if available
    aria2_stats = "N/A"
    if aria2:
        try:
            downloads = aria2.get_downloads()
            active_downloads = len([d for d in downloads if d.is_active])
            waiting_downloads = len([d for d in downloads if d.is_waiting])
            stopped_downloads = len([d for d in downloads if d.is_paused])
            completed_downloads = len([d for d in downloads if d.is_complete])
            
            aria2_stats = (
                f"**ᴀᴄᴛɪᴠᴇ:** {active_downloads}\n"
                f"**ᴡᴀɪᴛɪɴɢ:** {waiting_downloads}\n"
                f"**sᴛᴏᴘᴘᴇᴅ:** {stopped_downloads}\n"
                f"**ᴄᴏᴍᴘʟᴇᴛᴇᴅ:** {completed_downloads}"
            )
        except Exception as e:
            logger.error(f"Error getting aria2 stats: {e}")
            aria2_stats = f"Error: {str(e)[:50]}..."
    
    stats_text = (
        "📊 **ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs**\n\n"
        f"**ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs:** {total_pending}\n"
        f"**ᴀᴘᴘʀᴏᴠᴇᴅ ʀᴇǫᴜᴇsᴛs:** {total_approved}\n\n"
        f"**ᴀʀɪᴀ2 sᴛᴀᴛᴜs:**\n{aria2_stats}"
    )
    
    await message.reply_text(stats_text)

@app.on_message(filters.command("broadcast"))
async def broadcast_command(client: Client, message: Message):
    """Broadcast a message to all users who have made video requests"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    # Check for broadcast message
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await message.reply_text("⚠️ Please provide a message to broadcast.\nFormat: `/broadcast [message]`")
        return
    
    broadcast_message = command_parts[1]
    
    # Get unique user IDs from pending requests
    user_ids = set(request_data['user_id'] for request_data in pending_requests.values())
    
    if not user_ids:
        await message.reply_text("⚠️ No users found to broadcast to.")
        return
    
    # Start broadcasting
    success_count = 0
    fail_count = 0
    
    progress_message = await message.reply_text("🔄 Broadcasting message...")
    
    for user_id in user_ids:
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"📢 **ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ ғʀᴏᴍ ᴀᴅᴍɪɴ**\n\n{broadcast_message}"
            )
            success_count += 1
        except Exception as e:
            logger.error(f"Error broadcasting to user {user_id}: {e}")
            fail_count += 1
        
        # Update progress
        await progress_message.edit_text(
            f"🔄 **ʙʀᴏᴀᴅᴄᴀsᴛɪɴɢ ɪɴ ᴘʀᴏɢʀᴇss**\n\n"
            f"**sᴜᴄᴄᴇss:** {success_count}\n"
            f"**ғᴀɪʟᴇᴅ:** {fail_count}\n"
            f"**ᴛᴏᴛᴀʟ:** {len(user_ids)}"
        )
    
    # Final report
    await progress_message.edit_text(
        f"✅ **ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ**\n\n"
        f"**sᴜᴄᴄᴇss:** {success_count}\n"
        f"**ғᴀɪʟᴇᴅ:** {fail_count}\n"
        f"**ᴛᴏᴛᴀʟ:** {len(user_ids)}"
    )

# Flask web server for keeping the bot alive
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app_flask.run(host='0.0.0.0', port=8080)

def main():
    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start the user client if available
    if user:
        user.start()
        logger.info("User client started")
    
    # Start the bot
    logger.info("Starting bot")
    app.run()
    
    # Stop the user client when bot stops
    if user:
        user.stop()

if __name__ == "__main__":
    main()
