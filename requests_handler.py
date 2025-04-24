# requests_handler.py
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.enums import ChatMemberStatus
import os
import logging
import time
from datetime import datetime
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(name)s - %(levelname)s] %(message)s - %(filename)s:%(lineno)d"
)
logger = logging.getLogger(__name__)

# Constants
REQUEST_CHANNEL_ID = os.environ.get('REQUEST_CHANNEL_ID', '-1002541647242')
if len(REQUEST_CHANNEL_ID) == 0:
    logging.error("REQUEST_CHANNEL_ID variable is missing!")
else:
    REQUEST_CHANNEL_ID = int(REQUEST_CHANNEL_ID)

ADMIN_IDS = os.environ.get('ADMIN_IDS', '1352497419').split(',')
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS if admin_id.strip()]
if not ADMIN_IDS:
    logging.error("ADMIN_IDS variable is missing or invalid!")

# Maintain a cache of pending requests
pending_requests = {}

async def is_admin(client, user_id):
    """Check if a user is an admin"""
    return user_id in ADMIN_IDS

async def is_user_member(client, user_id, fsub_id):
    """Check if a user is a member of the force subscription channel"""
    try:
        member = await client.get_chat_member(fsub_id, user_id)
        if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"Error checking membership status for user {user_id}: {e}")
        return False

