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
        
        # Generate a unique request ID (timestamp + user ID)
        request_id = f"REQ{int(time.time())}{user_id % 1000}"
        
        # Store the request
        pending_requests[request_id] = {
            'user_id': user_id,
            'user_mention': message.from_user.mention,
            'photo_id': photo_id,
            'description': description,
            'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'pending'
        }
        
        # Notify user
        await message.reply_text(
            f"✅ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜʙᴍɪᴛᴛᴇᴅ!\n\n"
            f"🆔 **ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
            f"📝 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {description}\n\n"
            f"⏳ ᴡᴇ ᴡɪʟʟ ɴᴏᴛɪғʏ ʏᴏᴜ ᴡʜᴇɴ ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ ɪs ᴘʀᴏᴄᴇssᴇᴅ."
        )
        
        # Forward the request to the request channel
        try:
            # First forward the photo
            forwarded_photo = await client.send_photo(
                chat_id=REQUEST_CHANNEL_ID,
                photo=photo_id,
                caption=f"🆕 **ɴᴇᴡ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ**\n\n"
                        f"🆔 **ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
                        f"👤 **ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ:** {message.from_user.mention} (`{user_id}`)\n"
                        f"📝 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {description}\n"
                        f"⏰ **ᴛɪᴍᴇ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            # Add approval/rejection buttons for admins
            approve_button = InlineKeyboardButton("✅ ᴀᴘᴘʀᴏᴠᴇ", callback_data=f"approve_{request_id}")
            reject_button = InlineKeyboardButton("❌ ʀᴇᴊᴇᴄᴛ", callback_data=f"reject_{request_id}")
            admin_reply_markup = InlineKeyboardMarkup([[approve_button, reject_button]])
            
            # Add buttons to the forwarded message
            await forwarded_photo.edit_reply_markup(admin_reply_markup)
            
        except Exception as e:
            logger.error(f"Failed to forward request to channel: {e}")
            # Still continue as the user's request has been registered
        
        return
    
    # Check for TeraBox URL
    if is_valid_url(message.text):
        # Check for force subscription
        is_member = await is_user_member(client, user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Send initial processing message
        status_message = await message.reply_text("⏳ ᴘʀᴏᴄᴇssɪɴɢ ʏᴏᴜʀ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ...")
        
        terabox_url = message.text.strip()
        
        try:
            # Update status
            await update_status_message(status_message, "🔍 ғᴇᴛᴄʜɪɴɢ ғɪʟᴇ ɪɴғᴏʀᴍᴀᴛɪᴏɴ...")
            
            # Get TeraBox direct link
            link_info = await get_terabox_direct_link(terabox_url)
            
            if not link_info['success']:
                await update_status_message(status_message, f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ᴘʀᴏᴄᴇss ʟɪɴᴋ: {link_info.get('error', 'Unknown error')}")
                return
            
            direct_link = link_info['direct_link']
            filename = link_info['filename']
            file_size = link_info['size']
            
            # Update with file info
            await update_status_message(
                status_message, 
                f"📁 **ғɪʟᴇ ᴅᴇᴛᴀɪʟs:**\n\n"
                f"**ɴᴀᴍᴇ:** `{filename}`\n"
                f"**sɪᴢᴇ:** `{format_size(file_size)}`\n\n"
                f"⏳ sᴛᴀʀᴛɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ..."
            )
            
            # Check if aria2 is available
            if not aria2:
                await update_status_message(status_message, "❌ ᴅᴏᴡɴʟᴏᴀᴅ ᴇɴɢɪɴᴇ ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.")
                return
            
            # Start download with aria2
            download = aria2.add_uris([direct_link], {'dir': '/app/downloads/', 'out': filename})
            download_id = download.gid
            
            # Monitor download progress
            last_update_time = 0
            while download.is_active or download.is_waiting:
                download = aria2.get_download(download_id)
                
                # Update status every 3 seconds to avoid flooding
                current_time = time.time()
                if current_time - last_update_time >= 3:
                    last_update_time = current_time
                    
                    # Calculate progress percentage
                    if download.total_length > 0:
                        progress = download.completed_length / download.total_length * 100
                    else:
                        progress = 0
                    
                    # Calculate speed and ETA
                    speed = download.download_speed
                    if speed > 0 and download.total_length > 0:
                        eta = (download.total_length - download.completed_length) / speed
                    else:
                        eta = 0
                    
                    # Update progress message
                    progress_bar = generate_progress_bar(progress)
                    await update_status_message(
                        status_message,
                        f"📥 **ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**\n\n"
                        f"**ɴᴀᴍᴇ:** `{filename}`\n"
                        f"**sɪᴢᴇ:** `{format_size(download.total_length)}`\n"
                        f"**ᴘʀᴏɢʀᴇss:** {progress_bar} `{progress:.1f}%`\n"
                        f"**ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ:** `{format_size(download.completed_length)}`\n"
                        f"**sᴘᴇᴇᴅ:** `{format_size(speed)}/s`\n"
                        f"**ᴇᴛᴀ:** `{format_eta(eta)}`"
                    )
                
                await asyncio.sleep(1)
            
            # Check if download completed successfully
            if download.status == 'complete':
                await update_status_message(status_message, f"✅ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!\n\n**ɴᴀᴍᴇ:** `{filename}`\n**sɪᴢᴇ:** `{format_size(download.total_length)}`\n\n⏳ ᴘʀᴇᴘᴀʀɪɴɢ ᴛᴏ ᴜᴘʟᴏᴀᴅ...")
                
                # Get the downloaded file path
                file_path = os.path.join('/app/downloads/', filename)
                
                # Check if file exists
                if not os.path.exists(file_path):
                    await update_status_message(status_message, "❌ ᴇʀʀᴏʀ: ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ ғɪʟᴇ ɴᴏᴛ ғᴏᴜɴᴅ.")
                    return
                
                # Check file size
                file_size = os.path.getsize(file_path)
                
                # Upload the file to Telegram
                try:
                    # Determine if we need to use the user client for large files
                    if file_size > SPLIT_SIZE or file_size > 2000 * 1024 * 1024:  # > 2GB
                        if user and USER_SESSION_STRING:
                            await update_status_message(status_message, f"📤 ᴜᴘʟᴏᴀᴅɪɴɢ ᴠɪᴀ ᴜsᴇʀ ᴄʟɪᴇɴᴛ...\n\n**ɴᴀᴍᴇ:** `{filename}`\n**sɪᴢᴇ:** `{format_size(file_size)}`")
                            
                            # Upload to dump channel first
                            sent_message = await user.send_document(
                                chat_id=DUMP_CHAT_ID,
                                document=file_path,
                                caption=f"📁 **ғɪʟᴇ ɴᴀᴍᴇ:** `{filename}`\n**sɪᴢᴇ:** `{format_size(file_size)}`\n\n**ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ:** {message.from_user.mention}"
                            )
                            
                            # Forward to user
                            await sent_message.forward(message.chat.id)
                            
                            # Delete the status message
                            await status_message.delete()
                        else:
                            await update_status_message(status_message, f"❌ ғɪʟᴇ ɪs ᴛᴏᴏ ʟᴀʀɢᴇ ᴛᴏ ᴜᴘʟᴏᴀᴅ ᴠɪᴀ ʙᴏᴛ (`{format_size(file_size)}`). ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ.")
                    else:
                        # File is small enough for bot upload
                        await update_status_message(status_message, f"📤 ᴜᴘʟᴏᴀᴅɪɴɢ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ...\n\n**ɴᴀᴍᴇ:** `{filename}`\n**sɪᴢᴇ:** `{format_size(file_size)}`")
                        
                        # Upload via bot
                        await message.reply_document(
                            document=file_path,
                            caption=f"📁 **ғɪʟᴇ ɴᴀᴍᴇ:** `{filename}`\n**sɪᴢᴇ:** `{format_size(file_size)}`\n\n**ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ:** {message.from_user.mention}"
                        )
                        
                        # Delete the status message
                        await status_message.delete()
                
                except Exception as e:
                    logger.error(f"Upload error: {e}")
                    await update_status_message(status_message, f"❌ ᴜᴘʟᴏᴀᴅ ғᴀɪʟᴇᴅ: {str(e)[:100]}...")
                
                # Clean up the downloaded file
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.error(f"Error removing file: {e}")
            else:
                # Download failed
                await update_status_message(status_message, f"❌ ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ: {download.error_message}")
        
        except Exception as e:
            logger.error(f"Process error: {e}")
            await update_status_message(status_message, f"❌ ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ: {str(e)[:100]}...")

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    """Show bot statistics to admins"""
    if not await is_admin(message.from_user.id):
        await message.reply_text("⚠️ You are not authorized to use this command.")
        return
    
    # Collect stats
    pending_count = len([req for req_id, req in pending_requests.items() if req.get('status', '') == 'pending'])
    approved_count = len([req for req_id, req in pending_requests.items() if req.get('status', '') == 'approved'])
    
    stats_text = (
        "📊 **ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs**\n\n"
        f"📝 **ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs:** `{pending_count}`\n"
        f"✅ **ᴀᴘᴘʀᴏᴠᴇᴅ ʀᴇǫᴜᴇsᴛs:** `{approved_count}`\n"
    )
    
    # Add download stats if aria2 is available
    if aria2:
        try:
            downloads = aria2.get_downloads()
            active_downloads = len([d for d in downloads if d.is_active])
            waiting_downloads = len([d for d in downloads if d.is_waiting])
            completed_downloads = len([d for d in downloads if d.is_complete])
            
            stats_text += (
                f"\n📥 **ᴅᴏᴡɴʟᴏᴀᴅ sᴛᴀᴛs:**\n"
                f"⏳ **ᴀᴄᴛɪᴠᴇ:** `{active_downloads}`\n"
                f"⌛ **ᴡᴀɪᴛɪɴɢ:** `{waiting_downloads}`\n"
                f"✅ **ᴄᴏᴍᴘʟᴇᴛᴇᴅ:** `{completed_downloads}`\n"
            )
        except Exception as e:
            logger.error(f"Error getting download stats: {e}")
    
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
    
    # Collect unique user IDs from pending requests
    user_ids = set()
    for request_id, request_data in pending_requests.items():
        user_ids.add(request_data['user_id'])
    
    if not user_ids:
        await message.reply_text("⚠️ No users found for broadcasting.")
        return
    
    sent_count = 0
    failed_count = 0
    
    # Send status message
    status_msg = await message.reply_text(f"🔄 Broadcasting message to {len(user_ids)} users...")
    
    # Send message to each user
    for user_id in user_ids:
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"📢 **ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ**\n\n{broadcast_message}"
            )
            sent_count += 1
            
            # Update status every 5 users
            if sent_count % 5 == 0:
                await status_msg.edit_text(f"🔄 Broadcasting: {sent_count}/{len(user_ids)} completed...")
            
            # Sleep to avoid flood limits
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            failed_count += 1
    
    await status_msg.edit_text(f"✅ Broadcast completed!\n\n"
                               f"📨 Sent: {sent_count}\n"
                               f"❌ Failed: {failed_count}")

# Flask web server for keeping the bot alive
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "TeraBox Downloader Bot is Running!"

def run_flask():
    app_web.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# Handle additional callback queries for approval/rejection directly from channel
@app.on_callback_query(filters.regex(r'^(approve|reject)_'))
async def handle_admin_action_callback(client, callback_query):
    user_id = callback_query.from_user.id
    
    # Check if user is admin
    if not await is_admin(user_id):
        await callback_query.answer("⚠️ You are not authorized to perform this action.", show_alert=True)
        return
    
    # Extract action and request ID
    action, request_id = callback_query.data.split('_', 1)
    
    if request_id not in pending_requests:
        await callback_query.answer(f"⚠️ Request ID {request_id} not found.", show_alert=True)
        return
    
    request_data = pending_requests[request_id]
    requester_id = request_data['user_id']
    
    if action == "approve":
        # Handle approval
        try:
            # Update request status
            pending_requests[request_id]['status'] = 'approved'
            
            # Notify user
            await client.send_message(
                chat_id=requester_id,
                text=f"✅ **ʏᴏᴜʀ ᴠɪᴅᴇᴏ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!**\n\n"
                     f"🆔 **ʀᴇǫᴜᴇsᴛ ɪᴅ:** `{request_id}`\n"
                     f"📝 **ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:** {request_data['description']}\n\n"
                     f"⏳ ᴡᴇ ᴡɪʟʟ ᴘʀᴏᴄᴇss ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ sᴏᴏɴ ᴀɴᴅ ɢᴇᴛ ʙᴀᴄᴋ ᴛᴏ ʏᴏᴜ."
            )
            
            # Update original message
            approve_button = InlineKeyboardButton("✅ ᴀᴘᴘʀᴏᴠᴇᴅ", callback_data=f"approved_{request_id}")
            view_button = InlineKeyboardButton("👁️ ᴠɪᴇᴡ", callback_data=f"view_{request_id}")
            
            new_markup = InlineKeyboardMarkup([[approve_button, view_button]])
            await callback_query.edit_message_reply_markup(new_markup)
            
            await callback_query.answer("✅ Request approved and user notified", show_alert=True)
        except Exception as e:
            logger.error(f"Error in approval process: {e}")
            await callback_query.answer(f"❌ Error: {str(e)[:200]}", show_alert=True)
    
    elif action == "reject":
        # Open dialog for rejection reason
        await callback_query.answer("Please use /reject command with reason to reject this request.", show_alert=True)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "**📚 ʜᴇʟᴘ ɢᴜɪᴅᴇ**\n\n"
        "• Send any **TeraBox link** to download the file\n"
        "• Use the **Request Video** button to request videos\n"
        "• Join our channel for updates and new content\n\n"
        "**📝 ʜᴏᴡ ᴛᴏ ʀᴇǫᴜᴇsᴛ ᴀ ᴠɪᴅᴇᴏ:**\n"
        "1. Click on 'Request Video' button\n"
        "2. Send a screenshot of the video\n"
        "3. Provide name/description of the video\n"
        "4. Wait for admin approval\n\n"
        "**💡 sᴜᴘᴘᴏʀᴛᴇᴅ ᴛᴇʀᴀʙᴏx ᴅᴏᴍᴀɪɴs:**\n"
        "terabox.com, nephobox.com, 4funbox.com, and more..."
    )
    
    # Create buttons
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ ❤️", url="https://t.me/dailydiskwala")
    request_button = InlineKeyboardButton("ʀᴇǫᴜᴇsᴛ ᴠɪᴅᴇᴏ 🎬", callback_data="request_video")
    
    reply_markup = InlineKeyboardMarkup([
        [join_button],
        [request_button]
    ])
    
    await message.reply_text(help_text, reply_markup=reply_markup)

# Main function to run the bot
async def main():
    # Start user client if available
    global user
    if user:
        try:
            await user.start()
            logger.info("User client started successfully")
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            user = None
    
    # Start the Flask thread for keeping the bot alive
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start the bot
    await app.start()
    logger.info("Bot started successfully!")
    
    # Keep the bot running
    await asyncio.sleep(float("inf"))

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
