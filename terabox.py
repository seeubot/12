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

# Add function to fetch TeraBox link details
async def get_terabox_direct_link(url):
    """Fetch direct download link and file details from TeraBox API"""
    try:
        api_url = f"https://teraboxapi-phi.vercel.app/api?url={url}"
        response = requests.get(api_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check if API returned success
            if data.get('success', False):
                return {
                    'direct_link': data.get('direct_link', ''),
                    'filename': data.get('filename', ''),
                    'size': data.get('size', 0),
                    'success': True
                }
        
        # Return failure if any condition fails
        return {'success': False, 'error': 'Failed to fetch link details'}
    except Exception as e:
        logger.error(f"Error fetching TeraBox link details: {e}")
        return {'success': False, 'error': str(e)}

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
        request_id = f"REQ{int(time.time())}"
        
        # Store request in pending_requests
        pending_requests[request_id] = {
            'user_id': user_id,
            'user_mention': message.from_user.mention,
            'photo_id': photo_id,
            'description': description,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'pending'
        }
        
        # Send confirmation to user
        await message.reply_text(
            f"✅ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜʙᴍɪᴛᴛᴇᴅ!\n\n"
            f"🆔 ʀᴇǫᴜᴇsᴛ ɪᴅ: `{request_id}`\n"
            f"📝 ᴅᴇsᴄʀɪᴘᴛɪᴏɴ: {description}\n\n"
            f"ᴏᴜʀ ᴛᴇᴀᴍ ᴡɪʟʟ ʀᴇᴠɪᴇᴡ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ sʜᴏʀᴛʟʏ."
        )
        
        # Forward request to admin channel
        try:
            # First send the photo
            photo_message = await client.send_photo(
                chat_id=REQUEST_CHANNEL_ID,
                photo=photo_id,
                caption=f"📢 **ɴᴇᴡ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ**\n\n"
                       f"🆔 **ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
                       f"👤 **ᴜsᴇʀ:** {message.from_user.mention} (`{user_id}`)\n"
                       f"📝 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {description}\n"
                       f"⏰ **ᴛɪᴍᴇ:** {pending_requests[request_id]['time']}"
            )
            
            # Add action buttons for admins
            approve_button = InlineKeyboardButton(
                "✅ ᴀᴘᴘʀᴏᴠᴇ", 
                callback_data=f"approve_{request_id}"
            )
            reject_button = InlineKeyboardButton(
                "❌ ʀᴇᴊᴇᴄᴛ", 
                callback_data=f"reject_{request_id}"
            )
            reply_markup = InlineKeyboardMarkup([[approve_button, reject_button]])
            
            # Add buttons to the photo message
            await photo_message.edit_reply_markup(reply_markup)
            
        except Exception as e:
            logger.error(f"Failed to forward request to admin channel: {e}")
        
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
        status_message = await message.reply_text("🔍 ᴘʀᴏᴄᴇssɪɴɢ ʏᴏᴜʀ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ...")
        
        try:
            # Update status
            await update_status_message(status_message, "⏳ ғᴇᴛᴄʜɪɴɢ ғɪʟᴇ ᴅᴇᴛᴀɪʟs...")
            
            # Get file details from API
            link_info = await get_terabox_direct_link(message.text)
            
            if not link_info.get('success', False):
                await update_status_message(status_message, f"❌ ᴇʀʀᴏʀ: {link_info.get('error', 'Failed to process link')}")
                return
            
            direct_link = link_info.get('direct_link', '')
            filename = link_info.get('filename', 'file')
            file_size = link_info.get('size', 0)
            
            if not direct_link:
                await update_status_message(status_message, "❌ ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ ᴅɪʀᴇᴄᴛ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋ.")
                return
            
            # Size check and warning
            human_size = format_size(file_size)
            if file_size > SPLIT_SIZE:
                await update_status_message(
                    status_message, 
                    f"⚠️ ᴛʜᴇ ғɪʟᴇ sɪᴢᴇ ({human_size}) ᴇxᴄᴇᴇᴅs ᴛᴇʟᴇɢʀᴀᴍ's ʟɪᴍɪᴛ.\n"
                    f"ɪ'ʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴᴅ sᴘʟɪᴛ ɪᴛ ɪɴᴛᴏ sᴍᴀʟʟᴇʀ ᴘᴀʀᴛs."
                )
                await asyncio.sleep(2)  # Give user time to read
            
            # Start download with aria2
            await update_status_message(status_message, f"📥 sᴛᴀʀᴛɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ: {filename}\nsɪᴢᴇ: {human_size}")
            
            try:
                download = aria2.add_uris([direct_link], {"out": filename})
                download_id = download.gid
                
                # Monitor download progress
                while True:
                    download = aria2.get_download(download_id)
                    if not download:
                        await update_status_message(status_message, "❌ ᴅᴏᴡɴʟᴏᴀᴅ ᴡᴀs ᴄᴀɴᴄᴇʟʟᴇᴅ ᴏʀ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ.")
                        return
                    
                    status = download.status
                    if status == 'complete':
                        break
                    elif status == 'error':
                        await update_status_message(status_message, "❌ ᴅᴏᴡɴʟᴏᴀᴅ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ.")
                        return
                    
                    # Calculate progress
                    completed = download.completed_length
                    total = download.total_length
                    
                    if total > 0:
                        percentage = (completed / total) * 100
                        speed = download.download_speed
                        speed_str = format_size(speed) + "/s"
                        eta = (total - completed) / speed if speed > 0 else 0
                        eta_str = format_eta(eta)
                        progress_bar = generate_progress_bar(percentage)
                        
                        status_text = (
                            f"📥 ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ: {filename}\n\n"
                            f"{progress_bar} {percentage:.1f}%\n"
                            f"⚡️ sᴘᴇᴇᴅ: {speed_str}\n"
                            f"⏱️ ᴇᴛᴀ: {eta_str}\n"
                            f"📊 {format_size(completed)}/{format_size(total)}"
                        )
                        
                        global last_update_time
                        current_time = time.time()
                        if current_time - last_update_time >= 3:  # Update every 3 seconds
                            await update_status_message(status_message, status_text)
                            last_update_time = current_time
                    
                    await asyncio.sleep(1)
                
                # Download complete
                download_path = os.path.join(download.dir, download.name)
                
                await update_status_message(status_message, f"✅ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ: {filename}")
                
                # Handle file uploading
                if file_size <= SPLIT_SIZE:
                    # Upload directly if file is small enough
                    await update_status_message(status_message, f"📤 ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ...")
                    
                    # Upload to dump channel first
                    dump_message = await client.send_document(
                        chat_id=DUMP_CHAT_ID,
                        document=download_path,
                        caption=f"📁 **ғɪʟᴇ ɴᴀᴍᴇ:** {filename}\n💾 **sɪᴢᴇ:** {human_size}",
                        progress=None  # We'll handle progress updates manually
                    )
                    
                    # Forward from dump channel to user
                    await dump_message.forward(message.chat.id)
                    
                    # Delete status message
                    try:
                        await status_message.delete()
                    except:
                        pass
                    
                    # Clean up downloaded file
                    try:
                        os.remove(download_path)
                    except Exception as e:
                        logger.error(f"Error deleting file: {e}")
                    
                else:
                    # Split the file if it's too large
                    await update_status_message(status_message, f"✂️ sᴘʟɪᴛᴛɪɴɢ ғɪʟᴇ ɪɴᴛᴏ sᴍᴀʟʟᴇʀ ᴘᴀʀᴛs...")
                    
                    # Create directory for split files
                    split_dir = os.path.join(os.path.dirname(download_path), "splits")
                    os.makedirs(split_dir, exist_ok=True)
                    
                    # Calculate number of parts
                    num_parts = math.ceil(file_size / SPLIT_SIZE)
                    
                   # Replace from line 762-769 (approximate)
if os.name == 'nt':  # Windows
    # Use Python's built-in file operations instead of PowerShell
    split_process = 0  # Initialize as success
    try:
        with open(download_path, 'rb') as f:
            part_num = 0
            while True:
                chunk = f.read(SPLIT_SIZE)
                if not chunk:
                    break
                with open(f"{split_dir}/{filename}.part{part_num}", 'wb') as part_file:
                    part_file.write(chunk)
                part_num += 1
    except Exception as e:
        logger.error(f"Error splitting file: {e}")
        split_process = 1  # Mark as failed
else:  # Linux/Unix
    split_cmd = f'split -b {SPLIT_SIZE} "{download_path}" "{split_dir}/{filename}.part"'
    split_process = os.system(split_cmd)
                    
                    # Upload each part
                    split_files = sorted(os.listdir(split_dir))
                    total_parts = len(split_files)
                    
                    for idx, split_file in enumerate(split_files, 1):
                        split_path = os.path.join(split_dir, split_file)
                        part_caption = f"📁 **ғɪʟᴇ:** {filename} - ᴘᴀʀᴛ {idx}/{total_parts}\n💾 **ᴛᴏᴛᴀʟ sɪᴢᴇ:** {human_size}"
                        
                        await update_status_message(
                            status_message, 
                            f"📤 ᴜᴘʟᴏᴀᴅɪɴɢ ᴘᴀʀᴛ {idx}/{total_parts}..."
                        )
                        
                        # Upload to dump channel first
                        dump_message = await client.send_document(
                            chat_id=DUMP_CHAT_ID,
                            document=split_path,
                            caption=part_caption,
                            progress=None
                        )
                        
                        # Forward from dump channel to user
                        await dump_message.forward(message.chat.id)
                        
                        # Clean up the split file
                        try:
                            os.remove(split_path)
                        except Exception as e:
                            logger.error(f"Error deleting split file: {e}")
                    
                    # Clean up original file
                    try:
                        os.remove(download_path)
                        os.rmdir(split_dir)
                    except Exception as e:
                        logger.error(f"Error cleaning up files: {e}")
                    
                    # Delete status message
                    try:
                        await status_message.delete()
                    except:
                        pass
                    
                    # Send completion message
                    await message.reply_text(
                        f"✅ ᴀʟʟ {total_parts} ᴘᴀʀᴛs ᴏғ {filename} ʜᴀᴠᴇ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ!"
                    )
                
            except Exception as e:
                logger.error(f"Download error: {e}")
                await update_status_message(status_message, f"❌ ᴅᴏᴡɴʟᴏᴀᴅ ᴇʀʀᴏʀ: {str(e)[:100]}...")
        
        except Exception as e:
            logger.error(f"Process error: {e}")
            await update_status_message(status_message, f"❌ ᴘʀᴏᴄᴇssɪɴɢ ᴇʀʀᴏʀ: {str(e)[:100]}...")

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    """Display bot statistics"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    # Calculate statistics
    total_pending = len(pending_requests)
    approved_requests = sum(1 for req in pending_requests.values() if req.get('status') == 'approved')
    
    stats_text = (
        "📊 **ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs**\n\n"
        f"🔄 **ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs:** {total_pending}\n"
        f"✅ **ᴀᴘᴘʀᴏᴠᴇᴅ ʀᴇǫᴜᴇsᴛs:** {approved_requests}\n"
    )
    
    # Add aria2 stats if available
    if aria2:
        try:
            global_stat = aria2.get_global_stat()
            stats_text += (
                f"\n**ᴅᴏᴡɴʟᴏᴀᴅ sᴛᴀᴛs:**\n"
                f"📥 **ᴀᴄᴛɪᴠᴇ ᴅᴏᴡɴʟᴏᴀᴅs:** {global_stat.num_active}\n"
                f"⏸️ **ᴡᴀɪᴛɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅs:** {global_stat.num_waiting}\n"
                f"✅ **ᴄᴏᴍᴘʟᴇᴛᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅs:** {global_stat.num_stopped}\n"
            )
        except Exception as e:
            logger.error(f"Error fetching aria2 stats: {e}")
    
    await message.reply_text(stats_text)

@app.on_message(filters.command("broadcast"))
async def broadcast_command(client: Client, message: Message):
    """Broadcast a message to all users who requested videos"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await message.reply_text("⚠️ Please provide a message to broadcast.\nFormat: `/broadcast [message]`")
        return
    
    broadcast_message = command_parts[1]
    
    # Get unique user IDs from pending requests
    user_ids = set(req['user_id'] for req in pending_requests.values())
    
    if not user_ids:
        await message.reply_text("⚠️ No users found to broadcast to.")
        return
    
    # Send confirmation
    confirm_message = await message.reply_text(
        f"🔄 Broadcasting message to {len(user_ids)} users...\n\n"
        f"**Preview:**\n{broadcast_message[:100]}{'...' if len(broadcast_message) > 100 else ''}"
    )
    
    # Send broadcast
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"📢 **ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ**\n\n{broadcast_message}"
            )
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")
            fail_count += 1
        
        # Update progress every 5 users
        if (success_count + fail_count) % 5 == 0:
            await confirm_message.edit_text(
                f"🔄 Broadcasting: {success_count + fail_count}/{len(user_ids)} users processed...\n"
                f"✅ Success: {success_count}\n"
                f"❌ Failed: {fail_count}"
            )
    
    # Final update
    await confirm_message.edit_text(
        f"✅ Broadcast complete!\n\n"
        f"📊 **Results:**\n"
        f"👥 Total users: {len(user_ids)}\n"
        f"✅ Successfully sent: {success_count}\n"
        f"❌ Failed: {fail_count}"
    )

