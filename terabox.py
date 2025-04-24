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
        
        # Save request in pending_requests
        pending_requests[request_id] = {
            'user_id': user_id,
            'user_mention': message.from_user.mention,
            'photo_id': photo_id,
            'description': description,
            'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'pending'
        }
        
        # Send confirmation to user
        await message.reply_text(
            f"✅ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜʙᴍɪᴛᴛᴇᴅ!\n\n"
            f"🆔 ʀᴇǫᴜᴇsᴛ ɪᴅ: `{request_id}`\n"
            f"📝 ᴅᴇsᴄʀɪᴘᴛɪᴏɴ: {description}\n\n"
            f"ᴡᴇ'ʟʟ ɴᴏᴛɪғʏ ʏᴏᴜ ᴡʜᴇɴ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ ɪs ᴘʀᴏᴄᴇssᴇᴅ."
        )
        
        # Forward request to admin channel
        try:
            # Forward to request channel
            await client.send_photo(
                chat_id=REQUEST_CHANNEL_ID,
                photo=photo_id,
                caption=f"🆕 **ɴᴇᴡ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ**\n\n"
                        f"🆔 **ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
                        f"👤 **ᴜsᴇʀ:** {message.from_user.mention} (`{user_id}`)\n"
                        f"📝 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {description}\n"
                        f"🕒 **ᴛɪᴍᴇ:** {pending_requests[request_id]['time']}\n\n"
                        f"📌 ᴛᴏ ᴀᴘᴘʀᴏᴠᴇ: `/approve {request_id} [message]`\n"
                        f"❌ ᴛᴏ ʀᴇᴊᴇᴄᴛ: `/reject {request_id} [reason]`"
            )
        except Exception as e:
            logger.error(f"Failed to forward request to admin channel: {e}")
        
        return
    
    # Handle TeraBox links
    text = message.text.strip()
    if is_valid_url(text):
        # Check for force subscription
        is_member = await is_user_member(client, user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Send processing message
        status_message = await message.reply_text("🔍 ᴘʀᴏᴄᴇssɪɴɢ ʏᴏᴜʀ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ...")
        
        try:
            # Get direct link from TeraBox
            terabox_info = await get_terabox_direct_link(text)
            
            if not terabox_info['success']:
                await update_status_message(
                    status_message, 
                    f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ᴘʀᴏᴄᴇss ʟɪɴᴋ: {terabox_info.get('error', 'Unknown error')}"
                )
                return
            
            direct_link = terabox_info['direct_link']
            filename = terabox_info['filename']
            file_size = terabox_info['size']
            
            if not direct_link:
                await update_status_message(status_message, "❌ ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ ᴅɪʀᴇᴄᴛ ʟɪɴᴋ.")
                return
            
            await update_status_message(
                status_message,
                f"📥 ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ: `{filename}`\n"
                f"📊 sɪᴢᴇ: {format_size(file_size)}\n\n"
                f"{generate_progress_bar(0)} 0%"
            )
            
            # Use aria2 to download the file
            if aria2:
                download = aria2.add_uris([direct_link], {'dir': '/app/downloads', 'out': filename})
                download_id = download.gid
                
                # Monitor download progress
                while True:
                    download_info = aria2.get_download(download_id)
                    if not download_info:
                        break
                    
                    status = download_info.status
                    if status == 'complete':
                        await update_status_message(status_message, f"✅ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ: `{filename}`\n💾 ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ...")
                        break
                    elif status == 'error':
                        await update_status_message(status_message, f"❌ ᴅᴏᴡɴʟᴏᴀᴅ ᴇʀʀᴏʀ: `{filename}`")
                        return
                    elif status == 'active':
                        # Calculate progress
                        completed_length = int(download_info.completed_length)
                        total_length = int(download_info.total_length) if download_info.total_length != '0' else 1
                        progress = (completed_length / total_length) * 100 if total_length > 0 else 0
                        
                        # Calculate speed and ETA
                        speed = int(download_info.download_speed)
                        eta = (total_length - completed_length) / speed if speed > 0 else 0
                        
                        # Update status message
                        await update_status_message(
                            status_message,
                            f"📥 ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ: `{filename}`\n"
                            f"📊 sɪᴢᴇ: {format_size(completed_length)}/{format_size(total_length)}\n"
                            f"⚡ sᴘᴇᴇᴅ: {format_size(speed)}/s\n"
                            f"⏱️ ᴇᴛᴀ: {format_eta(eta)}\n\n"
                            f"{generate_progress_bar(progress)} {progress:.1f}%"
                        )
                    
                    await asyncio.sleep(3)  # Update every 3 seconds
                
                # Download completed, upload file to Telegram
                file_path = os.path.join('/app/downloads', filename)
                
                # Check if file exists
                if not os.path.exists(file_path):
                    await update_status_message(status_message, f"❌ ғɪʟᴇ ɴᴏᴛ ғᴏᴜɴᴅ ᴀғᴛᴇʀ ᴅᴏᴡɴʟᴏᴀᴅ: `{filename}`")
                    return
                
                # Check file size and handle accordingly
                if os.path.getsize(file_path) > SPLIT_SIZE:
                    await update_status_message(status_message, f"⚠️ ғɪʟᴇ ɪs ᴛᴏᴏ ʟᴀʀɢᴇ ғᴏʀ ᴅɪʀᴇᴄᴛ ᴜᴘʟᴏᴀᴅ. ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴄʜᴀɴɴᴇʟ ɪɴsᴛᴇᴀᴅ...")
                    
                    # Upload to dump channel
                    dump_message = await client.send_document(
                        chat_id=DUMP_CHAT_ID,
                        document=file_path,
                        caption=f"📁 {filename}\n🔄 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ: {message.from_user.mention}",
                        progress=lambda current, total: asyncio.create_task(
                            update_status_message(
                                status_message,
                                f"📤 ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴄʜᴀɴɴᴇʟ: `{filename}`\n"
                                f"📊 sɪᴢᴇ: {format_size(current)}/{format_size(total)}\n\n"
                                f"{generate_progress_bar((current / total) * 100)} {(current / total) * 100:.1f}%"
                            )
                        )
                    )
                    
                    # Create invite link
                    file_link = f"https://t.me/c/{DUMP_CHAT_ID.replace('-100', '')}/{dump_message.id}"
                    
                    # Send link to user
                    await update_status_message(
                        status_message,
                        f"✅ ғɪʟᴇ ᴜᴘʟᴏᴀᴅᴇᴅ ᴛᴏ ᴄʜᴀɴɴᴇʟ!\n\n"
                        f"📁 ғɪʟᴇɴᴀᴍᴇ: `{filename}`\n"
                        f"📊 sɪᴢᴇ: {format_size(file_size)}\n\n"
                        f"📥 [ᴄʟɪᴄᴋ ʜᴇʀᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ]({file_link})"
                    )
                    
                else:
                    # Upload directly to user
                    await client.send_document(
                        chat_id=message.chat.id,
                        document=file_path,
                        caption=f"📁 {filename}\n💾 sɪᴢᴇ: {format_size(file_size)}",
                        progress=lambda current, total: asyncio.create_task(
                            update_status_message(
                                status_message,
                                f"📤 ᴜᴘʟᴏᴀᴅɪɴɢ: `{filename}`\n"
                                f"📊 sɪᴢᴇ: {format_size(current)}/{format_size(total)}\n\n"
                                f"{generate_progress_bar((current / total) * 100)} {(current / total) * 100:.1f}%"
                            )
                        )
                    )
                    
                    await update_status_message(status_message, f"✅ ғɪʟᴇ ᴜᴘʟᴏᴀᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ: `{filename}`")
                
                # Clean up downloaded file
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.error(f"Failed to remove downloaded file: {e}")
                
            else:
                await update_status_message(status_message, "❌ ᴀʀɪᴀ2 ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ. ᴄᴀɴɴᴏᴛ ᴅᴏᴡɴʟᴏᴀᴅ ғɪʟᴇ.")
                
        except Exception as e:
            logger.error(f"Error processing TeraBox link: {e}")
            await update_status_message(status_message, f"❌ ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ: {str(e)[:100]}...")

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    """Show bot statistics to admins"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    # Count pending requests
    pending_count = len([req for req_id, req in pending_requests.items() if req.get('status') == 'pending'])
    approved_count = len([req for req_id, req in pending_requests.items() if req.get('status') == 'approved'])
    
    stats_text = (
        "📊 **ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs**\n\n"
        f"🔄 **ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs:** {pending_count}\n"
        f"✅ **ᴀᴘᴘʀᴏᴠᴇᴅ ʀᴇǫᴜᴇsᴛs:** {approved_count}\n"
    )
    
    await message.reply_text(stats_text)

@app.on_message(filters.command("broadcast"))
async def broadcast_command(client: Client, message: Message):
    """Broadcast a message to all users who have requested videos"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await message.reply_text("⚠️ Please provide a message to broadcast.\nFormat: `/broadcast [message]`")
        return
    
    broadcast_message = command_parts[1]
    
    # Get unique user IDs from pending_requests
    user_ids = set()
    for request_id, request_data in pending_requests.items():
        user_ids.add(request_data['user_id'])
    
    if not user_ids:
        await message.reply_text("⚠️ No users found to broadcast to.")
        return
    
    # Send status message
    status_message = await message.reply_text(f"🔄 Broadcasting message to {len(user_ids)} users...")
    
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
        
        # Update status message every 10 users
        if (success_count + fail_count) % 10 == 0:
            await update_status_message(
                status_message,
                f"🔄 Broadcasting: {success_count + fail_count}/{len(user_ids)} users processed\n"
                f"✅ Success: {success_count}\n"
                f"❌ Failed: {fail_count}"
            )
    
    # Final update
    await update_status_message(
        status_message,
        f"✅ Broadcast completed!\n\n"
        f"📊 **ʀᴇsᴜʟᴛs:**\n"
        f"👥 Total users: {len(user_ids)}\n"
        f"✅ Successful: {success_count}\n"
        f"❌ Failed: {fail_count}"
    )

# Flask web server for keeping the bot alive
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "TeraBox Downloader Bot is running!"

def run_flask():
    app_web.run(host='0.0.0.0', port=8080)

def main():
    # Start the web server in a separate thread
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
    
    # Start user client if available
    if user:
        try:
            user.start()
            logger.info("User client started successfully")
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
    
    # Start the bot
    logger.info("Starting Telegram bot...")
    app.run()

if __name__ == "__main__":
    main()
