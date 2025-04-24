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

# Use requestsids as the REQUEST_CHANNEL_ID
REQUEST_CHANNEL_USERNAME = "requestsids"
REQUEST_CHANNEL_ID = REQUEST_CHANNEL_USERNAME

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

# Enhanced function with backup methods to fetch TeraBox link details
async def get_terabox_direct_link(url):
    """Fetch direct download link and file details from TeraBox API with multiple fallback methods"""
    # Try first API endpoint
    try:
        api_url = f"https://teraboxapi-phi.vercel.app/api?url={url}"
        response = requests.get(api_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check if API returned success
            if data.get('success', False) and data.get('direct_link'):
                return {
                    'direct_link': data.get('direct_link', ''),
                    'filename': data.get('filename', ''),
                    'size': data.get('size', 0),
                    'success': True
                }
    except Exception as e:
        logger.error(f"First API method failed: {e}")
    
    # Try alternative method 1 - second API endpoint
    try:
        url_encoded = urllib.parse.quote_plus(url)
        alt_api_url = f"https://terabox-dl.herokuapp.com/api?url={url_encoded}"
        response = requests.get(alt_api_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == "success" and data.get('dl_link'):
                return {
                    'direct_link': data.get('dl_link', ''),
                    'filename': data.get('filename', ''),
                    'size': data.get('size', 0),
                    'success': True
                }
    except Exception as e:
        logger.error(f"Second API method failed: {e}")
    
    # Try alternative method 2 - third API endpoint
    try:
        alt_api_url2 = f"https://terabox-dl-api.vercel.app/api?url={url}"
        response = requests.get(alt_api_url2, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('direct_link'):
                return {
                    'direct_link': data.get('direct_link', ''),
                    'filename': data.get('filename', ''),
                    'size': data.get('size', 0),
                    'success': True
                }
    except Exception as e:
        logger.error(f"Third API method failed: {e}")
        
    # If all methods fail, return failure
    return {'success': False, 'error': 'All methods to fetch link details failed'}

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
    if user_id is None:
        return False
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
    if message.from_user and message.from_user.id in users_in_request_mode:
        del users_in_request_mode[message.from_user.id]
        
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/dailydiskwala")
    developer_button = InlineKeyboardButton("Backup", url="https://t.me/terao2")
    repo69 = InlineKeyboardButton("Requested videos", url="https://t.me/dailydiskwala")
    request_button = InlineKeyboardButton("ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏ 🎬", callback_data="request_video")
    
    user_mention = message.from_user.mention if message.from_user else "User"
    reply_markup = InlineKeyboardMarkup([
        [join_button, developer_button], 
        [repo69],
        [request_button]
    ])
    
    # Check if user is admin and add admin commands button
    if message.from_user and await is_admin(message.from_user.id):
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
    if not message.from_user or not await is_admin(message.from_user.id):
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
    if not message.from_user or not await is_admin(message.from_user.id):
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
    # Fix for NoneType error - check if message.from_user exists
    if not message.from_user or not await is_admin(message.from_user.id):
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
    # Fix for NoneType error - check if message.from_user exists
    if not message.from_user or not await is_admin(message.from_user.id):
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
    # Fix for NoneType error - check if message.from_user exists
    if not message.from_user or not await is_admin(message.from_user.id):
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
    # Fix for NoneType error - check if message.from_user exists
    if not message.from_user or not await is_admin(message.from_user.id):
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
    if not callback_query.from_user:
        await callback_query.answer("Error: User information not available.")
        return
    
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

@app.on_message(filters.photo & filters.private)
async def handle_photo(client, message):
    """Handle photo uploads for video requests"""
    if not message.from_user:
        await message.reply_text("Error: User information not available.")
        return
    
    user_id = message.from_user.id
    
    # Check if user is in request mode
    if user_id not in users_in_request_mode or users_in_request_mode[user_id]["state"] != "waiting_for_image":
        # User just sent a photo without being in request mode
        await message.reply_text("🎬 Do you want to request this video? Please use the /start command and click on 'Request Video' button.")
        return
    
    # Check for force subscription
    is_member = await is_user_member(client, user_id)
    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/dailydiskwala")
        reply_markup = InlineKeyboardMarkup([[join_button]])
        await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
        return
    
    # Store the photo file_id
    photo_file_id = message.photo[-1].file_id
    users_in_request_mode[user_id]["photo_id"] = photo_file_id
    users_in_request_mode[user_id]["state"] = "waiting_for_description"
    
    # Request description
    cancel_button = InlineKeyboardButton("ᴄᴀɴᴄᴇʟ ❌", callback_data="cancel_request")
    reply_markup = InlineKeyboardMarkup([[cancel_button]])
    
    await message.reply_text(
        "📝 ɴᴏᴡ ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴏғ ᴛʜᴇ ᴠɪᴅᴇᴏ (ɴᴀᴍᴇ, ᴇᴘɪsᴏᴅᴇ, ᴇᴛᴄ.)",
        reply_markup=reply_markup
    )

@app.on_message(filters.text & filters.private)
async def handle_text(client, message):
    """Handle text messages, including TeraBox links and request descriptions"""
    if not message.from_user:
        await message.reply_text("Error: User information not available.")
        return
    
    user_id = message.from_user.id
    text = message.text
    
    # Don't process commands
    if text.startswith("/"):
        return
    
    # Check for force subscription
    is_member = await is_user_member(client, user_id)
    if not is_member:
        join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/dailydiskwala")
        reply_markup = InlineKeyboardMarkup([[join_button]])
        await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
        return
    
    # Handle video request description
    if user_id in users_in_request_mode and users_in_request_mode[user_id]["state"] == "waiting_for_description":
        description = text
        photo_id = users_in_request_mode[user_id]["photo_id"]
        
        # Generate a unique request ID
        request_id = f"REQ{int(time.time())}{user_id % 1000}"
        
        # Store request information
        pending_requests[request_id] = {
            "user_id": user_id,
            "user_mention": message.from_user.mention,
            "photo_id": photo_id,
            "description": description,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "pending"
        }
        
        # Clear user from request mode
        del users_in_request_mode[user_id]
        
        # Notify user about their request
        await message.reply_text(
            f"✅ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜʙᴍɪᴛᴛᴇᴅ!\n\n"
            f"🆔 ʀᴇǫᴜᴇsᴛ ɪᴅ: `{request_id}`\n"
            f"📝 ᴅᴇsᴄʀɪᴘᴛɪᴏɴ: {description}\n\n"
            f"ᴡᴇ ᴡɪʟʟ ɴᴏᴛɪғʏ ʏᴏᴜ ᴡʜᴇɴ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ɪs ᴀᴠᴀɪʟᴀʙʟᴇ."
        )
        
        # Forward request to admins
        try:
            # First send the photo
            sent_photo = await client.send_photo(
                chat_id=DUMP_CHAT_ID,
                photo=photo_id,
                caption=f"📥 **ɴᴇᴡ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ**\n\n"
                       f"🆔 **ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
                       f"👤 **ᴜsᴇʀ:** {message.from_user.mention} (`{user_id}`)\n"
                       f"📝 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {description}\n\n"
                       f"ᴜsᴇ `/approve {request_id}` ᴏʀ `/reject {request_id} [reason]` ᴛᴏ ʀᴇsᴘᴏɴᴅ."
            )
            
            logger.info(f"New video request forwarded to admins: {request_id}")
        except Exception as e:
            logger.error(f"Failed to forward video request to admins: {e}")
        
        return
    
    # Handle TeraBox links
    if is_valid_url(text):
        # Send a status message
        status_message = await message.reply_text("🔍 ᴠᴀʟɪᴅ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ ᴅᴇᴛᴇᴄᴛᴇᴅ! ᴘʀᴏᴄᴇssɪɴɢ...")
        
        # Get file info
        try:
            await update_status_message(status_message, "⏳ ғᴇᴛᴄʜɪɴɢ ғɪʟᴇ ɪɴғᴏʀᴍᴀᴛɪᴏɴ...")
            file_info = await get_terabox_direct_link(text)
            
            if not file_info['success']:
                await update_status_message(status_message, f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ᴘʀᴏᴄᴇss ʟɪɴᴋ: {file_info.get('error', 'Unknown error')}")
                return
                
            direct_link = file_info['direct_link']
            filename = file_info.get('filename', 'terabox_file')
            size = file_info.get('size', 0)
            
            # Format file information
            file_size_formatted = format_size(size)
            
            await update_status_message(status_message, 
                f"✅ ғɪʟᴇ ɪɴғᴏ ʀᴇᴛʀɪᴇᴠᴇᴅ!\n\n"
                f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                f"📊 **sɪᴢᴇ:** {file_size_formatted}\n\n"
                f"⏳ sᴛᴀʀᴛɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ..."
            )
            
            # Download the file using aria2
            if aria2:
                try:
                    download = aria2.add_uris([direct_link], {'dir': '/tmp', 'out': filename})
                    download_id = download.gid
                    
                    # Update progress
                    progress_message = (
                        f"📥 **ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**\n\n"
                        f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                        f"📊 **sɪᴢᴇ:** {file_size_formatted}\n"
                        f"⏱️ **ᴇᴛᴀ:** calculating...\n"
                        f"🔄 **ᴘʀᴏɢʀᴇss:** 0%\n"
                        f"{generate_progress_bar(0)}"
                    )
                    await update_status_message(status_message, progress_message)
                    
                    # Monitor download progress
                    previous_progress = 0
                    last_update_time = time.time()
                    
                    while True:
                        download = aria2.get_download(download_id)
                        
                        if download.is_complete:
                            await update_status_message(status_message, 
                                f"✅ **ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ!**\n\n"
                                f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                                f"📊 **sɪᴢᴇ:** {file_size_formatted}\n\n"
                                f"⏳ ᴘʀᴇᴘᴀʀɪɴɢ ᴛᴏ ᴜᴘʟᴏᴀᴅ..."
                            )
                            break
                        
                        if download.has_failed:
                            await update_status_message(status_message, 
                                f"❌ **ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ!**\n\n"
                                f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                                f"⚠️ **ᴇʀʀᴏʀ:** {download.error_message}\n\n"
                                f"ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ."
                            )
                            return
                        
                        progress = round(download.progress * 100, 2)
                        current_time = time.time()
                        
                        # Update UI only if progress changed by at least 2% or 3 seconds passed
                        if (progress - previous_progress >= 2) or (current_time - last_update_time >= 3):
                            previous_progress = progress
                            last_update_time = current_time
                            
                            download_speed = format_size(download.download_speed) + "/s"
                            eta_seconds = download.eta
                            eta = format_eta(eta_seconds)
                            
                            progress_message = (
                                f"📥 **ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**\n\n"
                                f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                                f"📊 **sɪᴢᴇ:** {file_size_formatted}\n"
                                f"⚡ **sᴘᴇᴇᴅ:** {download_speed}\n"
                                f"⏱️ **ᴇᴛᴀ:** {eta}\n"
                                f"🔄 **ᴘʀᴏɢʀᴇss:** {progress}%\n"
                                f"{generate_progress_bar(progress)}"
                            )
                            await update_status_message(status_message, progress_message)
                        
                        await asyncio.sleep(1)
                    
                    # File is downloaded, now upload to Telegram
                    filepath = os.path.join('/tmp', filename)
                    file_size = os.path.getsize(filepath)
                    
                    # Check if file size exceeds Telegram limit (2GB for normal bots, 4GB for premium users)
                    if file_size > SPLIT_SIZE:
                        await update_status_message(status_message, 
                            f"⚠️ **ғɪʟᴇ ᴇxᴄᴇᴇᴅs ᴛᴇʟᴇɢʀᴀᴍ ʟɪᴍɪᴛ**\n\n"
                            f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                            f"📊 **sɪᴢᴇ:** {file_size_formatted}\n\n"
                            f"ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ʏᴏᴜʀ ᴅᴜᴍᴘ ᴄʜᴀɴɴᴇʟ..."
                        )
                        
                        # Upload to dump channel
                        try:
                            await update_status_message(status_message, "📤 ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴅᴜᴍᴘ ᴄʜᴀɴɴᴇʟ...")
                            
                            # Upload using user account if available
                            if user:
                                sent_message = await user.send_document(
                                    chat_id=DUMP_CHAT_ID,
                                    document=filepath,
                                    caption=f"📤 **ғɪʟᴇ ᴜᴘʟᴏᴀᴅᴇᴅ**\n\n📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n📊 **sɪᴢᴇ:** {file_size_formatted}\n🔗 **sᴏᴜʀᴄᴇ:** {text}",
                                    progress=progress_callback,
                                    progress_args=(status_message, filename, file_size_formatted)
                                )
                                
                                # Create shareable link
                                link = f"https://t.me/c/{str(DUMP_CHAT_ID)[4:]}/{sent_message.id}"
                                
                                await update_status_message(status_message,
                                    f"✅ **ᴜᴘʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ!**\n\n"
                                    f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                                    f"📊 **sɪᴢᴇ:** {file_size_formatted}\n\n"
                                    f"📥 **ᴅᴏᴡɴʟᴏᴀᴅ ғʀᴏᴍ:** [Dump Channel]({link})"
                                )
                            else:
                                await update_status_message(status_message,
                                    f"⚠️ **ғɪʟᴇ ᴛᴏᴏ ʟᴀʀɢᴇ ғᴏʀ ʙᴏᴛ ᴜᴘʟᴏᴀᴅ**\n\n"
                                    f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                                    f"📊 **sɪᴢᴇ:** {file_size_formatted}\n\n"
                                    f"ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴs ғᴏʀ ᴀssɪsᴛᴀɴᴄᴇ."
                                )
                        except Exception as e:
                            logger.error(f"Failed to upload large file to dump channel: {e}")
                            await update_status_message(status_message,
                                f"❌ **ᴜᴘʟᴏᴀᴅ ғᴀɪʟᴇᴅ!**\n\n"
                                f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                                f"⚠️ **ᴇʀʀᴏʀ:** Failed to upload large file.\n\n"
                                f"ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴs ғᴏʀ ᴀssɪsᴛᴀɴᴄᴇ."
                            )
                    else:
                        # File is within Telegram limits, upload directly
                        try:
                            await update_status_message(status_message, 
                                f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ...**\n\n"
                                f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
                                f"📊 **sɪᴢᴇ:** {file_size_formatted}\n"
                                f"🔄 **ᴘʀᴏɢʀᴇss:** 0%\n"
                                f"{generate_progress_bar(0)}"
                            )
                            
                            # Determine if it's a video or document based on extension
                            video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']
                            is_video = any(filename.lower().endswith(ext) for ext in video_extensions)
                            
                            # Send as video or document based on file type
                            if is_video:
                                await client.send_video(
                                    chat_id=message.chat.id,
                                    video=filepath,
                                    caption=f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n📊 **sɪᴢᴇ:** {file_size_formatted}\n🔗 **sᴏᴜʀᴄᴇ:** TeraBox",
                                    progress=progress_callback,
                                    progress_args=(status_message, filename, file_size_formatted)
                                )
                            else:
                                await client.send_document(
                                    chat_id=message.chat.id,
                                    document=filepath,
                                    caption=f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n📊 **sɪᴢᴇ:** {file_size_formatted}\n🔗 **sᴏᴜʀᴄᴇ:** TeraBox",
                                    progress=progress_callback,
                                    progress_args=(status_message, filename, file_size_formatted)
                                )
                            
                            await update_status_message(status_message, f"✅ **ᴜᴘʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ!**\n\n📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n📊 **sɪᴢᴇ:** {file_size_formatted}")
                        except Exception as e:
                            logger.error(f"Failed to upload file: {e}")
                            await update_status_message(status_message, f"❌ **ᴜᴘʟᴏᴀᴅ ғᴀɪʟᴇᴅ!**\n\n📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n⚠️ **ᴇʀʀᴏʀ:** {str(e)[:100]}...")
                    
                    # Clean up
                    try:
                        os.remove(filepath)
                    except Exception as e:
                        logger.error(f"Failed to clean up file {filepath}: {e}")
                    
                except Exception as e:
                    logger.error(f"Aria2 download failed: {e}")
                    await update_status_message(status_message, f"❌ **ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ!**\n\n⚠️ **ᴇʀʀᴏʀ:** {str(e)[:100]}...")
            else:
                await update_status_message(status_message, "❌ **ᴀʀɪᴀ2 ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.**\n\nᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ ᴀᴅᴍɪɴ.")
        
        except Exception as e:
            logger.error(f"Error processing TeraBox link: {e}")
            await update_status_message(status_message, f"❌ **ᴇʀʀᴏʀ ᴘʀᴏᴄᴇssɪɴɢ ʟɪɴᴋ!**\n\n⚠️ **ᴇʀʀᴏʀ:** {str(e)[:100]}...")

async def progress_callback(current, total, status_message, filename, size_str):
    """Callback for upload progress updates"""
    if total == 0:
        return
    
    global last_update_time
    now = time.time()
    
    # Update only if at least 1 second passed or it's the first/last update
    if now - last_update_time < 1 and 0 < current < total:
        return
    
    last_update_time = now
    
    percentage = round((current * 100) / total, 2)
    
    progress_message = (
        f"📤 **ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ...**\n\n"
        f"📋 **ғɪʟᴇɴᴀᴍᴇ:** `{filename}`\n"
        f"📊 **sɪᴢᴇ:** {size_str}\n"
        f"🔄 **ᴘʀᴏɢʀᴇss:** {percentage}%\n"
        f"{generate_progress_bar(percentage)}"
    )
    
    try:
        await status_message.edit_text(progress_message)
    except Exception as e:
        logger.error(f"Failed to update progress message: {e}")

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    """Show bot statistics to admins"""
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    pending_count = len([r for r in pending_requests.values() if r.get('status') == 'pending'])
    approved_count = len([r for r in pending_requests.values() if r.get('status') == 'approved'])
    
    stats_text = (
        "📊 **ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs:**\n\n"
        f"📝 **ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs:** {pending_count}\n"
        f"✅ **ᴀᴘᴘʀᴏᴠᴇᴅ ʀᴇǫᴜᴇsᴛs:** {approved_count}\n"
    )
    
    await message.reply_text(stats_text)

@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_command(client: Client, message: Message):
    """Send a broadcast message to all users who have made requests"""
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await message.reply_text("⚠️ Please provide a message to broadcast.\nFormat: `/broadcast [message]`")
        return
    
    broadcast_message = command_parts[1]
    
    # Get unique user IDs from pending requests
    user_ids = set(request['user_id'] for request in pending_requests.values())
    
    if not user_ids:
        await message.reply_text("⚠️ No users found to broadcast to.")
        return
    
    status_message = await message.reply_text(f"🔄 Broadcasting message to {len(user_ids)} users...")
    
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"📢 **ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ ғʀᴏᴍ ᴀᴅᴍɪɴ**\n\n{broadcast_message}"
            )
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")
            fail_count += 1
        
        # Add a small delay to avoid flood limits
        await asyncio.sleep(0.1)
    
    await status_message.edit_text(
        f"✅ **ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ**\n\n"
        f"📤 **sᴇɴᴛ ᴛᴏ:** {success_count} users\n"
        f"❌ **ғᴀɪʟᴇᴅ:** {fail_count} users"
    )
    # Create a simple web server to keep the bot alive on platforms like Heroku
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "TeraBox Downloader Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host='0.0.0.0', port=port)

async def start_bot():
    """Start the bot and initialize required resources"""
    # Connect to the bot and user accounts
    await app.start()
    
    if user:
        try:
            await user.start()
            logger.info("User client started successfully")
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
    
    # Log startup info
    bot_info = await app.get_me()
    logger.info(f"Bot started as @{bot_info.username}")
    
    # Check for DUMP_CHAT_ID validity
    try:
        chat = await app.get_chat(DUMP_CHAT_ID)
        logger.info(f"Dump chat configured: {chat.title}")
    except Exception as e:
        logger.error(f"Invalid DUMP_CHAT_ID: {e}")
    
    # Check for aria2c
    if aria2:
        try:
            version = aria2.client.get_version()
            logger.info(f"Aria2 connected: {version['version']}")
        except Exception as e:
            logger.error(f"Aria2 connection error: {e}")
    else:
        logger.warning("Aria2 is not available. Downloads may not work properly.")
    
    # Wait for signal to stop
    await asyncio.Event().wait()

async def stop_bot():
    """Stop the bot and clean up resources"""
    if user:
        await user.stop()
    await app.stop()

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    """Display help information"""
    help_text = (
        "📖 **ʜᴇʟᴘ & ᴄᴏᴍᴍᴀɴᴅs**\n\n"
        "• Send any TeraBox link to download\n"
        "• Use `/start` to see the welcome message\n"
        "• Click 'Request Video' to request new content\n"
        "• Use `/help` to see this message\n\n"
        "📝 **ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛs**\n\n"
        "1. Click 'Request Video' button\n"
        "2. Send a screenshot of the video\n"
        "3. Provide a description\n"
        "4. Wait for admin approval\n\n"
        "🔗 **sᴜᴘᴘᴏʀᴛᴇᴅ ᴛᴇʀᴀʙᴏx ᴅᴏᴍᴀɪɴs**\n\n"
        "• terabox.com, nephobox.com, 4funbox.com\n"
        "• mirrobox.com, teraboxapp.com, etc."
    )
    
    await message.reply_text(help_text)

@app.on_message(filters.command("restart") & filters.private)
async def restart_command(client: Client, message: Message):
    """Restart the bot (admin only)"""
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    restart_message = await message.reply_text("🔄 Restarting bot...")
    
    try:
        # Ensure both clients are stopped properly
        if user:
            await user.stop()
        await app.stop()
        
        # Restart using the command set by the system
        if os.environ.get("RESTART_CMD"):
            os.system(os.environ.get("RESTART_CMD"))
        else:
            # Default restart behavior
            os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        logger.error(f"Failed to restart bot: {e}")
        await restart_message.edit_text(f"❌ Failed to restart: {str(e)[:100]}...")

@app.on_message(filters.command("clean") & filters.private)
async def clean_command(client: Client, message: Message):
    """Clean temporary files (admin only)"""
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    clean_message = await message.reply_text("🔍 Checking for temporary files...")
    
    try:
        # Clean up /tmp directory
        count = 0
        size_freed = 0
        for filename in os.listdir('/tmp'):
            if not filename.startswith('.'):  # Skip hidden files
                try:
                    file_path = os.path.join('/tmp', filename)
                    if os.path.isfile(file_path):
                        file_size = os.path.getsize(file_path)
                        os.remove(file_path)
                        count += 1
                        size_freed += file_size
                except Exception as e:
                    logger.error(f"Failed to remove file {filename}: {e}")
        
        size_freed_str = format_size(size_freed)
        await clean_message.edit_text(f"✅ Cleanup complete!\n\n🗑️ Removed {count} files\n💾 Freed {size_freed_str} of space")
    except Exception as e:
        logger.error(f"Clean operation failed: {e}")
        await clean_message.edit_text(f"❌ Cleanup failed: {str(e)[:100]}...")

@app.on_message(filters.command("maintenance") & filters.private)
async def maintenance_command(client: Client, message: Message):
    """Toggle maintenance mode (admin only)"""
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    global MAINTENANCE_MODE
    command_parts = message.text.split(' ', 1)
    
    if len(command_parts) > 1 and command_parts[1].lower() == 'off':
        MAINTENANCE_MODE = False
        await message.reply_text("✅ Maintenance mode disabled. Bot is now available to all users.")
    else:
        MAINTENANCE_MODE = True
        maintenance_message = "🛠️ Bot is currently under maintenance. Please try again later."
        await message.reply_text(f"✅ Maintenance mode enabled with message:\n\n{maintenance_message}")

@app.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    """Check bot's response time"""
    start_time = time.time()
    ping_message = await message.reply_text("🏓 Pinging...")
    
    # Check aria2 status
    aria2_status = "✅ Connected" if aria2 else "❌ Not connected"
    
    # Calculate response time
    end_time = time.time()
    response_time = round((end_time - start_time) * 1000, 2)
    
    await ping_message.edit_text(
        f"🏓 **Pong!**\n\n"
        f"⏱️ **Response time:** {response_time} ms\n"
        f"📡 **Aria2:** {aria2_status}\n"
        f"🤖 **Bot status:** Online"
    )

# Define the maintenance mode global variable
MAINTENANCE_MODE = False

# Add middleware to check maintenance mode
@app.on_message(group=-1)
async def maintenance_middleware(client, message):
    """Check if bot is in maintenance mode before processing messages"""
    # Skip for admins
    if message.from_user and await is_admin(message.from_user.id):
        return
    
    if MAINTENANCE_MODE:
        if not message.text or not message.text.startswith('/'):
            await message.reply_text("🛠️ Bot is currently under maintenance. Please try again later.")
            return message.stop_propagation()

# Error handling middleware
@app.on_message(group=-2)
async def error_handler(client, message):
    """Global error handler for all messages"""
    try:
        await message.continue_propagation()
    except Exception as e:
        logger.error(f"Unhandled exception in message handler: {e}")
        if message.from_user and await is_admin(message.from_user.id):
            await message.reply_text(f"⚠️ Unexpected error: {str(e)[:100]}...")
        else:
            await message.reply_text("⚠️ An unexpected error occurred. Please try again later.")

if __name__ == "__main__":
    # Start the Flask server in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_bot())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping bot...")
        loop.run_until_complete(stop_bot())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        loop.run_until_complete(stop_bot())
    finally:
        loop.close()