# Add additional callback handlers for approve/reject from inline buttons
@app.on_callback_query(filters.regex(r'^approve_'))
async def approve_request_callback(client, callback_query):
    """Handle approval via callback button"""
    user_id = callback_query.from_user.id
    
    # Check if user is admin
    if not await is_admin(user_id):
        await callback_query.answer("You are not authorized to perform this action!", show_alert=True)
        return
    
    # Extract request ID from callback data
    request_id = callback_query.data.replace('approve_', '')
    
    if request_id not in pending_requests:
        await callback_query.answer(f"Request ID {request_id} not found!", show_alert=True)
        return
    
    request_data = pending_requests[request_id]
    requester_id = request_data['user_id']
    
    try:
        # Send approval notification to user
        await client.send_message(
            chat_id=requester_id,
            text=f"✅ **ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ᴀᴘᴘʀᴏᴠᴇᴅ!**\n\n"
                 f"🎬 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {request_data['description']}\n\n"
                 f"📝 **ᴍᴇssᴀɢᴇ:** Your request has been approved and we'll process it soon."
        )
        
        # Update message to show approved status
        new_caption = callback_query.message.caption.split("\n\n")[0] + "\n\n✅ **STATUS:** APPROVED"
        await callback_query.message.edit_caption(new_caption)
        
        # Remove buttons
        await callback_query.message.edit_reply_markup(None)
        
        # Mark as approved in pending_requests
        pending_requests[request_id]['status'] = 'approved'
        
        await callback_query.answer("Request approved and user notified!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Error in approve callback: {e}")
        await callback_query.answer(f"Error: {str(e)[:100]}", show_alert=True)