def register_request_handlers(app, FSUB_ID):
    """Register all handlers related to video requests"""

    @app.on_message(filters.command("request"))
    async def request_command(client, message):
        """Handle the /request command"""
        user_id = message.from_user.id
        
        # Check if user is subscribed
        is_member = await is_user_member(client, user_id, FSUB_ID)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        await message.reply_text(
            "📽️ **Send a screenshot or image of the video you want to request.**\n\n"
            "Please include the following details in the caption:\n"
            "1. Video name/title\n"
            "2. Source (if any)\n"
            "3. Any additional information\n\n"
            "Example: `Avengers Endgame (2019) | HD Quality | Marvel`"
        )

    @app.on_message(filters.photo & ~filters.channel)
    async def handle_request_photo(client, message):
        """Handle photos sent by users as video requests"""
        user_id = message.from_user.id
        
        # Check if user is subscribed
        is_member = await is_user_member(client, user_id, FSUB_ID)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Get caption or prompt user to add details
        caption = message.caption or ""
        if not caption:
            await message.reply_text(
                "❌ Please add a caption with details about the video you're requesting.\n\n"
                "Include: video name, quality, source, etc."
            )
            return
        
        # Prepare request message
        user_mention = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        request_text = (
            f"🎬 <b>New Video Request</b> 🎬\n\n"
            f"<b>Requested by:</b> {user_mention}\n"
            f"<b>User ID:</b> <code>{user_id}</code>\n"
            f"<b>Time:</b> {request_time}\n\n"
            f"<b>Request Details:</b>\n{caption}\n\n"
            f"<b>Status:</b> Pending Review"
        )
        
        # Buttons for admin actions
        approve_button = InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}")
        reject_button = InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
        markup = InlineKeyboardMarkup([[approve_button, reject_button]])
        
        # Forward request to admin channel
        try:
            sent_message = await client.send_photo(
                chat_id=REQUEST_CHANNEL_ID,
                photo=message.photo.file_id,
                caption=request_text,
                reply_markup=markup
            )
            
            # Save request info
            request_id = sent_message.id
            pending_requests[f"{user_id}_{request_id}"] = {
                "user_id": user_id,
                "request_id": request_id,
                "request_time": request_time,
                "details": caption,
                "status": "pending"
            }
            
            # Confirm to user
            await message.reply_text(
                "✅ Your video request has been submitted successfully!\n\n"
                "You will be notified when your request is processed."
            )
            
            logger.info(f"New video request from user {user_id} (Request ID: {request_id})")
            
        except Exception as e:
            logger.error(f"Error forwarding request: {e}")
            await message.reply_text("❌ Failed to submit your request. Please try again later.")

    @app.on_callback_query(filters.regex(r"^(approve|reject)_(\d+)$"))
    async def handle_request_action(client, callback_query):
        """Handle admin actions on user requests"""
        user_id = callback_query.from_user.id
        
        # Check if user is admin
        if not await is_admin(client, user_id):
            await callback_query.answer("You are not authorized to perform this action!", show_alert=True)
            return
        
        action, requester_id = callback_query.data.split("_")
        requester_id = int(requester_id)
        request_id = callback_query.message.id
        
        request_key = f"{requester_id}_{request_id}"
        if request_key not in pending_requests:
            await callback_query.answer("Request information not found!", show_alert=True)
            return
        
        # Update request status
        if action == "approve":
            pending_requests[request_key]["status"] = "approved"
            
            # Update message in admin channel
            await callback_query.edit_message_caption(
                caption=callback_query.message.caption.replace("Status: Pending Review", "Status: ✅ Approved"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬆️ Upload Video", callback_data=f"upload_{requester_id}_{request_id}")]
                ])
            )
            
            # Notify user about approval
            try:
                await client.send_message(
                    chat_id=requester_id,
                    text="✅ Good news! Your video request has been approved and is being processed.\n\n"
                         "We'll notify you when the video is ready for download."
                )
                await callback_query.answer("Request approved and user notified!", show_alert=True)
            except Exception as e:
                logger.error(f"Failed to notify user {requester_id}: {e}")
                await callback_query.answer("Request approved but failed to notify user", show_alert=True)
            
        elif action == "reject":
            pending_requests[request_key]["status"] = "rejected"
            
            # Update message in admin channel
            await callback_query.edit_message_caption(
                caption=callback_query.message.caption.replace("Status: Pending Review", "Status: ❌ Rejected"),
                reply_markup=None
            )
            
            # Notify user about rejection
            try:
                await client.send_message(
                    chat_id=requester_id,
                    text="❌ We're sorry, but your video request could not be fulfilled at this time.\n\n"
                         "You can try requesting a different video or provide more details."
                )
                await callback_query.answer("Request rejected and user notified!", show_alert=True)
            except Exception as e:
                logger.error(f"Failed to notify user {requester_id}: {e}")
                await callback_query.answer("Request rejected but failed to notify user", show_alert=True)

    @app.on_callback_query(filters.regex(r"^upload_(\d+)_(\d+)$"))
    async def handle_upload_action(client, callback_query):
        """Handle video upload after approval"""
        admin_id = callback_query.from_user.id
        
        # Check if user is admin
        if not await is_admin(client, admin_id):
            await callback_query.answer("You are not authorized to perform this action!", show_alert=True)
            return
        
        _, requester_id, request_id = callback_query.data.split("_")
        requester_id = int(requester_id)
        request_id = int(request_id)
        
        # Ask admin to provide the video link
        await callback_query.message.reply_text(
            f"Please provide the Terabox link for request ID: {request_id}\n\n"
            f"Reply to this message with the link to automatically notify the user."
        )
        
        # Update callback message
        await callback_query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Processing", callback_data=f"processing_{requester_id}")]
            ])
        )
        
        await callback_query.answer("Please provide the video link", show_alert=True)

    @app.on_message(filters.reply & filters.regex(r'https?://'))
    async def handle_video_link_reply(client, message):
        """Handle admin's reply with video link"""
        user_id = message.from_user.id
        
        # Check if user is admin
        if not await is_admin(client, user_id):
            return
        
        # Check if the message is replying to our request for link
        if not message.reply_to_message or not message.reply_to_message.text or "Please provide the Terabox link for request ID" not in message.reply_to_message.text:
            return
        
        # Extract request ID from the original message
        try:
            request_text = message.reply_to_message.text
            request_id_part = request_text.split("request ID: ")[1].split("\n")[0]
            request_id = int(request_id_part)
            
            # Find the requester ID
            requester_id = None
            for key, value in pending_requests.items():
                if value["request_id"] == request_id:
                    requester_id = value["user_id"]
                    break
                    
            if not requester_id:
                await message.reply_text("❌ Couldn't find the requester information.")
                return
                
            # Get the video link
            video_link = message.text.strip()
            
            # Notify user with the video link
            try:
                await client.send_message(
                    chat_id=requester_id,
                    text=f"🎬 **Your requested video is ready!**\n\n"
                         f"You can download it directly from our bot by sending this link:\n\n"
                         f"`{video_link}`\n\n"
                         f"Just paste the link in our chat to start downloading!"
                )
                
                # Update admin
                await message.reply_text(f"✅ User has been notified about their video!")
                
                # Update request status
                for key, value in pending_requests.items():
                    if value["request_id"] == request_id:
                        pending_requests[key]["status"] = "completed"
                        break
                
                # Update the original message in the requests channel
                try:
                    await client.edit_message_caption(
                        chat_id=REQUEST_CHANNEL_ID,
                        message_id=request_id,
                        caption=await client.get_messages(REQUEST_CHANNEL_ID, request_id).caption.replace(
                            "Status: ✅ Approved", "Status: ✅ Completed"
                        ),
                        reply_markup=None
                    )
                except Exception as e:
                    logger.error(f"Failed to update request message: {e}")
                    
            except Exception as e:
                logger.error(f"Failed to notify user {requester_id}: {e}")
                await message.reply_text(f"❌ Failed to notify user: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error processing video link reply: {e}")
            await message.reply_text(f"❌ Error: {str(e)}")

    @app.on_message(filters.command("myrequests"))
    async def my_requests_command(client, message):
        """Show user's requests and their status"""
        user_id = message.from_user.id
        
        # Check if user is subscribed
        is_member = await is_user_member(client, user_id, FSUB_ID)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/jetmirror")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await message.reply_text("ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", reply_markup=reply_markup)
            return
        
        # Find user's requests
        user_requests = []
        for key, value in pending_requests.items():
            if value["user_id"] == user_id:
                user_requests.append(value)
        
        if not user_requests:
            await message.reply_text("You haven't made any video requests yet.")
            return
        
        # Format requests info
        response = "🎬 **Your Video Requests**\n\n"
        for req in user_requests:
            status_emoji = {
                "pending": "⏳",
                "approved": "✅",
                "rejected": "❌",
                "completed": "🎉"
            }.get(req["status"], "⏳")
            
            response += (
                f"**Request ID:** `{req['request_id']}`\n"
                f"**Requested on:** {req['request_time']}\n"
                f"**Details:** {req['details'][:50]}...\n"
                f"**Status:** {status_emoji} {req['status'].capitalize()}\n\n"
            )
        
        await message.reply_text(response)

    @app.on_message(filters.command("allrequests") & filters.user(ADMIN_IDS))
    async def all_requests_command(client, message):
        """Show all requests for admins"""
        user_id = message.from_user.id
        
        # Verify admin
        if not await is_admin(client, user_id):
            await message.reply_text("This command is only available to admins.")
            return
        
        if not pending_requests:
            await message.reply_text("No video requests found in the system.")
            return
        
        # Format requests info
        response = "🎬 **All Video Requests**\n\n"
        for key, value in pending_requests.items():
            status_emoji = {
                "pending": "⏳",
                "approved": "✅",
                "rejected": "❌",
                "completed": "🎉"
            }.get(value["status"], "⏳")
            
            user_mention = f"<a href='tg://user?id={value['user_id']}'>{value['user_id']}</a>"
            
            response += (
                f"**Request ID:** `{value['request_id']}`\n"
                f"**User:** {user_mention}\n"
                f"**Requested on:** {value['request_time']}\n"
                f"**Details:** {value['details'][:50]}...\n"
                f"**Status:** {status_emoji} {value['status'].capitalize()}\n\n"
            )
            
            # Split long messages
            if len(response) > 3500:
                await message.reply_text(response)
                response = "🎬 **All Video Requests (Continued)**\n\n"
        
        if response != "🎬 **All Video Requests (Continued)**\n\n":
            await message.reply_text(response)

    return app
