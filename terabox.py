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
from pyrogram.errors import FloodWait, UserNotParticipant, ChatAdminRequired
import time
import urllib.parse
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify
from threading import Thread
import aiohttp
import aiofiles
from typing import Optional, Dict, Any
import hashlib

# Load environment variables
load_dotenv('config.env', override=True)

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(name)s - %(levelname)s] %(message)s - %(filename)s:%(lineno)d",
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Reduce pyrogram log verbosity
for log_name in ["pyrogram.session", "pyrogram.connection", "pyrogram.dispatcher"]:
    logging.getLogger(log_name).setLevel(logging.ERROR)

class Config:
    """Configuration class to manage all environment variables"""
    
    def __init__(self):
        self.API_ID = self._get_env_var('TELEGRAM_API')
        self.API_HASH = self._get_env_var('TELEGRAM_HASH')
        self.BOT_TOKEN = self._get_env_var('BOT_TOKEN')
        self.DUMP_CHAT_ID = int(self._get_env_var('DUMP_CHAT_ID'))
        self.FSUB_ID = int(self._get_env_var('FSUB_ID'))
        self.BIGG_BOSS_CHANNEL_ID = -1002922594148
        self.ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip()]
        self.USER_SESSION_STRING = os.environ.get('USER_SESSION_STRING')
        self.SERVER_URL = os.environ.get('SERVER_URL', 'https://historic-frances-school1660440-b73ae1e5.koyeb.app')
        self.SPLIT_SIZE = 2093796556  # ~2GB
        
        # Aria2 configuration
        self.ARIA2_HOST = "http://localhost"
        self.ARIA2_PORT = 6800
        self.ARIA2_SECRET = ""
        
        # API endpoints for TeraBox extraction
        self.API_ENDPOINTS = [
            "https://my-noor-queen-api.woodmirror.workers.dev/api?url={}",
            "https://terabox-api-latest.vercel.app/api?url={}",
            "https://tera-api-enhanced.herokuapp.com/api?url={}"
        ]
        
    def _get_env_var(self, key: str) -> str:
        value = os.environ.get(key, '')
        if not value:
            logger.error(f"{key} variable is missing! Exiting now")
            exit(1)
        return value

# Global configuration
config = Config()

