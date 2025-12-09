"""
Media Server Discord Bot
Supports Jellyfin, Emby, and Plex servers
Commands for watchtime, device management, password reset, and more
"""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal
import os
from dotenv import load_dotenv
import database as db

load_dotenv()

# Initialize database on import
db.init_database()

# Configuration - Set these in your .env file
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://localhost:8096")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
EMBY_URL = os.getenv("EMBY_URL", "http://localhost:8096")
EMBY_API_KEY = os.getenv("EMBY_API_KEY")
PLEX_URL = os.getenv("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

# Purge settings
PURGE_THRESHOLD_HOURS = int(os.getenv("PURGE_THRESHOLD_HOURS", 7))  # Default 7 hours
PURGE_PERIOD_DAYS = int(os.getenv("PURGE_PERIOD_DAYS", 15))  # Default 15 days


class MediaServerAPI:
    """Base class for media server API interactions"""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def close(self):
        await self.session.close()


class JellyfinAPI(MediaServerAPI):
    """Jellyfin API wrapper"""
    
    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str):
        super().__init__(session)
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Emby-Token": api_key}
    
    async def get_user_by_discord_id(self, discord_id: int) -> Optional[dict]:
        """Get Jellyfin user linked to Discord ID"""
        user = db.get_user_by_discord_id(discord_id)
        if user and user.get("jellyfin_id"):
            return {
                "jellyfin_id": user.get("jellyfin_id"),
                "username": user.get("jellyfin_username"),
                "discord_id": discord_id
            }
        return None
    
    async def get_all_users(self) -> list:
        """Get all users from Jellyfin"""
        try:
            async with self.session.get(
                f"{self.url}/Users",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Jellyfin get_all_users error: {e}")
        return []
    
    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Find a Jellyfin user by username"""
        users = await self.get_all_users()
        for user in users:
            if user.get("Name", "").lower() == username.lower():
                return user
        return None
    
    async def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """Authenticate a user with username and password"""
        try:
            async with self.session.post(
                f"{self.url}/Users/AuthenticateByName",
                headers={
                    **self.headers,
                    "X-Emby-Authorization": f'MediaBrowser Client="Discord Bot", Device="Bot", DeviceId="discord-bot", Version="1.0"'
                },
                json={"Username": username, "Pw": password}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Jellyfin authenticate_user error: {e}")
        return None
    
    async def get_user_info(self, user_id: str) -> Optional[dict]:
        """Get user information from Jellyfin"""
        try:
            async with self.session.get(
                f"{self.url}/Users/{user_id}",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Jellyfin get_user_info error: {e}")
        return None
    
    async def get_playback_info(self, user_id: str) -> dict:
        """Get user's playback/watch statistics"""
        try:
            async with self.session.get(
                f"{self.url}/Users/{user_id}/Items",
                headers=self.headers,
                params={"Recursive": "true", "IncludeItemTypes": "Movie,Episode"}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Jellyfin get_playback_info error: {e}")
        return {}
    
    async def get_devices(self, user_id: str) -> list:
        """Get devices connected to user's account"""
        try:
            async with self.session.get(
                f"{self.url}/Devices",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [d for d in data.get("Items", []) if d.get("LastUserId") == user_id]
        except Exception as e:
            print(f"Jellyfin get_devices error: {e}")
        return []
    
    async def delete_devices(self, user_id: str) -> bool:
        """Delete all devices for a user"""
        devices = await self.get_devices(user_id)
        success = True
        for device in devices:
            try:
                async with self.session.delete(
                    f"{self.url}/Devices",
                    headers=self.headers,
                    params={"Id": device.get("Id")}
                ) as resp:
                    if resp.status not in [200, 204]:
                        success = False
            except Exception as e:
                print(f"Jellyfin delete_device error: {e}")
                success = False
        return success
    
    async def reset_password(self, user_id: str) -> Optional[str]:
        """Reset user password and return new password"""
        import secrets
        new_password = secrets.token_urlsafe(12)
        try:
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Password",
                headers=self.headers,
                json={
                    "CurrentPw": "",
                    "NewPw": new_password,
                    "ResetPassword": True
                }
            ) as resp:
                if resp.status in [200, 204]:
                    return new_password
        except Exception as e:
            print(f"Jellyfin reset_password error: {e}")
        return None
    
    async def get_active_streams(self) -> list:
        """Get currently active streams"""
        try:
            async with self.session.get(
                f"{self.url}/Sessions",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    sessions = await resp.json()
                    return [s for s in sessions if s.get("NowPlayingItem")]
        except Exception as e:
            print(f"Jellyfin get_active_streams error: {e}")
        return []
    
    async def get_server_info(self) -> Optional[dict]:
        """Get server information and status"""
        try:
            async with self.session.get(
                f"{self.url}/System/Info",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Jellyfin get_server_info error: {e}")
        return None
    
    async def set_library_access(self, user_id: str, library_id: str, enable: bool) -> bool:
        """Enable or disable library access for a user"""
        try:
            user_info = await self.get_user_info(user_id)
            if not user_info:
                return False
            
            policy = user_info.get("Policy", {})
            enabled_folders = policy.get("EnabledFolders", [])
            
            if enable and library_id not in enabled_folders:
                enabled_folders.append(library_id)
            elif not enable and library_id in enabled_folders:
                enabled_folders.remove(library_id)
            
            policy["EnabledFolders"] = enabled_folders
            
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Policy",
                headers=self.headers,
                json=policy
            ) as resp:
                return resp.status in [200, 204]
        except Exception as e:
            print(f"Jellyfin set_library_access error: {e}")
        return False


class EmbyAPI(MediaServerAPI):
    """Emby API wrapper - Similar to Jellyfin"""
    
    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str):
        super().__init__(session)
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Emby-Token": api_key}
    
    async def get_user_by_discord_id(self, discord_id: int) -> Optional[dict]:
        """Get Emby user linked to Discord ID"""
        user = db.get_user_by_discord_id(discord_id)
        if user and user.get("emby_id"):
            return {
                "emby_id": user.get("emby_id"),
                "username": user.get("emby_username"),
                "discord_id": discord_id
            }
        return None
    
    async def get_all_users(self) -> list:
        """Get all users from Emby"""
        try:
            async with self.session.get(
                f"{self.url}/Users",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Emby get_all_users error: {e}")
        return []
    
    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Find an Emby user by username"""
        users = await self.get_all_users()
        for user in users:
            if user.get("Name", "").lower() == username.lower():
                return user
        return None
    
    async def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """Authenticate a user with username and password"""
        try:
            async with self.session.post(
                f"{self.url}/Users/AuthenticateByName",
                headers={
                    **self.headers,
                    "X-Emby-Authorization": f'MediaBrowser Client="Discord Bot", Device="Bot", DeviceId="discord-bot", Version="1.0"'
                },
                json={"Username": username, "Pw": password}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Emby authenticate_user error: {e}")
        return None
    
    async def get_user_info(self, user_id: str) -> Optional[dict]:
        try:
            async with self.session.get(
                f"{self.url}/Users/{user_id}",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Emby get_user_info error: {e}")
        return None
    
    async def get_devices(self, user_id: str) -> list:
        try:
            async with self.session.get(
                f"{self.url}/Devices",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [d for d in data.get("Items", []) if d.get("LastUserId") == user_id]
        except Exception as e:
            print(f"Emby get_devices error: {e}")
        return []
    
    async def delete_devices(self, user_id: str) -> bool:
        devices = await self.get_devices(user_id)
        success = True
        for device in devices:
            try:
                async with self.session.delete(
                    f"{self.url}/Devices",
                    headers=self.headers,
                    params={"Id": device.get("Id")}
                ) as resp:
                    if resp.status not in [200, 204]:
                        success = False
            except Exception as e:
                print(f"Emby delete_device error: {e}")
                success = False
        return success
    
    async def reset_password(self, user_id: str) -> Optional[str]:
        import secrets
        new_password = secrets.token_urlsafe(12)
        try:
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Password",
                headers=self.headers,
                json={"NewPw": new_password, "ResetPassword": True}
            ) as resp:
                if resp.status in [200, 204]:
                    return new_password
        except Exception as e:
            print(f"Emby reset_password error: {e}")
        return None
    
    async def get_active_streams(self) -> list:
        try:
            async with self.session.get(
                f"{self.url}/Sessions",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    sessions = await resp.json()
                    return [s for s in sessions if s.get("NowPlayingItem")]
        except Exception as e:
            print(f"Emby get_active_streams error: {e}")
        return []
    
    async def get_server_info(self) -> Optional[dict]:
        try:
            async with self.session.get(
                f"{self.url}/System/Info",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Emby get_server_info error: {e}")
        return None
    
    async def set_library_access(self, user_id: str, library_id: str, enable: bool) -> bool:
        try:
            user_info = await self.get_user_info(user_id)
            if not user_info:
                return False
            
            policy = user_info.get("Policy", {})
            enabled_folders = policy.get("EnabledFolders", [])
            
            if enable and library_id not in enabled_folders:
                enabled_folders.append(library_id)
            elif not enable and library_id in enabled_folders:
                enabled_folders.remove(library_id)
            
            policy["EnabledFolders"] = enabled_folders
            
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Policy",
                headers=self.headers,
                json=policy
            ) as resp:
                return resp.status in [200, 204]
        except Exception as e:
            print(f"Emby set_library_access error: {e}")
        return False


class PlexAPI(MediaServerAPI):
    """Plex API wrapper"""
    
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str):
        super().__init__(session)
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {
            "X-Plex-Token": token,
            "Accept": "application/json"
        }
    
    async def get_user_by_discord_id(self, discord_id: int) -> Optional[dict]:
        """Get Plex user linked to Discord ID"""
        user = db.get_user_by_discord_id(discord_id)
        if user and user.get("plex_id"):
            return {
                "plex_id": user.get("plex_id"),
                "username": user.get("plex_username"),
                "email": user.get("plex_email"),
                "discord_id": discord_id
            }
        return None
    
    async def get_all_users(self) -> list:
        """Get all shared users from Plex"""
        try:
            async with self.session.get(
                f"https://plex.tv/api/v2/friends",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Plex get_all_users error: {e}")
        return []
    
    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Find a Plex user by username or email"""
        users = await self.get_all_users()
        for user in users:
            if (user.get("username", "").lower() == username.lower() or
                user.get("email", "").lower() == username.lower() or
                user.get("title", "").lower() == username.lower()):
                return user
        return None
    
    async def get_user_info(self, user_id: str) -> Optional[dict]:
        try:
            async with self.session.get(
                f"{self.url}/accounts/{user_id}",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Plex get_user_info error: {e}")
        return None
    
    async def get_devices(self, user_id: str) -> list:
        try:
            async with self.session.get(
                f"https://plex.tv/api/v2/resources",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
        except Exception as e:
            print(f"Plex get_devices error: {e}")
        return []
    
    async def get_active_streams(self) -> list:
        try:
            async with self.session.get(
                f"{self.url}/status/sessions",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("MediaContainer", {}).get("Metadata", [])
        except Exception as e:
            print(f"Plex get_active_streams error: {e}")
        return []
    
    async def get_server_info(self) -> Optional[dict]:
        try:
            async with self.session.get(
                f"{self.url}/",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            print(f"Plex get_server_info error: {e}")
        return None
    
    async def get_libraries(self) -> list:
        try:
            async with self.session.get(
                f"{self.url}/library/sections",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("MediaContainer", {}).get("Directory", [])
        except Exception as e:
            print(f"Plex get_libraries error: {e}")
        return []


class MediaServerBot(commands.Bot):
    """Discord bot for media server management"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None  # We'll create a custom help command
        )
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.jellyfin: Optional[JellyfinAPI] = None
        self.emby: Optional[EmbyAPI] = None
        self.plex: Optional[PlexAPI] = None
    
    async def setup_hook(self):
        """Initialize API clients and sync commands"""
        self.session = aiohttp.ClientSession()
        
        if JELLYFIN_URL and JELLYFIN_API_KEY:
            self.jellyfin = JellyfinAPI(self.session, JELLYFIN_URL, JELLYFIN_API_KEY)
        
        if EMBY_URL and EMBY_API_KEY:
            self.emby = EmbyAPI(self.session, EMBY_URL, EMBY_API_KEY)
        
        if PLEX_URL and PLEX_TOKEN:
            self.plex = PlexAPI(self.session, PLEX_URL, PLEX_TOKEN)
        
        await self.tree.sync()
    
    async def close(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
        await super().close()
    
    async def on_ready(self):
        print(f"Bot is ready! Logged in as {self.user}")
        print(f"Connected servers: {len(self.guilds)}")
        
        # Set activity
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="your media servers | !help"
            )
        )


# Create bot instance
bot = MediaServerBot()


# Library mapping for each server
# Format: command_name -> {server: library_name}
LIBRARY_MAPPING = {
    "4kmovies": {
        "display": "4K Movies",
        "jellyfin": "4K Movies",
        "emby": "4K Movies",
        "plex": "4K Movies"
    },
    "movies": {
        "display": "Movies",
        "jellyfin": "Movies",
        "emby": "Movies",
        "plex": "Movies"
    },
    "shows": {
        "display": "TV Shows",
        "jellyfin": "Shows",
        "emby": "TV Shows",
        "plex": "TV Shows"
    },
    "animemovies": {
        "display": "Anime Movies",
        "jellyfin": "Anime Movies",
        "emby": "Anime Movies",
        "plex": "Anime Movies"
    },
    "animeshows": {
        "display": "Anime TV Shows",
        "jellyfin": "Anime Shows",
        "emby": "Anime TV Shows",
        "plex": "Anime TV Shows"
    }
}

# Simple list of available features for help text
AVAILABLE_FEATURES = ["4kmovies", "movies", "shows", "animemovies", "animeshows"]


def create_embed(title: str, description: str, color: discord.Color = discord.Color.blue()) -> discord.Embed:
    """Helper function to create consistent embeds"""
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Media Server Bot")
    return embed


# ============== PREFIX COMMANDS ==============

@bot.command(name="watchtime")
async def watchtime(ctx: commands.Context):
    """Check your watchtime and see if you're safe from the purge"""
    discord_id = ctx.author.id
    
    # Get user from database
    db_user = db.get_user_by_discord_id(discord_id)
    
    if not db_user:
        embed = create_embed("⏱️ Watchtime Check", "")
        embed.description = "❌ No linked accounts found. Use `!link` to link your account first."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Check if user has ever subscribed (immune to purge)
    is_subscriber = db.has_ever_subscribed(db_user.get("id"))
    
    # Determine tier
    if is_subscriber:
        tier = "Subscriber"
        tier_emoji = "💎"
    else:
        tier = "Member"
        tier_emoji = "🏆"
    
    # Get daily watchtime for the period
    daily_watchtime = db.get_daily_watchtime(db_user.get("id"), PURGE_PERIOD_DAYS)
    
    # Calculate totals
    total_tv_seconds = sum(d.get("tv", 0) for d in daily_watchtime.values())
    total_movie_seconds = sum(d.get("movie", 0) for d in daily_watchtime.values())
    total_seconds = total_tv_seconds + total_movie_seconds
    total_hours = total_seconds / 3600
    
    # Calculate remaining hours needed
    threshold_seconds = PURGE_THRESHOLD_HOURS * 3600
    remaining_seconds = max(0, threshold_seconds - total_seconds)
    remaining_hours = remaining_seconds / 3600
    
    # Calculate days left in period
    days_left = PURGE_PERIOD_DAYS - len(daily_watchtime)
    if days_left < 0:
        days_left = 0
    
    # Determine status
    if is_subscriber:
        status = "**Immune**"
        status_color = discord.Color.gold()
        status_message = "Your presence is a whisper in the dark. Even the purge cannot detect you. 🥷"
    elif total_seconds >= threshold_seconds:
        status = "✅ Safe"
        status_color = discord.Color.green()
        status_message = "You're safe from the purge! Keep watching! 🎬"
    else:
        status = "⚠️ At Risk"
        status_color = discord.Color.red()
        status_message = f"Watch {format_duration(remaining_seconds)} more to be safe!"
    
    # Get username from linked accounts
    username = ctx.author.display_name
    server_name = "Server"
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            username = user.get("username", username)
            server_name = "Jellyfin"
    elif bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            username = user.get("username", username)
            server_name = "Emby"
    elif bot.plex:
        user = await bot.plex.get_user_by_discord_id(discord_id)
        if user:
            username = user.get("username", username)
            server_name = "Plex"
    
    # Build the embed
    embed = discord.Embed(
        title=f"{username}'s {server_name} Watchtime",
        color=status_color
    )
    
    # Build daily watchtime table
    table_header = "```"
    table_header += f"{'Day':<11}| {'Date':<8}| {'TV':<10}| {'Movie':<10}| {'Total':<10}\n"
    table_header += "-" * 55 + "\n"
    
    table_rows = ""
    
    # Get last N days
    from datetime import date
    today = date.today()
    
    for i in range(min(PURGE_PERIOD_DAYS, 7)):  # Show last 7 days max
        day_date = today - timedelta(days=i)
        day_name = day_date.strftime("%A")
        day_str = day_date.strftime("%d %b")
        
        day_key = day_date.strftime("%Y-%m-%d")
        day_data = daily_watchtime.get(day_key, {"tv": 0, "movie": 0})
        
        tv_time = format_duration_short(day_data.get("tv", 0))
        movie_time = format_duration_short(day_data.get("movie", 0))
        day_total = format_duration_short(day_data.get("tv", 0) + day_data.get("movie", 0))
        
        table_rows += f"{day_name:<11}| {day_str:<8}| {tv_time:<10}| {movie_time:<10}| {day_total:<10}\n"
    
    table_footer = "-" * 55 + "\n"
    table_footer += f"{'Total':<11}| {'':<8}| {format_duration_short(total_tv_seconds):<10}| {format_duration_short(total_movie_seconds):<10}| {format_duration_short(total_seconds):<10}\n"
    table_footer += "```"
    
    embed.description = table_header + table_rows + table_footer
    
    # Add status message
    embed.add_field(
        name="\u200b",  # Empty name
        value=f"*{status_message}*",
        inline=False
    )
    
    # Calculate period dates
    period_start = today - timedelta(days=PURGE_PERIOD_DAYS - 1)
    period_str = f"{period_start.strftime('%d %b')} - {today.strftime('%d %b')}"
    
    # Add stats fields
    embed.add_field(name="📅 Week Period", value=period_str, inline=True)
    embed.add_field(name="📅 Days Left", value=f"{days_left} Days", inline=True)
    embed.add_field(name="🔵 Status", value=status, inline=True)
    
    embed.add_field(name="⏱️ Purge Limit", value=f"{PURGE_THRESHOLD_HOURS}h", inline=True)
    embed.add_field(name="⏳ Remaining", value=f"{remaining_hours:.1f} hrs" if not is_subscriber else "N/A", inline=True)
    embed.add_field(name=f"{tier_emoji} Tier", value=tier, inline=True)
    
    embed.set_footer(text="⚫ All times are based on the server's timezone.")
    embed.timestamp = datetime.now(timezone.utc)
    
    await ctx.send(embed=embed)


def format_duration(seconds: int) -> str:
    """Format seconds into human readable duration (e.g., 4h15m29s)"""
    if seconds <= 0:
        return "0s"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return "".join(parts)


def format_duration_short(seconds: int) -> str:
    """Format seconds into short duration (e.g., 1h2m31s)"""
    if seconds <= 0:
        return "0s"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}h{minutes}m{secs}s"
    elif minutes > 0:
        return f"{minutes}m{secs}s"
    else:
        return f"{secs}s"


@bot.command(name="totaltime")
async def totaltime(ctx: commands.Context):
    """Check your total watchtime from when you've joined the server"""
    embed = create_embed("📊 Total Watchtime", "Fetching your total watchtime...")
    
    results = []
    discord_id = ctx.author.id
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            total_hours = user.get("total_watchtime_hours", 0)
            results.append(f"**Jellyfin:** {total_hours} hours total")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            total_hours = user.get("total_watchtime_hours", 0)
            results.append(f"**Emby:** {total_hours} hours total")
    
    if bot.plex:
        user = await bot.plex.get_user_by_discord_id(discord_id)
        if user:
            total_hours = user.get("total_watchtime_hours", 0)
            results.append(f"**Plex:** {total_hours} hours total")
    
    if results:
        embed.description = "\n".join(results)
    else:
        embed.description = "❌ No linked accounts found."
        embed.color = discord.Color.red()
    
    await ctx.send(embed=embed)


@bot.command(name="devices")
async def devices(ctx: commands.Context):
    """Lists the devices currently connected to your account"""
    embed = create_embed("📱 Connected Devices", "Fetching your devices...")
    
    discord_id = ctx.author.id
    all_devices = []
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            devices = await bot.jellyfin.get_devices(user.get("jellyfin_id"))
            for device in devices:
                all_devices.append(
                    f"**[Jellyfin]** {device.get('Name', 'Unknown')} - "
                    f"{device.get('AppName', 'Unknown App')}"
                )
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            devices = await bot.emby.get_devices(user.get("emby_id"))
            for device in devices:
                all_devices.append(
                    f"**[Emby]** {device.get('Name', 'Unknown')} - "
                    f"{device.get('AppName', 'Unknown App')}"
                )
    
    if bot.plex:
        user = await bot.plex.get_user_by_discord_id(discord_id)
        if user:
            devices = await bot.plex.get_devices(user.get("plex_id"))
            for device in devices:
                all_devices.append(
                    f"**[Plex]** {device.get('name', 'Unknown')} - "
                    f"{device.get('product', 'Unknown App')}"
                )
    
    if all_devices:
        embed.description = "\n".join(all_devices[:25])  # Limit to 25 devices
        if len(all_devices) > 25:
            embed.add_field(
                name="Note",
                value=f"Showing 25 of {len(all_devices)} devices",
                inline=False
            )
    else:
        embed.description = "No devices found or no linked accounts."
        embed.color = discord.Color.orange()
    
    await ctx.send(embed=embed)


@bot.command(name="reset_devices")
async def reset_devices(ctx: commands.Context):
    """Deletes all your connected devices from the account (Jellyfin or Emby)"""
    embed = create_embed("🔄 Reset Devices", "Removing all connected devices...")
    
    discord_id = ctx.author.id
    results = []
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            success = await bot.jellyfin.delete_devices(user.get("jellyfin_id"))
            status = "✅ Cleared" if success else "❌ Failed"
            results.append(f"**Jellyfin:** {status}")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            success = await bot.emby.delete_devices(user.get("emby_id"))
            status = "✅ Cleared" if success else "❌ Failed"
            results.append(f"**Emby:** {status}")
    
    if results:
        embed.description = "\n".join(results)
        embed.add_field(
            name="Note",
            value="You may need to sign in again on your devices.",
            inline=False
        )
    else:
        embed.description = "❌ No linked Jellyfin or Emby accounts found."
        embed.color = discord.Color.red()
    
    await ctx.send(embed=embed)


@bot.command(name="reset_password")
async def reset_password(ctx: commands.Context):
    """Resets your password and sends you the new credentials (Jellyfin or Emby)"""
    # Send initial response
    await ctx.send("🔐 Resetting your password... Check your DMs!")
    
    discord_id = ctx.author.id
    results = []
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            new_password = await bot.jellyfin.reset_password(user.get("jellyfin_id"))
            if new_password:
                results.append(f"**Jellyfin**\nUsername: {user.get('username')}\nNew Password: ||{new_password}||")
            else:
                results.append("**Jellyfin:** ❌ Failed to reset password")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            new_password = await bot.emby.reset_password(user.get("emby_id"))
            if new_password:
                results.append(f"**Emby**\nUsername: {user.get('username')}\nNew Password: ||{new_password}||")
            else:
                results.append("**Emby:** ❌ Failed to reset password")
    
    if results:
        try:
            embed = create_embed("🔐 Password Reset", "\n\n".join(results))
            embed.color = discord.Color.green()
            embed.add_field(
                name="⚠️ Security Notice",
                value="Please change your password after logging in!",
                inline=False
            )
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ Could not send DM. Please enable DMs from server members.")
    else:
        await ctx.send("❌ No linked Jellyfin or Emby accounts found.")


@bot.command(name="stream")
async def stream(ctx: commands.Context):
    """Shows details about your streaming tracks"""
    embed = create_embed("🎬 Active Streams", "Fetching stream information...")
    
    all_streams = []
    
    if bot.jellyfin:
        streams = await bot.jellyfin.get_active_streams()
        for s in streams:
            item = s.get("NowPlayingItem", {})
            user = s.get("UserName", "Unknown")
            title = item.get("Name", "Unknown")
            stream_type = item.get("Type", "Unknown")
            all_streams.append(f"**[Jellyfin]** {user} watching: {title} ({stream_type})")
    
    if bot.emby:
        streams = await bot.emby.get_active_streams()
        for s in streams:
            item = s.get("NowPlayingItem", {})
            user = s.get("UserName", "Unknown")
            title = item.get("Name", "Unknown")
            stream_type = item.get("Type", "Unknown")
            all_streams.append(f"**[Emby]** {user} watching: {title} ({stream_type})")
    
    if bot.plex:
        streams = await bot.plex.get_active_streams()
        for s in streams:
            user = s.get("User", {}).get("title", "Unknown")
            title = s.get("title", "Unknown")
            stream_type = s.get("type", "Unknown")
            all_streams.append(f"**[Plex]** {user} watching: {title} ({stream_type})")
    
    if all_streams:
        embed.description = "\n".join(all_streams)
        embed.add_field(name="Total Active Streams", value=str(len(all_streams)), inline=True)
    else:
        embed.description = "No active streams at the moment."
        embed.color = discord.Color.orange()
    
    await ctx.send(embed=embed)


@bot.command(name="status")
async def status(ctx: commands.Context):
    """Displays the current operational status and health of the server"""
    discord_id = ctx.author.id
    
    # Get user info for the header
    db_user = db.get_user_by_discord_id(discord_id)
    username = ctx.author.display_name
    
    # Determine which server to show (priority: Jellyfin > Emby > Plex)
    server_name = "Media Server"
    server_online = False
    server_info = None
    streams_data = {"total": 0, "transcoding": 0, "direct": 0}
    latency_ms = 0
    
    # Check servers and get detailed info
    import time
    
    if bot.jellyfin:
        start_time = time.time()
        info = await bot.jellyfin.get_server_info()
        latency_ms = round((time.time() - start_time) * 1000, 1)
        
        if info:
            server_online = True
            server_name = "Jellyfin"
            server_info = info
            
            # Get stream details
            streams = await bot.jellyfin.get_active_streams()
            streams_data["total"] = len(streams)
            for s in streams:
                play_state = s.get("PlayState", {})
                transcode_info = s.get("TranscodingInfo")
                if transcode_info:
                    streams_data["transcoding"] += 1
                else:
                    streams_data["direct"] += 1
    
    elif bot.emby:
        start_time = time.time()
        info = await bot.emby.get_server_info()
        latency_ms = round((time.time() - start_time) * 1000, 1)
        
        if info:
            server_online = True
            server_name = "Emby"
            server_info = info
            
            streams = await bot.emby.get_active_streams()
            streams_data["total"] = len(streams)
            for s in streams:
                transcode_info = s.get("TranscodingInfo")
                if transcode_info:
                    streams_data["transcoding"] += 1
                else:
                    streams_data["direct"] += 1
    
    elif bot.plex:
        start_time = time.time()
        info = await bot.plex.get_server_info()
        latency_ms = round((time.time() - start_time) * 1000, 1)
        
        if info:
            server_online = True
            server_name = "Plex"
            server_info = info
            
            streams = await bot.plex.get_active_streams()
            streams_data["total"] = len(streams)
            for s in streams:
                transcode_session = s.get("TranscodeSession")
                if transcode_session:
                    streams_data["transcoding"] += 1
                else:
                    streams_data["direct"] += 1
    
    # Calculate membership duration
    member_duration = ""
    if db_user:
        created_at = db_user.get("created_at")
        if created_at:
            from datetime import datetime
            if isinstance(created_at, str):
                try:
                    created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except:
                    created_date = datetime.now(timezone.utc)
            else:
                created_date = created_at
            
            now = datetime.now(timezone.utc)
            if created_date.tzinfo is None:
                created_date = created_date.replace(tzinfo=timezone.utc)
            
            diff = now - created_date
            months = diff.days // 30
            days = diff.days % 30
            
            if months > 0:
                member_duration = f"{months} month{'s' if months != 1 else ''} and {days} day{'s' if days != 1 else ''}"
            else:
                member_duration = f"{days} day{'s' if days != 1 else ''}"
    
    # Determine tier
    is_subscriber = False
    if db_user:
        is_subscriber = db.has_ever_subscribed(db_user.get("id"))
    tier = "Elite" if is_subscriber else "Member"
    
    # Build the embed
    embed = discord.Embed(
        title=f"{username}'s {server_name} Server",
        color=discord.Color.purple() if server_online else discord.Color.red()
    )
    
    # Add description with member info
    if member_duration:
        embed.description = f"*User {username} has joined our Discord {member_duration} ago and is an **{tier}** member of the {server_name.lower()} server.*"
    
    # Server Info section
    embed.add_field(name="Server Info:", value="\u200b", inline=False)
    
    # Local status
    local_status = "🟢 Online" if server_online else "🔴 Offline"
    embed.add_field(name="🖥️ Local", value=local_status, inline=True)
    
    # Internet status (same as local for now)
    internet_status = "🟢 Online" if server_online else "🔴 Offline"
    embed.add_field(name="🌐 Internet", value=internet_status, inline=True)
    
    # Latency
    latency_display = f"= {latency_ms} ms" if server_online else "N/A"
    embed.add_field(name="⚡ Latency", value=latency_display, inline=True)
    
    # Streams info
    embed.add_field(name="📺 Streams", value=f"[{streams_data['total']}] streams", inline=True)
    
    # Transcoding
    transcode_display = f"[{streams_data['transcoding']}V/0A]"  # Video/Audio transcoding
    embed.add_field(name="🔄 Transcoding", value=transcode_display, inline=True)
    
    # Direct Play
    embed.add_field(name="▶️ Direct Play", value=f"[{streams_data['direct']}] streams", inline=True)
    
    # Footer with timestamp
    embed.set_footer(
        text=f"Requested by {ctx.author.display_name} • {datetime.now(timezone.utc).strftime('%m/%d/%Y %I:%M %p')}",
        icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None
    )
    
    # Add server icon/thumbnail if available
    embed.set_thumbnail(url="https://i.imgur.com/YQPnLHB.png")  # Default server icon
    
    await ctx.send(embed=embed)


@bot.command(name="enable")
async def enable_feature(ctx: commands.Context, feature: str, option: Optional[int] = None):
    """Enable a specific content library (e.g. 4kmovies, movies, shows, animemovies, animeshows)"""
    feature = feature.lower()
    
    if feature not in LIBRARY_MAPPING:
        available = ", ".join(AVAILABLE_FEATURES)
        await ctx.send(f"❌ Unknown feature. Available: `{available}`")
        return
    
    library_info = LIBRARY_MAPPING[feature]
    display_name = library_info["display"]
    
    embed = create_embed(
        "✅ Enable Feature",
        f"Enabling **{display_name}** access..."
    )
    
    discord_id = ctx.author.id
    results = []
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            library_name = library_info.get("jellyfin")
            if library_name:
                success = await bot.jellyfin.set_library_access(
                    user.get("jellyfin_id"), library_name, True
                )
                status = "✅ Enabled" if success else "❌ Failed"
                results.append(f"**Jellyfin:** {status}")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            library_name = library_info.get("emby")
            if library_name:
                success = await bot.emby.set_library_access(
                    user.get("emby_id"), library_name, True
                )
                status = "✅ Enabled" if success else "❌ Failed"
                results.append(f"**Emby:** {status}")
    
    if results:
        embed.description = f"**{display_name}**\n\n" + "\n".join(results)
        embed.color = discord.Color.green()
    else:
        embed.description = "❌ No linked accounts found."
        embed.color = discord.Color.red()
    
    await ctx.send(embed=embed)


@bot.command(name="disable")
async def disable_feature(ctx: commands.Context, feature: str, option: Optional[int] = None):
    """Disable a specific content library (e.g. 4kmovies, movies, shows, animemovies, animeshows)"""
    feature = feature.lower()
    
    if feature not in LIBRARY_MAPPING:
        available = ", ".join(AVAILABLE_FEATURES)
        await ctx.send(f"❌ Unknown feature. Available: `{available}`")
        return
    
    library_info = LIBRARY_MAPPING[feature]
    display_name = library_info["display"]
    
    embed = create_embed(
        "🚫 Disable Feature",
        f"Disabling **{display_name}** access..."
    )
    
    discord_id = ctx.author.id
    results = []
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            library_name = library_info.get("jellyfin")
            if library_name:
                success = await bot.jellyfin.set_library_access(
                    user.get("jellyfin_id"), library_name, False
                )
                status = "✅ Disabled" if success else "❌ Failed"
                results.append(f"**Jellyfin:** {status}")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            library_name = library_info.get("emby")
            if library_name:
                success = await bot.emby.set_library_access(
                    user.get("emby_id"), library_name, False
                )
                status = "✅ Disabled" if success else "❌ Failed"
                results.append(f"**Emby:** {status}")
    
    if results:
        embed.description = f"**{display_name}**\n\n" + "\n".join(results)
        embed.color = discord.Color.orange()
    else:
        embed.description = "❌ No linked accounts found."
        embed.color = discord.Color.red()
    
    await ctx.send(embed=embed)


@bot.command(name="link")
async def link_account(ctx: commands.Context, server_type: str = None, *, username: str = None):
    """Link your Discord account to your media server account
    
    Usage: 
        !link jellyfin <username>
        !link emby <username>
        !link plex <username or email>
    """
    if not server_type or not username:
        embed = create_embed("🔗 Link Account", "")
        embed.description = """**Usage:** `!link <server> <username>`

**Examples:**
• `!link jellyfin MyUsername`
• `!link emby MyUsername`
• `!link plex myemail@example.com`

**Available servers:** `jellyfin`, `emby`, `plex`"""
        embed.color = discord.Color.blue()
        await ctx.send(embed=embed)
        return
    
    server_type = server_type.lower()
    discord_id = ctx.author.id
    discord_username = str(ctx.author)
    
    embed = create_embed("🔗 Link Account", f"Searching for **{username}** on {server_type.title()}...")
    
    try:
        # Ensure user exists in database
        db.get_or_create_user(discord_id, discord_username)
    except Exception as e:
        print(f"Database error in link command: {e}")
        embed.description = f"❌ Database error: `{str(e)[:100]}`"
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    if server_type == "jellyfin":
        if not bot.jellyfin:
            embed.description = "❌ Jellyfin is not configured on this server."
            embed.color = discord.Color.red()
            await ctx.send(embed=embed)
            return
        
        try:
            # Search for user
            user = await bot.jellyfin.get_user_by_username(username)
            if user:
                jellyfin_id = user.get("Id")
                jellyfin_username = user.get("Name")
                
                # Save to database
                db.link_jellyfin_account(discord_id, jellyfin_id, jellyfin_username)
                db.log_action(discord_id, "link_jellyfin", f"Linked to {jellyfin_username}")
                
                embed.description = f"✅ Successfully linked to Jellyfin account: **{jellyfin_username}**"
                embed.color = discord.Color.green()
            else:
                embed.description = f"❌ User **{username}** not found on Jellyfin.\n\nMake sure you're using your exact Jellyfin username."
                embed.color = discord.Color.red()
        except Exception as e:
            print(f"Jellyfin link error: {e}")
            embed.description = f"❌ Error connecting to Jellyfin: `{str(e)[:100]}`"
            embed.color = discord.Color.red()
    
    elif server_type == "emby":
        if not bot.emby:
            embed.description = "❌ Emby is not configured on this server."
            embed.color = discord.Color.red()
            await ctx.send(embed=embed)
            return
        
        try:
            user = await bot.emby.get_user_by_username(username)
            if user:
                emby_id = user.get("Id")
                emby_username = user.get("Name")
                
                db.link_emby_account(discord_id, emby_id, emby_username)
                db.log_action(discord_id, "link_emby", f"Linked to {emby_username}")
                
                embed.description = f"✅ Successfully linked to Emby account: **{emby_username}**"
                embed.color = discord.Color.green()
            else:
                embed.description = f"❌ User **{username}** not found on Emby.\n\nMake sure you're using your exact Emby username."
                embed.color = discord.Color.red()
        except Exception as e:
            print(f"Emby link error: {e}")
            embed.description = f"❌ Error connecting to Emby: `{str(e)[:100]}`"
            embed.color = discord.Color.red()
    
    elif server_type == "plex":
        if not bot.plex:
            embed.description = "❌ Plex is not configured on this server."
            embed.color = discord.Color.red()
            await ctx.send(embed=embed)
            return
        
        try:
            user = await bot.plex.get_user_by_username(username)
            if user:
                plex_id = str(user.get("id"))
                plex_username = user.get("username") or user.get("title")
                plex_email = user.get("email")
                
                db.link_plex_account(discord_id, plex_id, plex_username, plex_email)
                db.log_action(discord_id, "link_plex", f"Linked to {plex_username}")
                
                embed.description = f"✅ Successfully linked to Plex account: **{plex_username}**"
                embed.color = discord.Color.green()
            else:
                embed.description = f"❌ User **{username}** not found on Plex.\n\nMake sure you're using your Plex username or email."
                embed.color = discord.Color.red()
        except Exception as e:
            print(f"Plex link error: {e}")
            embed.description = f"❌ Error connecting to Plex: `{str(e)[:100]}`"
            embed.color = discord.Color.red()
    
    else:
        embed.description = f"❌ Unknown server type: **{server_type}**\n\nAvailable: `jellyfin`, `emby`, `plex`"
        embed.color = discord.Color.red()
    
    await ctx.send(embed=embed)


@bot.command(name="unlink")
async def unlink_account(ctx: commands.Context, server_type: str = None):
    """Unlink your Discord account from a media server
    
    Usage: !unlink <server>
    """
    if not server_type:
        embed = create_embed("🔓 Unlink Account", "")
        embed.description = """**Usage:** `!unlink <server>`

**Examples:**
• `!unlink jellyfin`
• `!unlink emby`
• `!unlink plex`

**Available servers:** `jellyfin`, `emby`, `plex`"""
        embed.color = discord.Color.blue()
        await ctx.send(embed=embed)
        return
    
    server_type = server_type.lower()
    discord_id = ctx.author.id
    
    if server_type not in ["jellyfin", "emby", "plex"]:
        embed = create_embed("🔓 Unlink Account", "")
        embed.description = f"❌ Unknown server type: **{server_type}**\n\nAvailable: `jellyfin`, `emby`, `plex`"
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    success = db.unlink_account(discord_id, server_type)
    
    embed = create_embed("🔓 Unlink Account", "")
    if success:
        db.log_action(discord_id, f"unlink_{server_type}", f"Unlinked from {server_type}")
        embed.description = f"✅ Successfully unlinked from **{server_type.title()}**"
        embed.color = discord.Color.green()
    else:
        embed.description = f"❌ No linked {server_type.title()} account found."
        embed.color = discord.Color.red()
    
    await ctx.send(embed=embed)


@bot.command(name="time")
async def server_time(ctx: commands.Context):
    """Shows the current server date and time"""
    now = datetime.now(timezone.utc)
    
    embed = create_embed("🕐 Server Time", "")
    embed.add_field(name="UTC Time", value=now.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    embed.add_field(name="Unix Timestamp", value=str(int(now.timestamp())), inline=False)
    
    await ctx.send(embed=embed)


@bot.command(name="commands", aliases=["help"])
async def help_command(ctx: commands.Context):
    """Lists all the available commands and their descriptions"""
    embed = create_embed("📋 Available Commands", "")
    embed.color = discord.Color.blue()
    
    prefix_commands = """
**!link [server] [username]** - Link your Discord to a media server account
**!unlink [server]** - Unlink your Discord from a media server
**!watchtime** - Check your watchtime and see if you're safe from the purge
**!totaltime** - Check your total watchtime from when you've joined
**!devices** - Lists the devices currently connected to your account
**!reset_devices** - Deletes all connected devices (Jellyfin/Emby)
**!reset_password** - Resets password and sends new credentials (Jellyfin/Emby)
**!stream** - Shows details about current streaming tracks
**!status** - Displays server operational status and health
**!enable [feature]** - Enable a content library
**!disable [feature]** - Disable a content library
**!time** - Shows the current server date and time
**!commands** or **!help** - Shows this message
    """
    
    slash_commands = """
**/subscribe** - Get your personalized subscription link
**/unsubscribe** - Cancel an active subscription
**/info** - Show your account info
    """
    
    embed.add_field(name="Prefix Commands (!)", value=prefix_commands, inline=False)
    embed.add_field(name="Slash Commands (/)", value=slash_commands, inline=False)
    
    features = ", ".join(AVAILABLE_FEATURES)
    embed.add_field(
        name="Available Libraries",
        value=f"`{features}`",
        inline=False
    )
    
    embed.add_field(
        name="Purge Info",
        value=f"Watch {PURGE_THRESHOLD_HOURS}+ hours over {PURGE_PERIOD_DAYS} days to stay safe.\nSubscribers are **immune** to purge!",
        inline=False
    )
    
    await ctx.send(embed=embed)


# ============== ADMIN COMMANDS ==============

# Get admin user IDs from environment variable (comma-separated)
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]


def is_admin():
    """Check if user is an admin"""
    async def predicate(ctx: commands.Context):
        return ctx.author.id in ADMIN_IDS or ctx.author.guild_permissions.administrator
    return commands.check(predicate)


@bot.command(name="addsub")
@is_admin()
async def add_subscriber(ctx: commands.Context, member: discord.Member, plan_type: str = "kofi", amount: float = 0):
    """[ADMIN] Add a subscriber manually
    
    Usage: !addsub @user [plan_type] [amount]
    Example: !addsub @JohnDoe kofi 5.00
    """
    discord_id = member.id
    discord_username = str(member)
    
    # Ensure user exists in database
    db_user = db.get_or_create_user(discord_id, discord_username)
    user_id = db_user.get("id") if isinstance(db_user, dict) else db_user
    
    # Get internal user ID
    if isinstance(db_user, int):
        user_id = db_user
    else:
        full_user = db.get_user_by_discord_id(discord_id)
        user_id = full_user.get("id")
    
    # Create subscription
    try:
        sub_id = db.create_subscription(
            user_id=user_id,
            plan_type=plan_type,
            amount=amount,
            days=36500  # ~100 years (lifetime)
        )
        
        db.log_action(discord_id, "admin_add_sub", f"Added by {ctx.author} - Plan: {plan_type}, Amount: ${amount}")
        
        embed = create_embed("✅ Subscriber Added", "")
        embed.description = f"Successfully added **{member.display_name}** as a subscriber!"
        embed.add_field(name="User", value=f"{member.mention}", inline=True)
        embed.add_field(name="Plan", value=plan_type.title(), inline=True)
        embed.add_field(name="Amount", value=f"${amount:.2f}" if amount > 0 else "Free", inline=True)
        embed.add_field(name="Status", value="🛡️ Immune to purge", inline=False)
        embed.color = discord.Color.green()
        
        await ctx.send(embed=embed)
        
        # Notify the user
        try:
            user_embed = create_embed("🎉 Subscription Activated!", "")
            user_embed.description = f"Your subscription has been activated by an admin!\n\nYou are now **immune to purge**. Thank you for your support!"
            user_embed.color = discord.Color.gold()
            await member.send(embed=user_embed)
        except discord.Forbidden:
            pass  # Can't DM user
            
    except Exception as e:
        print(f"Add subscriber error: {e}")
        embed = create_embed("❌ Error", f"Failed to add subscriber: `{str(e)[:100]}`")
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)


@bot.command(name="removesub")
@is_admin()
async def remove_subscriber(ctx: commands.Context, member: discord.Member):
    """[ADMIN] Remove a subscriber
    
    Usage: !removesub @user
    """
    discord_id = member.id
    
    db_user = db.get_user_by_discord_id(discord_id)
    if not db_user:
        embed = create_embed("❌ Error", "User not found in database.")
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    user_id = db_user.get("id")
    
    # Remove all subscriptions
    try:
        success = db.remove_all_subscriptions(user_id)
        
        if success:
            db.log_action(discord_id, "admin_remove_sub", f"Removed by {ctx.author}")
            
            embed = create_embed("✅ Subscriber Removed", "")
            embed.description = f"Removed subscription for **{member.display_name}**."
            embed.add_field(name="Status", value="⚠️ No longer immune to purge", inline=False)
            embed.color = discord.Color.orange()
        else:
            embed = create_embed("ℹ️ No Subscription", f"{member.display_name} has no active subscription.")
            embed.color = discord.Color.blue()
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Remove subscriber error: {e}")
        embed = create_embed("❌ Error", f"Failed to remove subscriber: `{str(e)[:100]}`")
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)


@bot.command(name="listsubs")
@is_admin()
async def list_subscribers(ctx: commands.Context):
    """[ADMIN] List all subscribers"""
    try:
        subscribers = db.get_all_subscribers()
        
        if not subscribers:
            embed = create_embed("📋 Subscribers", "No subscribers found.")
            embed.color = discord.Color.blue()
            await ctx.send(embed=embed)
            return
        
        embed = create_embed("📋 Subscribers", f"Total: **{len(subscribers)}** subscribers")
        embed.color = discord.Color.gold()
        
        # Build list (max 20 to avoid embed limits)
        sub_list = []
        for i, sub in enumerate(subscribers[:20]):
            discord_id = sub.get("discord_id")
            username = sub.get("discord_username", "Unknown")
            plan = sub.get("plan_type", "Unknown")
            sub_list.append(f"`{i+1}.` **{username}** - {plan}")
        
        embed.description = "\n".join(sub_list)
        
        if len(subscribers) > 20:
            embed.set_footer(text=f"Showing 20 of {len(subscribers)} subscribers")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"List subscribers error: {e}")
        embed = create_embed("❌ Error", f"Failed to list subscribers: `{str(e)[:100]}`")
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)


@bot.command(name="checksub")
@is_admin()
async def check_subscriber(ctx: commands.Context, member: discord.Member):
    """[ADMIN] Check if a user is a subscriber
    
    Usage: !checksub @user
    """
    discord_id = member.id
    
    db_user = db.get_user_by_discord_id(discord_id)
    if not db_user:
        embed = create_embed("❌ Not Found", f"{member.display_name} is not in the database.")
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    user_id = db_user.get("id")
    is_subscriber = db.has_ever_subscribed(user_id)
    subscription = db.get_active_subscription(user_id)
    
    embed = create_embed(f"🔍 Subscription Check: {member.display_name}", "")
    
    if is_subscriber:
        embed.color = discord.Color.gold()
        embed.add_field(name="Status", value="🛡️ Subscriber (Immune)", inline=True)
        
        if subscription:
            embed.add_field(name="Plan", value=subscription.get("plan_type", "Unknown").title(), inline=True)
            embed.add_field(name="Amount", value=f"${subscription.get('amount', 0):.2f}", inline=True)
    else:
        embed.color = discord.Color.blue()
        embed.add_field(name="Status", value="👤 Regular Member", inline=True)
        embed.add_field(name="Immune", value="❌ No", inline=True)
    
    await ctx.send(embed=embed)


# ============== SLASH COMMANDS ==============

@bot.tree.command(name="subscribe", description="Get your personalized subscription link")
async def subscribe(interaction: discord.Interaction):
    """Get your personalized subscription link"""
    discord_id = interaction.user.id
    
    # Generate a unique subscription link - in production, this would be from your payment system
    base_url = os.getenv("SUBSCRIBE_URL", "https://yourserver.com/subscribe")
    subscription_url = f"{base_url}?user={discord_id}"
    
    embed = create_embed("💳 Subscribe", "Get access to premium features!")
    embed.add_field(
        name="Your Subscription Link",
        value=f"[Click here to subscribe]({subscription_url})",
        inline=False
    )
    embed.add_field(
        name="Benefits",
        value="• 🛡️ **Immune to purge** (forever!)\n• Access to 4K content\n• Priority streaming\n• Extended device limits",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="unsubscribe", description="Cancel an active subscription")
async def unsubscribe(interaction: discord.Interaction):
    """Cancel an active subscription"""
    discord_id = interaction.user.id
    
    embed = create_embed("🚫 Unsubscribe", "")
    
    # Get user from database
    user = db.get_user_by_discord_id(discord_id)
    has_subscription = False
    
    if user:
        subscription = db.get_active_subscription(user.get("id"))
        has_subscription = subscription is not None
    
    if has_subscription:
        db.cancel_subscription(user.get("id"))
        db.log_action(discord_id, "unsubscribe", "Cancelled subscription")
        embed.description = "Your subscription has been cancelled."
        embed.add_field(
            name="Note",
            value="Your access will remain active until the end of your billing period.",
            inline=False
        )
        embed.color = discord.Color.orange()
    else:
        embed.description = "You don't have an active subscription."
        embed.color = discord.Color.red()
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="info", description="Show your account info")
async def info(interaction: discord.Interaction):
    """Show your account info"""
    discord_id = interaction.user.id
    
    embed = create_embed("👤 Account Information", "")
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    
    embed.add_field(name="Discord Username", value=interaction.user.name, inline=True)
    embed.add_field(name="Discord ID", value=str(discord_id), inline=True)
    
    # Check linked accounts
    linked = []
    
    if bot.jellyfin:
        user = await bot.jellyfin.get_user_by_discord_id(discord_id)
        if user:
            linked.append(f"✅ Jellyfin: {user.get('username', 'Linked')}")
        else:
            linked.append("❌ Jellyfin: Not linked")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            linked.append(f"✅ Emby: {user.get('username', 'Linked')}")
        else:
            linked.append("❌ Emby: Not linked")
    
    if bot.plex:
        user = await bot.plex.get_user_by_discord_id(discord_id)
        if user:
            linked.append(f"✅ Plex: {user.get('username', 'Linked')}")
        else:
            linked.append("❌ Plex: Not linked")
    
    if linked:
        embed.add_field(name="Linked Accounts", value="\n".join(linked), inline=False)
    
    # Subscription status
    db_user = db.get_user_by_discord_id(discord_id)
    has_subscription = False
    if db_user:
        subscription = db.get_active_subscription(db_user.get("id"))
        has_subscription = subscription is not None
    
    sub_status = "✅ Active" if has_subscription else "❌ None"
    embed.add_field(name="Subscription", value=sub_status, inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============== ERROR HANDLING ==============

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Global error handler for prefix commands"""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command. Use `!help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: `{error.param.name}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided.")
    else:
        print(f"Error: {error}")
        await ctx.send("❌ An error occurred while processing your command.")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    """Global error handler for slash commands"""
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ Command on cooldown. Try again in {error.retry_after:.1f}s",
            ephemeral=True
        )
    else:
        print(f"App command error: {error}")
        await interaction.response.send_message(
            "❌ An error occurred while processing your command.",
            ephemeral=True
        )


# ============== MAIN ==============

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN not set in environment variables")
        print("Create a .env file with your Discord bot token")
        exit(1)
    
    print("Starting Media Server Bot...")
    print(f"Jellyfin configured: {bool(JELLYFIN_URL and JELLYFIN_API_KEY)}")
    print(f"Emby configured: {bool(EMBY_URL and EMBY_API_KEY)}")
    print(f"Plex configured: {bool(PLEX_URL and PLEX_TOKEN)}")
    
    bot.run(DISCORD_TOKEN)