@app.on_callback_query(filters.regex(r'^reject_'))
async def reject_request_callback(client, callback_query):
    """Handle rejection via callback button"""
    user_id = callback_query.from_user.id
    
    # Check if user is admin
    if not await is_admin(user_id):
        await callback_query.answer("You are not authorized to perform this action!", show_alert=True)
        return
    
    # Extract request ID from callback data
    request_id = callback_query.data.replace('reject_', '')
    
    if request_id not in pending_requests:
        await callback_query.answer(f"Request ID {request_id} not found!", show_alert=True)
        return
    
    # Ask admin for rejection reason
    await callback_query.message.reply_text(
        f"Please provide a reason for rejecting request `{request_id}`.\n"
        f"Reply to this message with: `/reject {request_id} [reason]`"
    )
    
    await callback_query.answer("Please provide rejection reason as instructed", show_alert=True)

# Create a Flask server to keep the bot alive
app_server = Flask(__name__)

@app_server.route('/')
def home():
    return "TeraBox Downloader Bot is running!"

def run_server():
    app_server.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

if __name__ == "__main__":
    # Start Flask server in a separate thread
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Start the user bot if configured
    if user:
        try:
            user.start()
            logger.info("User client started successfully!")
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            user = None
    
    # Start the bot
    app.run()