class Aria2Manager:
    """Enhanced Aria2 download manager with better error handling"""
    
    def __init__(self):
        self.api = None
        self.initialize()
        
    def initialize(self):
        """Initialize Aria2 API with enhanced settings"""
        try:
            client = Aria2Client(
                host=config.ARIA2_HOST,
                port=config.ARIA2_PORT,
                secret=config.ARIA2_SECRET
            )
            self.api = Aria2API(client)
            
            # Enhanced options for better performance
            options = {
                "max-tries": "50",
                "retry-wait": "2",
                "continue": "true",
                "allow-overwrite": "true",
                "min-split-size": "1M",
                "split": "16",
                "max-connection-per-server": "16",
                "max-concurrent-downloads": "5",  # Reduced for stability
                "optimize-concurrent-downloads": "true",
                "async-dns": "true",
                "file-allocation": "none",
                "disk-cache": "64M",
                "check-certificate": "false",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            self.api.set_global_options(options)
            logger.info("Aria2 initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Aria2: {e}")
            self.api = None
    
    def add_download(self, url: str, options: Dict[str, Any] = None):
        """Add a download with error handling"""
        if not self.api:
            raise Exception("Aria2 not initialized")
        
        try:
            return self.api.add_uris([url], options=options)
        except Exception as e:
            logger.error(f"Failed to add download: {e}")
            raise
    
    def get_active_downloads(self):
        """Get number of active downloads"""
        if not self.api:
            return 0
        try:
            return len(self.api.get_downloads())
        except:
            return 0

class TeraBoxExtractor:
    """Enhanced TeraBox link extractor with multiple API fallbacks"""
    
    VALID_DOMAINS = [
        'terabox.com', 'nephobox.com', '4funbox.com', 'mirrobox.com', 
        'momorybox.com', 'teraboxapp.com', '1024tera.com', '1024terabox.com',
        'terabox.app', 'gibibox.com', 'goaibox.com', 'terasharelink.com', 
        'teraboxlink.com', 'terafileshare.com'
    ]
    
    def __init__(self):
        self.session = None
        
    async def create_session(self):
        """Create aiohttp session if not exists"""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            self.session = aiohttp.ClientSession(timeout=timeout, headers=headers)
    
    async def close_session(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()
    
    def is_valid_url(self, url: str) -> bool:
        """Check if URL is from a valid TeraBox domain"""
        try:
            parsed_url = urlparse(url)
            return any(parsed_url.netloc.endswith(domain) for domain in self.VALID_DOMAINS)
        except:
            return False
    
    async def extract_direct_link(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract direct download link with multiple API fallback"""
        await self.create_session()
        
        for api_url_template in config.API_ENDPOINTS:
            try:
                api_url = api_url_template.format(urllib.parse.quote(url, safe=''))
                logger.info(f"Trying API: {api_url}")
                
                async with self.session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Handle different API response formats
                        if self._is_valid_response(data):
                            return self._extract_file_info(data)
                        
            except Exception as e:
                logger.warning(f"API failed {api_url_template}: {e}")
                continue
        
        logger.error("All API endpoints failed")
        return None
    
    def _is_valid_response(self, data: Dict[str, Any]) -> bool:
        """Check if API response is valid"""
        return (
            data.get("status") == "✅ Successfully" and 
            "download_link" in data
        ) or (
            data.get("success") is True and
            "direct_link" in data
        )
    
    def _extract_file_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract file information from API response"""
        # Handle different response formats
        direct_url = data.get("download_link") or data.get("direct_link")
        filename = data.get("file_name") or data.get("name", "Unknown")
        size = data.get("file_size") or data.get("size", "Unknown")
        size_bytes = data.get("size_bytes") or data.get("size_in_bytes", 0)
        
        return {
            "direct_url": direct_url,
            "filename": filename,
            "size": size,
            "size_bytes": size_bytes
        }

class ProgressTracker:
    """Enhanced progress tracking with better formatting"""
    
    PROGRESS_BAR_FILLED = "█"
    PROGRESS_BAR_EMPTY = "░"
    PROGRESS_BAR_LENGTH = 15
    
    @staticmethod
    def format_size(size: int) -> str:
        """Format size in human readable format"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"
    
    @staticmethod
    def get_progress_bar(percentage: float) -> str:
        """Generate progress bar"""
        completed_length = int(percentage / 100 * ProgressTracker.PROGRESS_BAR_LENGTH)
        return (ProgressTracker.PROGRESS_BAR_FILLED * completed_length + 
                ProgressTracker.PROGRESS_BAR_EMPTY * (ProgressTracker.PROGRESS_BAR_LENGTH - completed_length))
    
    @staticmethod
    def format_time(seconds: float) -> str:
        """Format time duration"""
        if hasattr(seconds, 'total_seconds'):
            seconds = seconds.total_seconds()
        
        try:
            seconds = max(0, float(seconds))
        except (ValueError, TypeError):
            seconds = 0
        
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes, secs = divmod(seconds, 60)
            return f"{minutes:.0f}m {secs:.0f}s"
        else:
            hours, remainder = divmod(seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            return f"{hours:.0f}h {minutes:.0f}m {secs:.0f}s"

class SafeMessaging:
    """Safe messaging with FloodWait handling and retry logic"""
    
    MAX_RETRIES = 3
    BASE_DELAY = 1
    
    @classmethod
    async def send_message(cls, client: Client, chat_id: int, text: str, 
                          reply_markup=None, retries: int = 0) -> Optional[Message]:
        """Safely send message with exponential backoff"""
        try:
            return await client.send_message(chat_id, text, reply_markup=reply_markup)
        except FloodWait as e:
            if retries < cls.MAX_RETRIES:
                logger.warning(f"FloodWait: {e.value}s (retry {retries + 1})")
                await asyncio.sleep(e.value)
                return await cls.send_message(client, chat_id, text, reply_markup, retries + 1)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            if retries < cls.MAX_RETRIES:
                delay = cls.BASE_DELAY * (2 ** retries)
                await asyncio.sleep(delay)
                return await cls.send_message(client, chat_id, text, reply_markup, retries + 1)
        return None
    
    @classmethod
    async def edit_message(cls, message: Message, text: str, reply_markup=None, 
                          retries: int = 0) -> Optional[Message]:
        """Safely edit message with exponential backoff"""
        try:
            return await message.edit_text(text, reply_markup=reply_markup)
        except FloodWait as e:
            if retries < cls.MAX_RETRIES:
                logger.warning(f"FloodWait on edit: {e.value}s (retry {retries + 1})")
                await asyncio.sleep(e.value)
                return await cls.edit_message(message, text, reply_markup, retries + 1)
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            if retries < cls.MAX_RETRIES:
                delay = cls.BASE_DELAY * (2 ** retries)
                await asyncio.sleep(delay)
                return await cls.edit_message(message, text, reply_markup, retries + 1)
        return None
    
    @classmethod
    async def send_video(cls, client: Client, chat_id: int, video, 
                        caption=None, reply_markup=None, progress=None, 
                        retries: int = 0) -> Optional[Message]:
        """Safely send video with exponential backoff"""
        try:
            return await client.send_video(
                chat_id, video, caption=caption, 
                reply_markup=reply_markup, progress=progress
            )
        except FloodWait as e:
            if retries < cls.MAX_RETRIES:
                logger.warning(f"FloodWait on video: {e.value}s (retry {retries + 1})")
                await asyncio.sleep(e.value)
                return await cls.send_video(
                    client, chat_id, video, caption, reply_markup, progress, retries + 1
                )
        except Exception as e:
            logger.error(f"Error sending video: {e}")
            if retries < cls.MAX_RETRIES:
                delay = cls.BASE_DELAY * (2 ** retries)
                await asyncio.sleep(delay)
                return await cls.send_video(
                    client, chat_id, video, caption, reply_markup, progress, retries + 1
                )
        return None

class BotManager:
    """Main bot manager class"""
    
    def __init__(self):
        self.app = Client("jetbot", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)
        self.aria2 = Aria2Manager()
        self.extractor = TeraBoxExtractor()
        self.video_links = {}  # Store video links for play buttons
        
    async def is_user_member(self, user_id: int) -> bool:
        """Check if user is member of required channel"""
        try:
            member = await self.app.get_chat_member(config.FSUB_ID, user_id)
            return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
        except (UserNotParticipant, ChatAdminRequired):
            return False
        except Exception as e:
            logger.error(f"Error checking membership for user {user_id}: {e}")
            return False
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in config.ADMIN_IDS
    
    def create_play_button_markup(self, download_url: str, filename: str, file_id: str = None):
        """Create inline keyboard with play video button and web app player"""
        encoded_url = urllib.parse.quote(download_url, safe='')
        encoded_filename = urllib.parse.quote(filename, safe='')
        
        # Direct play button
        play_button = InlineKeyboardButton("🎬 Play Video", url=download_url)
        
        # Web app player button
        player_url = f"{config.SERVER_URL}/player?video={encoded_url}&title={encoded_filename}"
        webapp_button = InlineKeyboardButton("📱 Open Player", web_app=WebAppInfo(url=player_url))
        
        # Store the video link for callback queries
        if file_id:
            self.video_links[file_id] = {
                'url': download_url,
                'filename': filename,
                'timestamp': datetime.now()
            }
        
        return InlineKeyboardMarkup([[play_button], [webapp_button]])
    
    async def handle_download_process(self, client: Client, message: Message, url: str):
        """Handle the complete download process"""
        user_id = message.from_user.id
        
        # Create status message
        status_message = await SafeMessaging.send_message(
            client, message.chat.id, "🔍 Extracting file info..."
        )
        if not status_message:
            return
        
        # Extract direct download link
        link_info = await self.extractor.extract_direct_link(url)
        if not link_info or not link_info.get("direct_url"):
            await SafeMessaging.edit_message(
                status_message,
                "❌ Failed to extract download link. "
                "The link might be invalid, expired, or temporarily unavailable. "
                "Please try again later or check if the link is correct."
            )
            return
        
        direct_url = link_info["direct_url"]
        filename = link_info.get("filename", "Unknown")
        size_text = link_info.get("size", "Unknown")
        
        await SafeMessaging.edit_message(
            status_message,
            f"✅ File info extracted!\n\n"
            f"📁 Filename: {filename}\n"
            f"📏 Size: {size_text}\n\n"
            f"⏳ Starting download..."
        )
        
        # Start download
        try:
            download = self.aria2.add_download(direct_url)
            download.update()
        except Exception as e:
            logger.error(f"Download start error: {e}")
            await SafeMessaging.edit_message(
                status_message, f"❌ Failed to start download: {str(e)}"
            )
            return
        
        # Monitor download progress
        await self._monitor_download_progress(download, status_message, user_id, message.from_user.first_name)
        
        # Handle upload after download completion
        if download.is_complete:
            await self._handle_upload(client, download, status_message, user_id, 
                                    message.from_user.first_name, direct_url, filename, message.chat.id)
    
    async def _monitor_download_progress(self, download, status_message, user_id, user_name):
        """Monitor download progress with enhanced updates"""
        start_time = datetime.now()
        previous_speed = 0
        update_interval = 10
        last_update = time.time()
        
        while not download.is_complete:
            await asyncio.sleep(2)
            current_time = time.time()
            
            if current_time - last_update >= update_interval:
                download.update()
                progress = download.progress
                progress_bar = ProgressTracker.get_progress_bar(progress)
                
                elapsed_time = datetime.now() - start_time
                elapsed_seconds = elapsed_time.total_seconds()
                
                # Calculate ETA safely
                try:
                    eta_display = ProgressTracker.format_time(download.eta)
                except Exception:
                    eta_display = "Calculating..."
                
                status_text = (
                    f"🔽 <b>DOWNLOADING</b>\n\n"
                    f"📁 <b>{download.name}</b>\n\n"
                    f"⏳ <b>Progress:</b> {progress:.1f}%\n"
                    f"{progress_bar} \n"
                    f"📊 <b>Speed:</b> {ProgressTracker.format_size(download.download_speed)}/s\n"
                    f"📦 <b>Downloaded:</b> {ProgressTracker.format_size(download.completed_length)} of {ProgressTracker.format_size(download.total_length)}\n"
                    f"⏱️ <b>ETA:</b> {eta_display}\n"
                    f"⏰ <b>Elapsed:</b> {ProgressTracker.format_time(elapsed_seconds)}\n\n"
                    f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{user_name}</a>\n"
                )
                
                await SafeMessaging.edit_message(status_message, status_text)
                last_update = current_time
    
    async def _handle_upload(self, client, download, status_message, user_id, user_name, 
                           direct_url, filename, chat_id):
        """Handle file upload to Telegram"""
        start_time = datetime.now()
        file_path = download.files[0].path
        download_time = (datetime.now() - start_time).total_seconds()
        avg_speed = download.total_length / download_time if download_time > 0 else 0
        
        await SafeMessaging.edit_message(
            status_message,
            f"✅ Download completed!\n\n"
            f"📁 <b>{download.name}</b>\n"
            f"📦 <b>Size:</b> {ProgressTracker.format_size(download.total_length)}\n"
            f"⏱️ <b>Time taken:</b> {ProgressTracker.format_time(download_time)}\n"
            f"📊 <b>Avg. Speed:</b> {ProgressTracker.format_size(avg_speed)}/s\n\n"
            f"📤 <b>Starting upload to Telegram...</b>"
        )
        
        # Prepare caption and markup
        caption = (
            f"✨ {download.name}\n"
            f"👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : <a href='tg://user?id={user_id}'>{user_name}</a>\n"
            f"📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}\n\n"
            "[Telugu stuff ❤️🚀](https://t.me/dailydiskwala)"
        )
        
        play_markup = self.create_play_button_markup(direct_url, filename)
        
        # Upload file
        try:
            await SafeMessaging.edit_message(
                status_message,
                f"📤 <b>UPLOADING TO TELEGRAM</b>\n\n"
                f"📁 <b>{download.name}</b>\n"
                f"⏳ <b>Starting upload...</b>"
            )
            
            # Upload to dump channel first
            sent = await SafeMessaging.send_video(
                client, config.DUMP_CHAT_ID, file_path,
                caption=caption, reply_markup=play_markup
            )
            
            # Send to user
            if sent:
                await SafeMessaging.send_video(
                    client, chat_id, sent.video.file_id,
                    caption=caption, reply_markup=play_markup
                )
            
            # Clean up file
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # Update final status
            total_time = (datetime.now() - start_time).total_seconds()
            await SafeMessaging.edit_message(
                status_message,
                f"✅ <b>PROCESS COMPLETED</b>\n\n"
                f"📁 <b>{download.name}</b>\n"
                f"📦 <b>Size:</b> {ProgressTracker.format_size(download.total_length)}\n"
                f"⏱️ <b>Total time:</b> {ProgressTracker.format_time(total_time)}\n\n"
                f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{user_name}</a>\n"
            )
            
        except Exception as e:
            logger.error(f"Upload error: {e}")
            await SafeMessaging.edit_message(
                status_message,
                f"❌ Upload failed: {str(e)}\n\n"
                "Please try again later."
            )
        
        # Cleanup aria2 download
        try:
            self.aria2.api.remove([download], force=True, files=True)
        except Exception as e:
            logger.error(f"Aria2 cleanup error: {e}")

# Initialize bot manager
bot_manager = BotManager()
app = bot_manager.app

# Command handlers
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    """Enhanced start command with better UI"""
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/dailydiskwala")
    developer_button = InlineKeyboardButton("ᴅᴇᴠᴇʟᴏᴘᴇʀ ⚡️", url="https://t.me/terao2")
    bigg_boss_button = InlineKeyboardButton("Bigg Boss", url="https://t.me/+y0slgRpoKiNhYzg1")
    telugu_videos_button = InlineKeyboardButton("Telugu Videos", url="https://t.me/+y0slgRpoKiNhYzg1")
    
    user_mention = message.from_user.mention
    
    # Show admin panel button only to admins
    if bot_manager.is_admin(message.from_user.id):
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
    
    welcome_text = (
        f"ᴡᴇʟᴄᴏᴍᴇ, {user_mention}.\n\n"
        f"🌟 ɪ ᴀᴍ ᴀ ᴛᴇʀᴀʙᴏx ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ. sᴇɴᴅ ᴍᴇ ᴀɴʏ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ "
        f"ɪ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴡɪᴛʜɪɴ ғᴇᴡ sᴇᴄᴏɴᴅs ᴀɴᴅ sᴇɴᴅ ɪᴛ ᴛᴏ ʏᴏᴜ ✨.\n\n"
        f"🚀 **Features:**\n"
        f"• Fast downloads with aria2\n"
        f"• Multiple API fallbacks\n"
        f"• Progress tracking\n"
        f"• Play button for videos\n"
        f"• Reliable error handling"
    )
    
    await SafeMessaging.send_message(client, message.chat.id, welcome_text, reply_markup)

@app.on_message(filters.text)
async def handle_text_message(client: Client, message: Message):
    """Handle text messages (TeraBox links)"""
    if not message.from_user or not message.text:
        return
    
    # Skip commands except speedtest
    if message.text.startswith('/') and not message.text.startswith('/speedtest'):
        return
    
    user_id = message.from_user.id
    
    # Check membership for non-admins
    if not bot_manager.is_admin(user_id):
        is_member = await bot_manager.is_user_member(user_id)
        if not is_member:
            join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/terao2")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            await SafeMessaging.send_message(
                client, message.chat.id, 
                "ʏᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴍʏ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ.", 
                reply_markup
            )
            return
    
    # Extract URL from message
    url = None
    for word in message.text.split():
        if bot_manager.extractor.is_valid_url(word):
            url = word
            break
    
    if not url:
        await SafeMessaging.send_message(
            client, message.chat.id, 
            "Please provide a valid TeraBox link from supported domains."
        )
        return
    
    # Handle download process
    await bot_manager.handle_download_process(client, message, url)

# Admin callback handlers
@app.on_callback_query(filters.regex("admin_panel"))
async def admin_panel_callback(client: Client, callback_query):
    if not bot_manager.is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ You are not authorized to access admin panel.", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Upload to Bigg Boss", callback_data="upload_bigg_boss")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("🧹 Clean Downloads", callback_data="clean_downloads")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ])
    
    await SafeMessaging.edit_message(
        callback_query.message,
        "⚙️ **ADMIN PANEL**\n\nChoose an option:",
        keyboard
    )

@app.on_callback_query(filters.regex("upload_bigg_boss"))
async def upload_bigg_boss_callback(client: Client, callback_query):
    if not bot_manager.is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    await SafeMessaging.edit_message(
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
    if not bot_manager.is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    # Get bot statistics
    active_downloads = bot_manager.aria2.get_active_downloads()
    stored_video_links = len(bot_manager.video_links)
    
    # Clean old video links (older than 24 hours)
    current_time = datetime.now()
    expired_links = [
        k for k, v in bot_manager.video_links.items()
        if (current_time - v['timestamp']).total_seconds() > 86400
    ]
    for link_id in expired_links:
        del bot_manager.video_links[link_id]
    
    stats_text = (
        "📊 **BOT STATISTICS**\n\n"
        f"🔄 Active Downloads: {active_downloads}\n"
        f"📁 Stored Video Links: {stored_video_links}\n"
        f"📱 User Client: {'❌ Disabled' if not config.USER_SESSION_STRING else '✅ Active'}\n"
        f"🤖 Bot Status: ✅ Online\n"
        f"⚠️ FloodWait Protection: ✅ Active\n"
        f"🔗 API Endpoints: {len(config.API_ENDPOINTS)} configured\n"
        f"📋 Aria2 Status: {'✅ Connected' if bot_manager.aria2.api else '❌ Disconnected'}\n"
        f"🧹 Cleaned expired links: {len(expired_links)}"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="bot_stats")],
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]
    ])
    
    await SafeMessaging.edit_message(callback_query.message, stats_text, keyboard)

@app.on_callback_query(filters.regex("clean_downloads"))
async def clean_downloads_callback(client: Client, callback_query):
    if not bot_manager.is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    try:
        if bot_manager.aria2.api:
            # Remove completed and failed downloads
            downloads = bot_manager.aria2.api.get_downloads()
            removed_count = 0
            
            for download in downloads:
                if download.is_complete or download.has_failed:
                    try:
                        bot_manager.aria2.api.remove([download], force=True, files=True)
                        removed_count += 1
                    except Exception as e:
                        logger.error(f"Failed to remove download {download.gid}: {e}")
            
            await callback_query.answer(f"✅ Cleaned {removed_count} downloads.", show_alert=True)
        else:
            await callback_query.answer("❌ Aria2 not connected.", show_alert=True)
            
    except Exception as e:
        logger.error(f"Clean downloads error: {e}")
        await callback_query.answer("❌ Failed to clean downloads.", show_alert=True)

@app.on_callback_query(filters.regex("back_to_main"))
async def back_to_main_callback(client: Client, callback_query):
    # Recreate the start message
    user_mention = callback_query.from_user.mention
    join_button = InlineKeyboardButton("ᴊᴏɪɴ ❤️🚀", url="https://t.me/dailydiskwala")
    developer_button = InlineKeyboardButton("ᴅᴇᴠᴇʟᴏᴘᴇʀ ⚡️", url="https://t.me/terao2")
    bigg_boss_button = InlineKeyboardButton("Bigg Boss", url="https://t.me/+y0slgRpoKiNhYzg1")
    telugu_videos_button = InlineKeyboardButton("Telugu Videos", url="https://t.me/+y0slgRpoKiNhYzg1")
    
    if bot_manager.is_admin(callback_query.from_user.id):
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
    
    welcome_text = (
        f"ᴡᴇʟᴄᴏᴍᴇ, {user_mention}.\n\n"
        f"🌟 ɪ ᴀᴍ ᴀ ᴛᴇʀᴀʙᴏx ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ. sᴇɴᴅ ᴍᴇ ᴀɴʏ ᴛᴇʀᴀʙᴏx ʟɪɴᴋ "
        f"ɪ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴡɪᴛʜɪɴ ғᴇᴡ sᴇᴄᴏɴᴅs ᴀɴᴅ sᴇɴᴅ ɪᴛ ᴛᴏ ʏᴏᴜ ✨.\n\n"
        f"🚀 **Features:**\n"
        f"• Fast downloads with aria2\n"
        f"• Multiple API fallbacks\n"
        f"• Progress tracking\n"
        f"• Play button for videos\n"
        f"• Reliable error handling"
    )
    
    await SafeMessaging.edit_message(callback_query.message, welcome_text, reply_markup)

# Handle admin file uploads for Bigg Boss channel
@app.on_message(filters.video | filters.document)
async def handle_file_upload(client: Client, message: Message):
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    
    # Only handle file uploads from admins
    if not bot_manager.is_admin(user_id):
        return
    
    file_type = "video" if message.video else "document"
    file_name = ""
    
    if message.video:
        file_name = message.video.file_name or f"Video_{message.video.file_id[:8]}.mp4"
        file_size = ProgressTracker.format_size(message.video.file_size)
    elif message.document:
        file_name = message.document.file_name or f"Document_{message.document.file_id[:8]}"
        file_size = ProgressTracker.format_size(message.document.file_size)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Upload to Bigg Boss", callback_data=f"confirm_bigg_boss_{message.id}")],
        [InlineKeyboardButton("📁 Upload to Dump", callback_data=f"confirm_dump_{message.id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")]
    ])
    
    forward_text = " (Forwarded)" if message.forward_from or message.forward_from_chat else ""
    
    await SafeMessaging.send_message(
        client, message.chat.id,
        f"📤 **Admin Upload{forward_text}**\n\n"
        f"📁 **File:** {file_name}\n"
        f"📂 **Type:** {file_type.title()}\n"
        f"📏 **Size:** {file_size}\n\n"
        "Choose upload destination:",
        keyboard
    )

# Handle upload confirmations
@app.on_callback_query(filters.regex(r"confirm_(bigg_boss|dump)_(\d+)"))
async def confirm_upload(client: Client, callback_query):
    if not bot_manager.is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    data_parts = callback_query.data.split("_")
    destination = data_parts[1] + "_" + data_parts[2]  # bigg_boss or dump
    message_id = int(data_parts[3])
    
    try:
        # Get the original message with the file
        original_message = await client.get_messages(callback_query.message.chat.id, message_id)
        
        if not (original_message.video or original_message.document):
            await callback_query.answer("❌ File not found.", show_alert=True)
            return
        
        # Determine target channel
        if destination == "bigg_boss":
            target_channel = config.BIGG_BOSS_CHANNEL_ID
            channel_name = "Bigg Boss"
        else:
            target_channel = config.DUMP_CHAT_ID
            channel_name = "Dump"
        
        await SafeMessaging.edit_message(
            callback_query.message, 
            f"📤 Uploading to {channel_name} channel..."
        )
        
        # Create caption
        file_name = ""
        if original_message.video:
            file_name = original_message.video.file_name or "Video File"
        elif original_message.document:
            file_name = original_message.document.file_name or "Document File"
        
        if destination == "bigg_boss":
            caption = (
                f"📺 **{file_name}**\n\n"
                f"👤 **Uploaded by:** {callback_query.from_user.first_name}\n"
                f"📅 **Date:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
                f"🔥 [Join our channel for more content](https://t.me/+y0slgRpoKiNhYzg1)"
            )
        else:
            caption = (
                f"✨ {file_name}\n"
                f"👤 **Uploaded by Admin:** {callback_query.from_user.first_name}\n"
                f"📅 **Date:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
                f"[Join Telugu Channel ❤️🚀](https://t.me/dailydiskwala)"
            )
        
        # Upload to target channel
        if original_message.video:
            sent_message = await SafeMessaging.send_video(
                client, target_channel, original_message.video.file_id,
                caption=caption
            )
        elif original_message.document:
            sent_message = await client.send_document(
                chat_id=target_channel,
                document=original_message.document.file_id,
                caption=caption,
                file_name=original_message.document.file_name
            )
        
        if sent_message:
            await SafeMessaging.edit_message(
                callback_query.message,
                f"✅ **Upload Successful!**\n\n"
                f"📁 **File:** {file_name}\n"
                f"📤 **Destination:** {channel_name} Channel\n"
                f"📅 **Time:** {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
                f"✨ File has been successfully uploaded!"
            )
        else:
            await SafeMessaging.edit_message(
                callback_query.message,
                f"❌ **Upload Failed**\n\n"
                f"Failed to upload {file_name} to {channel_name} channel.\n"
                f"Please try again later."
            )
            
    except Exception as e:
        logger.error(f"Upload confirmation error: {e}")
        await SafeMessaging.edit_message(
            callback_query.message,
            f"❌ **Upload Error**\n\n"
            f"An error occurred during upload: {str(e)}\n"
            f"Please try again later."
        )

@app.on_callback_query(filters.regex("cancel_upload"))
async def cancel_upload(client: Client, callback_query):
    await SafeMessaging.edit_message(
        callback_query.message,
        "❌ **Upload Cancelled**\n\n"
        "The file upload has been cancelled."
    )

# Error handler for better debugging
@app.on_message()
async def error_handler(client: Client, message: Message):
    """Global error handler to catch any unhandled messages"""
    try:
        # This will only catch messages that weren't handled by other handlers
        pass
    except Exception as e:
        logger.error(f"Unhandled error in message processing: {e}")

# Cleanup function for graceful shutdown
async def cleanup():
    """Cleanup function to close connections gracefully"""
    try:
        if bot_manager.extractor.session:
            await bot_manager.extractor.close_session()
        logger.info("Cleanup completed successfully")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

# Add speedtest command for performance testing
@app.on_message(filters.command("speedtest") & filters.user(config.ADMIN_IDS))
async def speedtest_command(client: Client, message: Message):
    """Admin command to test download speeds"""
    if len(message.command) < 2:
        await SafeMessaging.send_message(
            client, message.chat.id,
            "Usage: `/speedtest <terabox_url>`\n\n"
            "This will test the download speed without uploading the file."
        )
        return
    
    url = message.command[1]
    
    if not bot_manager.extractor.is_valid_url(url):
        await SafeMessaging.send_message(
            client, message.chat.id,
            "❌ Invalid TeraBox URL provided."
        )
        return
    
    status_msg = await SafeMessaging.send_message(
        client, message.chat.id,
        "🧪 **Speed Test Started**\n\n⏳ Extracting download link..."
    )
    
    # Extract link
    link_info = await bot_manager.extractor.extract_direct_link(url)
    if not link_info:
        await SafeMessaging.edit_message(
            status_msg,
            "❌ **Speed Test Failed**\n\nCouldn't extract download link."
        )
        return
    
    # Start speed test download
    try:
        start_time = datetime.now()
        download = bot_manager.aria2.add_download(
            link_info["direct_url"], 
            options={"dry-run": "true"}  # Don't actually save the file
        )
        
        # Monitor for 30 seconds max
        test_duration = 30
        elapsed = 0
        
        while elapsed < test_duration and not download.is_complete:
            await asyncio.sleep(2)
            elapsed = (datetime.now() - start_time).total_seconds()
            download.update()
            
            speed_mbps = (download.download_speed * 8) / (1024 * 1024)  # Convert to Mbps
            
            await SafeMessaging.edit_message(
                status_msg,
                f"🧪 **Speed Test Running**\n\n"
                f"📁 **File:** {link_info['filename']}\n"
                f"📏 **Size:** {link_info['size']}\n"
                f"📊 **Current Speed:** {ProgressTracker.format_size(download.download_speed)}/s ({speed_mbps:.2f} Mbps)\n"
                f"📦 **Downloaded:** {ProgressTracker.format_size(download.completed_length)}\n"
                f"⏱️ **Elapsed:** {ProgressTracker.format_time(elapsed)}\n"
                f"⏳ **Progress:** {download.progress:.1f}%"
            )
        
        # Calculate average speed
        final_elapsed = (datetime.now() - start_time).total_seconds()
        avg_speed = download.completed_length / final_elapsed if final_elapsed > 0 else 0
        avg_speed_mbps = (avg_speed * 8) / (1024 * 1024)
        
        await SafeMessaging.edit_message(
            status_msg,
            f"✅ **Speed Test Completed**\n\n"
            f"📁 **File:** {link_info['filename']}\n"
            f"📏 **Total Size:** {link_info['size']}\n"
            f"📦 **Downloaded:** {ProgressTracker.format_size(download.completed_length)}\n"
            f"⏱️ **Duration:** {ProgressTracker.format_time(final_elapsed)}\n"
            f"📊 **Average Speed:** {ProgressTracker.format_size(avg_speed)}/s ({avg_speed_mbps:.2f} Mbps)\n"
            f"🎯 **Completion:** {download.progress:.1f}%"
        )
        
        # Cleanup test download
        try:
            bot_manager.aria2.api.remove([download], force=True, files=True)
        except:
            pass
            
    except Exception as e:
        logger.error(f"Speed test error: {e}")
        await SafeMessaging.edit_message(
            status_msg,
            f"❌ **Speed Test Failed**\n\nError: {str(e)}"
        )

if __name__ == "__main__":
    logger.info("Starting Enhanced TeraBox Bot...")
    
    # Register cleanup handler
    import atexit
    atexit.register(lambda: asyncio.run(cleanup()))
    
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        asyncio.run(cleanup())
