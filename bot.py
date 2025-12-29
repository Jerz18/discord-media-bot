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

# Link indicators - emoji/logo added to nickname based on which server is linked
# You can use custom Discord emoji IDs like <:jellyfin:123456789> for server emojis
JELLYFIN_INDICATOR = os.getenv("JELLYFIN_INDICATOR", "🪼")  # Jellyfin logo
EMBY_INDICATOR = os.getenv("EMBY_INDICATOR", "🟩")  # Emby logo
UNLINKED_INDICATOR = os.getenv("UNLINKED_INDICATOR", "🍄")  # Not linked to any server


async def get_linked_users(bot, discord_id: int, discord_username: str) -> dict:
    """Get linked users from all servers in parallel.
    Returns: {server_name: user_data} dict
    """
    tasks = {}
    if bot.jellyfin:
        tasks["Jellyfin"] = bot.jellyfin.get_user_by_discord_id(discord_id, discord_username)
    if bot.emby:
        tasks["Emby"] = bot.emby.get_user_by_discord_id(discord_id, discord_username)
    
    if not tasks:
        return {}
    
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    users = {}
    for server, result in zip(tasks.keys(), results):
        if result and not isinstance(result, Exception):
            users[server] = result
    return users


async def update_member_link_indicator(member: discord.Member, server_type: str = None):
    """Update link indicator on member's display name based on linked servers.
    
    Args:
        member: The Discord member
        server_type: Optional - the server that was just linked (for context)
    """
    try:
        current_nick = member.display_name
        
        # Remove all existing indicators
        clean_name = current_nick
        for ind in [JELLYFIN_INDICATOR, EMBY_INDICATOR, UNLINKED_INDICATOR]:
            if ind:
                clean_name = clean_name.replace(f" {ind}", "").replace(ind, "")
        clean_name = clean_name.strip()
        
        # Check what's linked in database
        db_user = db.get_user_by_discord_id(member.id)
        
        indicators = []
        if db_user:
            if db_user.get("jellyfin_id") and JELLYFIN_INDICATOR:
                indicators.append(JELLYFIN_INDICATOR)
            if db_user.get("emby_id") and EMBY_INDICATOR:
                indicators.append(EMBY_INDICATOR)
        
        # Build new nickname
        if indicators:
            indicator_str = " ".join(indicators)
            new_nick = f"{clean_name} {indicator_str}"
        elif UNLINKED_INDICATOR:
            new_nick = f"{clean_name} {UNLINKED_INDICATOR}"
        else:
            new_nick = clean_name
        
        # Only update if changed and within Discord's 32 char limit
        if new_nick != current_nick and len(new_nick) <= 32:
            await member.edit(nick=new_nick)
            return True
        elif len(new_nick) > 32:
            print(f"Cannot update nickname for {member.name}: exceeds 32 char limit")
            return False
            
    except discord.Forbidden:
        print(f"No permission to change nickname for {member.name}")
        return False
    except Exception as e:
        print(f"Error updating nickname for {member.name}: {e}")
        return False
    
    return True


async def remove_link_indicator(member: discord.Member):
    """Remove all link indicators from member's display name or set unlinked indicator."""
    try:
        current_nick = member.display_name
        
        # Remove all indicators
        clean_name = current_nick
        for ind in [JELLYFIN_INDICATOR, EMBY_INDICATOR, UNLINKED_INDICATOR]:
            if ind:
                clean_name = clean_name.replace(f" {ind}", "").replace(ind, "")
        clean_name = clean_name.strip()
        
        # Add unlinked indicator if configured
        if UNLINKED_INDICATOR:
            new_nick = f"{clean_name} {UNLINKED_INDICATOR}"
        else:
            new_nick = clean_name
        
        if new_nick != current_nick and len(new_nick) <= 32:
            await member.edit(nick=new_nick if new_nick != member.name else None)
            return True
    except discord.Forbidden:
        print(f"No permission to change nickname for {member.name}")
    except Exception as e:
        print(f"Error removing indicator for {member.name}: {e}")
    
    return False


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
    
    async def get_user_by_discord_id(self, discord_id: int, discord_username: str = None) -> Optional[dict]:
        """Get Jellyfin user linked to Discord ID, or try to match by username"""
        # First, check if user is explicitly linked in database
        user = db.get_user_by_discord_id(discord_id)
        if user and user.get("jellyfin_id"):
            return {
                "jellyfin_id": user.get("jellyfin_id"),
                "username": user.get("jellyfin_username"),
                "discord_id": discord_id
            }
        
        # If not linked, try to match by Discord username
        if discord_username:
            # Try exact match first
            jf_user = await self.get_user_by_username(discord_username)
            if jf_user:
                return {
                    "jellyfin_id": jf_user.get("Id"),
                    "username": jf_user.get("Name"),
                    "discord_id": discord_id,
                    "auto_matched": True
                }
            
            # Try matching without discriminator (e.g., "user#1234" -> "user")
            if "#" in discord_username:
                base_name = discord_username.split("#")[0]
                jf_user = await self.get_user_by_username(base_name)
                if jf_user:
                    return {
                        "jellyfin_id": jf_user.get("Id"),
                        "username": jf_user.get("Name"),
                        "discord_id": discord_id,
                        "auto_matched": True
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
    
    async def delete_user(self, user_id: str) -> bool:
        """Delete a user from Jellyfin"""
        try:
            async with self.session.delete(
                f"{self.url}/Users/{user_id}",
                headers=self.headers
            ) as resp:
                if resp.status in [200, 204]:
                    print(f"Jellyfin: Deleted user {user_id}")
                    return True
                else:
                    print(f"Jellyfin delete_user failed: {resp.status}")
        except Exception as e:
            print(f"Jellyfin delete_user error: {e}")
        return False
    
    async def reset_password(self, user_id: str) -> Optional[str]:
        """Reset user password and return new password"""
        import secrets
        new_password = secrets.token_urlsafe(12)
        try:
            # First, reset the password to empty (admin action)
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Password",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                json={"ResetPassword": True}
            ) as resp:
                if resp.status not in [200, 204]:
                    print(f"Jellyfin reset password step 1 failed: {resp.status}")
                    return None
            
            # Then set the new password
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Password",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                json={
                    "CurrentPw": "",
                    "NewPw": new_password
                }
            ) as resp:
                if resp.status in [200, 204]:
                    return new_password
                else:
                    print(f"Jellyfin reset password step 2 failed: {resp.status}")
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
                print(f"Jellyfin: Could not get user info for {user_id}")
                return False
            
            policy = user_info.get("Policy", {})
            
            # Check if user currently has access to all folders
            enable_all_folders = policy.get("EnableAllFolders", True)
            enabled_folders = list(policy.get("EnabledFolders", []))
            
            print(f"Jellyfin: EnableAllFolders currently: {enable_all_folders}")
            print(f"Jellyfin: Current enabled folders: {enabled_folders}")
            print(f"Jellyfin: Library ID to {'enable' if enable else 'disable'}: {library_id}")
            
            # If EnableAllFolders is true and we're disabling, we need to:
            # 1. Get ALL library IDs
            # 2. Add them all to EnabledFolders
            # 3. Then remove the one we want to disable
            if enable_all_folders and not enable:
                # Get all libraries and add their IDs
                all_libraries = await self.get_libraries()
                enabled_folders = []
                for lib in all_libraries:
                    lib_id = lib.get("ItemId") or lib.get("Id")
                    if lib_id:
                        enabled_folders.append(lib_id)
                print(f"Jellyfin: Populated all library IDs: {enabled_folders}")
            
            # Now modify the list
            if enable and library_id not in enabled_folders:
                enabled_folders.append(library_id)
            elif not enable and library_id in enabled_folders:
                enabled_folders.remove(library_id)
            
            # IMPORTANT: Must set EnableAllFolders to false for EnabledFolders to work
            policy["EnableAllFolders"] = False
            policy["EnabledFolders"] = enabled_folders
            
            print(f"Jellyfin: New enabled folders: {enabled_folders}")
            
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Policy",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                json=policy
            ) as resp:
                if resp.status in [200, 204]:
                    return True
                else:
                    print(f"Jellyfin set_library_access failed: {resp.status}")
                    return False
        except Exception as e:
            print(f"Jellyfin set_library_access error: {e}")
        return False
    
    async def get_libraries(self) -> list:
        """Get all media libraries"""
        try:
            async with self.session.get(
                f"{self.url}/Library/VirtualFolders",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    libraries = await resp.json()
                    print(f"Jellyfin get_libraries: Found {len(libraries)} libraries")
                    for lib in libraries:
                        print(f"  - '{lib.get('Name')}': {lib.get('ItemId')}")
                    return libraries
        except Exception as e:
            print(f"Jellyfin get_libraries error: {e}")
        return []
    
    async def get_library_id_by_name(self, library_name: str) -> Optional[str]:
        """Find library ID by name"""
        libraries = await self.get_libraries()
        print(f"Jellyfin: Looking for library '{library_name}'")
        for lib in libraries:
            lib_name = lib.get("Name", "")
            lib_id = lib.get("ItemId")
            if lib_name.lower() == library_name.lower():
                print(f"Jellyfin: Found match '{lib_name}' -> {lib_id}")
                return lib_id
        print(f"Jellyfin: Library '{library_name}' not found in available libraries")
        return None
    
    async def set_library_access_by_name(self, user_id: str, library_name: str, enable: bool) -> bool:
        """Enable or disable library access by library name"""
        library_id = await self.get_library_id_by_name(library_name)
        if not library_id:
            print(f"Jellyfin library not found: {library_name}")
            return False
        return await self.set_library_access(user_id, library_id, enable)
    
    async def get_watch_history(self, user_id: str, limit: int = 10000) -> list:
        """Get user's complete watch history with play duration"""
        history = []
        try:
            # Get played items
            async with self.session.get(
                f"{self.url}/Users/{user_id}/Items",
                headers=self.headers,
                params={
                    "Filters": "IsPlayed",
                    "Recursive": "true",
                    "Fields": "DateCreated,RunTimeTicks,UserData",
                    "IncludeItemTypes": "Movie,Episode",
                    "Limit": limit,
                    "SortBy": "DatePlayed",
                    "SortOrder": "Descending"
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("Items", [])
                    
                    for item in items:
                        user_data = item.get("UserData", {})
                        runtime_ticks = item.get("RunTimeTicks", 0)
                        
                        # Convert ticks to seconds (1 tick = 100 nanoseconds)
                        runtime_seconds = runtime_ticks // 10000000 if runtime_ticks else 0
                        
                        # Get play date
                        last_played = user_data.get("LastPlayedDate")
                        
                        if last_played and runtime_seconds > 0:
                            history.append({
                                "title": item.get("Name", "Unknown"),
                                "type": item.get("Type", "Unknown"),
                                "series": item.get("SeriesName", ""),
                                "runtime_seconds": runtime_seconds,
                                "played_date": last_played[:10] if last_played else None,  # YYYY-MM-DD
                                "play_count": user_data.get("PlayCount", 1)
                            })
        except Exception as e:
            print(f"Jellyfin get_watch_history error: {e}")
        
        return history
    
    async def get_playback_stats(self, user_id: str) -> dict:
        """Get aggregated playback statistics from Jellyfin"""
        stats = {
            "total_seconds": 0,
            "total_plays": 0,
            "movies": 0,
            "episodes": 0,
            "by_date": {}  # {date: seconds}
        }
        
        history = await self.get_watch_history(user_id)
        
        for item in history:
            runtime = item.get("runtime_seconds", 0)
            play_count = item.get("play_count", 1)
            played_date = item.get("played_date")
            item_type = item.get("type", "")
            
            stats["total_seconds"] += runtime * play_count
            stats["total_plays"] += play_count
            
            if item_type == "Movie":
                stats["movies"] += play_count
            elif item_type == "Episode":
                stats["episodes"] += play_count
            
            if played_date:
                if played_date not in stats["by_date"]:
                    stats["by_date"][played_date] = 0
                stats["by_date"][played_date] += runtime
        
        return stats
    
    async def get_user_watchtime(self, user_id: str, days: int = 30) -> dict:
        """Get user's total watchtime for the last N days"""
        from datetime import date, timedelta
        
        stats = {"total_seconds": 0, "total_plays": 0}
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        
        history = await self.get_watch_history(user_id)
        
        for item in history:
            played_date = item.get("played_date")
            if played_date and played_date >= cutoff_date:
                runtime = item.get("runtime_seconds", 0)
                play_count = item.get("play_count", 1)
                stats["total_seconds"] += runtime * play_count
                stats["total_plays"] += play_count
        
        return stats


class EmbyAPI(MediaServerAPI):
    """Emby API wrapper - Similar to Jellyfin"""
    
    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str):
        super().__init__(session)
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Emby-Token": api_key}
    
    async def get_user_by_discord_id(self, discord_id: int, discord_username: str = None) -> Optional[dict]:
        """Get Emby user linked to Discord ID, or try to match by username"""
        # First, check if user is explicitly linked in database
        user = db.get_user_by_discord_id(discord_id)
        if user and user.get("emby_id"):
            return {
                "emby_id": user.get("emby_id"),
                "username": user.get("emby_username"),
                "discord_id": discord_id
            }
        
        # If not linked, try to match by Discord username
        if discord_username:
            # Try exact match first
            emby_user = await self.get_user_by_username(discord_username)
            if emby_user:
                return {
                    "emby_id": emby_user.get("Id"),
                    "username": emby_user.get("Name"),
                    "discord_id": discord_id,
                    "auto_matched": True
                }
            
            # Try matching without discriminator (e.g., "user#1234" -> "user")
            if "#" in discord_username:
                base_name = discord_username.split("#")[0]
                emby_user = await self.get_user_by_username(base_name)
                if emby_user:
                    return {
                        "emby_id": emby_user.get("Id"),
                        "username": emby_user.get("Name"),
                        "discord_id": discord_id,
                        "auto_matched": True
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
    
    async def delete_user(self, user_id: str) -> bool:
        """Delete a user from Emby"""
        try:
            async with self.session.delete(
                f"{self.url}/Users/{user_id}",
                headers=self.headers
            ) as resp:
                if resp.status in [200, 204]:
                    print(f"Emby: Deleted user {user_id}")
                    return True
                else:
                    print(f"Emby delete_user failed: {resp.status}")
        except Exception as e:
            print(f"Emby delete_user error: {e}")
        return False
    
    async def reset_password(self, user_id: str) -> Optional[str]:
        """Reset user password and return new password"""
        import secrets
        new_password = secrets.token_urlsafe(12)
        try:
            # First, reset the password to empty (admin action)
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Password",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                json={"ResetPassword": True}
            ) as resp:
                if resp.status not in [200, 204]:
                    print(f"Emby reset password step 1 failed: {resp.status}")
                    return None
            
            # Then set the new password
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Password",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                json={
                    "CurrentPw": "",
                    "NewPw": new_password
                }
            ) as resp:
                if resp.status in [200, 204]:
                    return new_password
                else:
                    print(f"Emby reset password step 2 failed: {resp.status}")
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
                print(f"Emby: Could not get user info for {user_id}")
                return False
            
            policy = user_info.get("Policy", {})
            
            # Check if user currently has access to all folders
            enable_all_folders = policy.get("EnableAllFolders", True)
            enabled_folders = list(policy.get("EnabledFolders", []))
            
            # Convert library_id to string for comparison
            library_id = str(library_id)
            
            # Convert all existing folder IDs to strings for consistent comparison
            enabled_folders = [str(f) for f in enabled_folders]
            
            print(f"Emby: EnableAllFolders currently: {enable_all_folders}")
            print(f"Emby: Current enabled folders: {enabled_folders}")
            print(f"Emby: Library ID to {'enable' if enable else 'disable'}: {library_id}")
            
            # If EnableAllFolders is true and we're disabling, we need to:
            # 1. Get ALL library IDs
            # 2. Add them all to EnabledFolders
            # 3. Then remove the one we want to disable
            if enable_all_folders and not enable:
                # Get all libraries and add their IDs
                all_libraries = await self.get_libraries()
                enabled_folders = []
                for lib in all_libraries:
                    lib_id = lib.get("ItemId") or lib.get("Id")
                    if lib_id:
                        enabled_folders.append(str(lib_id))
                print(f"Emby: Populated all library IDs: {enabled_folders}")
            
            # Now modify the list
            if enable and library_id not in enabled_folders:
                enabled_folders.append(library_id)
            elif not enable and library_id in enabled_folders:
                enabled_folders.remove(library_id)
            
            # IMPORTANT: Must set EnableAllFolders to false for EnabledFolders to work
            policy["EnableAllFolders"] = False
            policy["EnabledFolders"] = enabled_folders
            
            print(f"Emby: New enabled folders: {enabled_folders}")
            
            # Use the correct Emby API endpoint for updating user policy
            async with self.session.post(
                f"{self.url}/Users/{user_id}/Policy",
                headers={
                    **self.headers,
                    "Content-Type": "application/json"
                },
                json=policy
            ) as resp:
                response_text = await resp.text()
                print(f"Emby set_library_access response: {resp.status} - {response_text[:200] if response_text else 'empty'}")
                if resp.status in [200, 204]:
                    return True
                else:
                    print(f"Emby set_library_access failed: {resp.status}")
                    return False
        except Exception as e:
            print(f"Emby set_library_access error: {e}")
        return False
    
    async def get_libraries(self) -> list:
        """Get all media libraries with their GUIDs"""
        libraries = []
        
        # Get VirtualFolders for library names and count
        vf_libraries = []
        try:
            async with self.session.get(
                f"{self.url}/Library/VirtualFolders",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    vf_libraries = await resp.json()
                    print(f"Emby: Found {len(vf_libraries)} virtual folders")
        except Exception as e:
            print(f"Emby get VirtualFolders error: {e}")
        
        # Build a mapping of library names to find GUIDs
        vf_names = {lib.get("Name").lower(): lib.get("Name") for lib in vf_libraries}
        found_guids = {}  # name -> guid
        
        # Check ALL users to collect GUIDs from their EnabledFolders
        try:
            users = await self.get_all_users()
            print(f"Emby: Checking {len(users)} users for library GUIDs")
            
            for user in users:
                user_id = user.get("Id")
                user_name = user.get("Name")
                user_info = await self.get_user_info(user_id)
                
                if user_info:
                    policy = user_info.get("Policy", {})
                    enabled_guids = policy.get("EnabledFolders", [])
                    
                    if enabled_guids:
                        # Query each GUID to get its name
                        for guid in enabled_guids:
                            if guid in [g for g in found_guids.values()]:
                                continue  # Already found this GUID
                            
                            try:
                                async with self.session.get(
                                    f"{self.url}/Users/{user_id}/Items/{guid}",
                                    headers=self.headers
                                ) as item_resp:
                                    if item_resp.status == 200:
                                        item_data = await item_resp.json()
                                        item_name = item_data.get("Name")
                                        if item_name and item_name.lower() in vf_names:
                                            found_guids[item_name] = guid
                                            print(f"  Found: {item_name} -> {guid}")
                            except Exception as e:
                                pass
                
                # If we found all libraries, stop searching
                if len(found_guids) >= len(vf_libraries):
                    break
            
            print(f"Emby: Found GUIDs for {len(found_guids)}/{len(vf_libraries)} libraries")
            
            # Build library list with found GUIDs
            if found_guids:
                for lib in vf_libraries:
                    lib_name = lib.get("Name")
                    guid = found_guids.get(lib_name)
                    if guid:
                        libraries.append({
                            "Name": lib_name,
                            "Id": guid
                        })
                        print(f"  - {lib_name}: {guid} (GUID)")
                    else:
                        # Fallback to numeric ID if GUID not found
                        numeric_id = str(lib.get("ItemId"))
                        libraries.append({
                            "Name": lib_name,
                            "Id": numeric_id
                        })
                        print(f"  - {lib_name}: {numeric_id} (numeric, no GUID found)")
                
                return libraries
                
        except Exception as e:
            print(f"Emby get_libraries (GUID lookup) error: {e}")
        
        # Fallback: Return VirtualFolders with numeric IDs
        print("Emby: Falling back to VirtualFolders (numeric IDs)")
        for lib in vf_libraries:
            lib_name = lib.get("Name")
            item_id = lib.get("ItemId")
            print(f"  - {lib_name}: {item_id} (numeric)")
            libraries.append({
                "Name": lib_name,
                "Id": str(item_id)
            })
        
        return libraries
    
    async def get_library_id_by_name(self, library_name: str) -> Optional[str]:
        """Find library ID (GUID) by name"""
        libraries = await self.get_libraries()
        print(f"Emby: Looking for library '{library_name}' in {len(libraries)} libraries")
        for lib in libraries:
            lib_name = lib.get("Name", "")
            lib_id = lib.get("Id")
            print(f"Emby:   Checking '{lib_name}' (ID: {lib_id})")
            if lib_name.lower() == library_name.lower():
                print(f"Emby: Found match! Library ID: {lib_id}")
                return str(lib_id)
        print(f"Emby: Library '{library_name}' not found")
        return None
    
    async def set_library_access_by_name(self, user_id: str, library_name: str, enable: bool) -> bool:
        """Enable or disable library access by library name"""
        library_id = await self.get_library_id_by_name(library_name)
        if not library_id:
            print(f"Emby library not found: {library_name}")
            return False
        return await self.set_library_access(user_id, library_id, enable)
    
    async def get_watch_history(self, user_id: str, limit: int = 10000) -> list:
        """Get user's complete watch history with play duration"""
        history = []
        
        # Try the Items endpoint
        try:
            async with self.session.get(
                f"{self.url}/Users/{user_id}/Items",
                headers=self.headers,
                params={
                    "Filters": "IsPlayed",
                    "Recursive": "true",
                    "Fields": "DateCreated,RunTimeTicks,UserData,MediaSources,DateLastMediaAdded",
                    "IncludeItemTypes": "Movie,Episode",
                    "Limit": limit,
                    "SortBy": "DatePlayed,DateCreated",
                    "SortOrder": "Descending"
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("Items", [])
                    print(f"Emby: Found {len(items)} played items for user {user_id}")
                    
                    for item in items:
                        user_data = item.get("UserData", {})
                        runtime_ticks = item.get("RunTimeTicks", 0)
                        runtime_seconds = runtime_ticks // 10000000 if runtime_ticks else 0
                        
                        # Emby may not have LastPlayedDate, use DateCreated or current date as fallback
                        last_played = user_data.get("LastPlayedDate")
                        if not last_played:
                            # Try other date fields
                            last_played = item.get("DateCreated") or item.get("PremiereDate")
                        
                        # For played items, ensure at least 1 play count
                        play_count = user_data.get("PlayCount", 0)
                        is_played = user_data.get("Played", False)
                        if is_played and play_count == 0:
                            play_count = 1
                        
                        if runtime_seconds > 0 and play_count > 0:
                            # Use today's date if no date available (item was played but date unknown)
                            played_date = last_played[:10] if last_played else datetime.now().strftime("%Y-%m-%d")
                            
                            history.append({
                                "title": item.get("Name", "Unknown"),
                                "type": item.get("Type", "Unknown"),
                                "series": item.get("SeriesName", ""),
                                "runtime_seconds": runtime_seconds,
                                "played_date": played_date,
                                "play_count": play_count
                            })
                else:
                    print(f"Emby get_watch_history: Status {resp.status}")
        except Exception as e:
            print(f"Emby get_watch_history error: {e}")
        
        print(f"Emby: Returning {len(history)} history items with valid data")
        return history
    
    async def get_playback_stats(self, user_id: str) -> dict:
        """Get aggregated playback statistics from Emby"""
        stats = {
            "total_seconds": 0,
            "total_plays": 0,
            "movies": 0,
            "episodes": 0,
            "by_date": {}
        }
        
        history = await self.get_watch_history(user_id)
        
        for item in history:
            runtime = item.get("runtime_seconds", 0)
            play_count = item.get("play_count", 1)
            played_date = item.get("played_date")
            item_type = item.get("type", "")
            
            stats["total_seconds"] += runtime * play_count
            stats["total_plays"] += play_count
            
            if item_type == "Movie":
                stats["movies"] += play_count
            elif item_type == "Episode":
                stats["episodes"] += play_count
            
            if played_date:
                if played_date not in stats["by_date"]:
                    stats["by_date"][played_date] = 0
                stats["by_date"][played_date] += runtime
        
        return stats
    
    async def get_user_watchtime(self, user_id: str, days: int = 30) -> dict:
        """Get user's total watchtime for the last N days
        
        Note: Emby may not provide accurate LastPlayedDate, so we return 
        all played content if dates are not available.
        """
        from datetime import date, timedelta
        
        stats = {"total_seconds": 0, "total_plays": 0}
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()
        
        history = await self.get_watch_history(user_id)
        
        has_valid_dates = False
        for item in history:
            played_date = item.get("played_date")
            runtime = item.get("runtime_seconds", 0)
            play_count = item.get("play_count", 1)
            
            # Check if this looks like a real play date (not just DateCreated fallback)
            # If we have dates in the recent period, use date filtering
            if played_date and played_date >= cutoff_date:
                has_valid_dates = True
                stats["total_seconds"] += runtime * play_count
                stats["total_plays"] += play_count
        
        # If no items matched the date filter, Emby might not have proper dates
        # In that case, return all played content as "recent"
        if not has_valid_dates and history:
            print(f"Emby: No valid play dates found, counting all {len(history)} played items")
            for item in history:
                runtime = item.get("runtime_seconds", 0)
                play_count = item.get("play_count", 1)
                stats["total_seconds"] += runtime * play_count
                stats["total_plays"] += play_count
        
        print(f"Emby watchtime: {stats['total_seconds']} seconds, {stats['total_plays']} plays")
        return stats



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
    
    async def setup_hook(self):
        """Initialize API clients and sync commands"""
        self.session = aiohttp.ClientSession()
        
        if JELLYFIN_URL and JELLYFIN_API_KEY:
            self.jellyfin = JellyfinAPI(self.session, JELLYFIN_URL, JELLYFIN_API_KEY)
        
        if EMBY_URL and EMBY_API_KEY:
            self.emby = EmbyAPI(self.session, EMBY_URL, EMBY_API_KEY)
        
        await self.tree.sync()
    
    async def close(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
        await super().close()
    
    async def on_ready(self):
        print(f"Bot is ready! Logged in as {self.user}")
        print(f"Connected servers: {len(self.guilds)}")
        print(f"Jellyfin configured: {self.jellyfin is not None}")
        print(f"Emby configured: {self.emby is not None}")
        
        # Sync existing users from media servers to database
        await self.sync_existing_users()
        
        # Set activity
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="your media servers | !help"
            )
        )
    
    async def sync_existing_users(self):
        """Sync all existing users from Jellyfin/Emby to the database"""
        print("Syncing existing users from media servers...")
        synced_count = 0
        
        # Sync Jellyfin users
        if self.jellyfin:
            try:
                jf_users = await self.jellyfin.get_all_users()
                for user in jf_users:
                    user_id = user.get("Id")
                    username = user.get("Name")
                    is_admin = user.get("Policy", {}).get("IsAdministrator", False)
                    
                    if is_admin:
                        continue  # Skip admin users
                    
                    # Check if user already exists in database by username
                    existing = db.get_user_by_server_id(user_id, "jellyfin")
                    if not existing:
                        # Create user in database
                        db_user_id = db.create_server_user(username, user_id, "jellyfin")
                        if db_user_id:
                            synced_count += 1
                            print(f"  Synced Jellyfin user: {username}")
            except Exception as e:
                print(f"Error syncing Jellyfin users: {e}")
        
        # Sync Emby users
        if self.emby:
            try:
                emby_users = await self.emby.get_all_users()
                for user in emby_users:
                    user_id = user.get("Id")
                    username = user.get("Name")
                    is_admin = user.get("Policy", {}).get("IsAdministrator", False)
                    
                    if is_admin:
                        continue  # Skip admin users
                    
                    # Check if user already exists in database by username
                    existing = db.get_user_by_server_id(user_id, "emby")
                    if not existing:
                        # Create user in database
                        db_user_id = db.create_server_user(username, user_id, "emby")
                        if db_user_id:
                            synced_count += 1
                            print(f"  Synced Emby user: {username}")
            except Exception as e:
                print(f"Error syncing Emby users: {e}")
        
        print(f"User sync complete. {synced_count} new users added to database.")
        
        # Sync link indicators for all Discord members
        await self.sync_link_indicators()
    
    async def sync_link_indicators(self):
        """Sync link indicators for all Discord members based on their linked accounts"""
        print("Syncing link indicators for Discord members...")
        updated_count = 0
        error_count = 0
        
        for guild in self.guilds:
            print(f"  Processing guild: {guild.name}")
            
            for member in guild.members:
                if member.bot:
                    continue
                
                try:
                    # Update indicator for ALL members (linked or not)
                    result = await update_member_link_indicator(member)
                    if result:
                        updated_count += 1
                except Exception as e:
                    error_count += 1
                    if error_count <= 5:  # Only log first 5 errors
                        print(f"    Error updating {member.name}: {e}")
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)
        
        print(f"Link indicator sync complete. {updated_count} members updated, {error_count} errors.")


# Create bot instance
bot = MediaServerBot()


# Library mapping for each server
# Format: command_name -> {server: library_name}
# IMPORTANT: These names must EXACTLY match your library names in each server
LIBRARY_MAPPING = {
    "4kmovies": {
        "display": "4K Movies",
        "jellyfin": "4KMovies",      # Jellyfin has no space
        "emby": "4K Movies"          # Emby has space
    },
    "movies": {
        "display": "Movies",
        "jellyfin": "Movies",
        "emby": "Movies"
    },
    "shows": {
        "display": "Shows",
        "jellyfin": "Shows",
        "emby": "Shows"
    },
    "animemovies": {
        "display": "Anime Movies",
        "jellyfin": "Anime Movies",
        "emby": "Anime Movies"
    },
    "animeshows": {
        "display": "Anime Shows",
        "jellyfin": "Anime Shows",
        "emby": "Anime Shows"
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
    """Check your watchtime for the last 30 days with detailed breakdown"""
    discord_id = ctx.author.id
    discord_username = ctx.author.name
    
    username = ctx.author.display_name
    server_stats = {}  # {server_name: {total_seconds, total_plays, by_date}}
    
    # Gather user lookups in parallel
    tasks = {}
    if bot.jellyfin:
        tasks["Jellyfin"] = bot.jellyfin.get_user_by_discord_id(discord_id, discord_username)
    if bot.emby:
        tasks["Emby"] = bot.emby.get_user_by_discord_id(discord_id, discord_username)
    
    users = {}
    if tasks:
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for server, result in zip(tasks.keys(), results):
            if result and not isinstance(result, Exception):
                users[server] = result
                if not username or username == ctx.author.display_name:
                    username = result.get("username", username)
    
    if not users:
        embed = create_embed("⏱️ Watchtime", "")
        embed.description = "❌ No linked accounts found. Use `!link` to link your account first."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Gather stats in parallel
    stats_tasks = {}
    for server, user in users.items():
        if server == "Jellyfin" and bot.jellyfin:
            stats_tasks[server] = bot.jellyfin.get_playback_stats(user.get("jellyfin_id"))
        elif server == "Emby" and bot.emby:
            stats_tasks[server] = bot.emby.get_playback_stats(user.get("emby_id"))
    
    if stats_tasks:
        results = await asyncio.gather(*stats_tasks.values(), return_exceptions=True)
        from datetime import date
        today = date.today()
        cutoff = (today - timedelta(days=30)).isoformat()
        
        for server, result in zip(stats_tasks.keys(), results):
            if result and not isinstance(result, Exception):
                # Filter to last 30 days
                filtered_seconds = 0
                filtered_plays = 0
                by_date = {}
                
                for d, secs in result.get("by_date", {}).items():
                    if d >= cutoff:
                        filtered_seconds += secs
                        by_date[d] = secs
                
                # If no valid dates (Emby issue), use totals
                if filtered_seconds == 0 and result.get("total_seconds", 0) > 0:
                    filtered_seconds = result.get("total_seconds", 0)
                    filtered_plays = result.get("total_plays", 0)
                else:
                    # Estimate plays from the ratio
                    total_secs = result.get("total_seconds", 1)
                    total_plays = result.get("total_plays", 0)
                    if total_secs > 0:
                        filtered_plays = int(total_plays * (filtered_seconds / total_secs))
                
                server_stats[server] = {
                    "total_seconds": filtered_seconds,
                    "total_plays": filtered_plays,
                    "by_date": by_date
                }
    
    if not server_stats:
        embed = create_embed("⏱️ Watchtime", "")
        embed.description = "❌ Could not fetch watchtime data."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Calculate totals
    grand_total_seconds = sum(s["total_seconds"] for s in server_stats.values())
    grand_total_plays = sum(s["total_plays"] for s in server_stats.values())
    grand_total_hours = grand_total_seconds / 3600
    
    # Merge by_date from all servers
    all_dates = {}
    for server, stats in server_stats.items():
        for d, secs in stats.get("by_date", {}).items():
            if d not in all_dates:
                all_dates[d] = 0
            all_dates[d] += secs
    
    # Calculate daily average
    days_with_activity = len(all_dates) if all_dates else 1
    daily_avg_hours = (grand_total_seconds / 3600) / max(days_with_activity, 1)
    
    # Calculate weekly breakdown (last 4 weeks)
    from datetime import date
    today = date.today()
    weekly_hours = [0, 0, 0, 0]  # Week 1 (most recent) to Week 4
    
    for d_str, secs in all_dates.items():
        try:
            d = date.fromisoformat(d_str)
            days_ago = (today - d).days
            week_idx = min(days_ago // 7, 3)
            weekly_hours[week_idx] += secs / 3600
        except:
            pass
    
    # Build embed
    embed = discord.Embed(
        title=f"⏱️ {username}'s Watchtime",
        color=discord.Color.blue()
    )
    
    period_start = today - timedelta(days=29)
    period_str = f"{period_start.strftime('%d %b')} - {today.strftime('%d %b')}"
    embed.description = f"**Last 30 Days** ({period_str})"
    
    # Summary
    embed.add_field(
        name="📊 Summary",
        value=f"⏱️ **{grand_total_hours:.1f}h** total\n🎬 **{grand_total_plays}** plays\n📅 **{daily_avg_hours:.1f}h** daily avg",
        inline=True
    )
    
    # Weekly breakdown
    week_labels = ["This Week", "Last Week", "2 Weeks Ago", "3 Weeks Ago"]
    weekly_str = "\n".join([f"{week_labels[i]}: **{weekly_hours[i]:.1f}h**" for i in range(4)])
    embed.add_field(
        name="📅 Weekly",
        value=weekly_str,
        inline=True
    )
    
    # Per-server breakdown
    if len(server_stats) > 1:
        server_str = ""
        for server, stats in server_stats.items():
            hours = stats["total_seconds"] / 3600
            plays = stats["total_plays"]
            server_str += f"**{server}**: {hours:.1f}h ({plays} plays)\n"
        embed.add_field(name="🖥️ Per Server", value=server_str.strip(), inline=True)
    else:
        server_name = list(server_stats.keys())[0]
        embed.add_field(name="🖥️ Server", value=f"**{server_name}**", inline=True)
    
    embed.set_footer(text="Media Server Bot")
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
    """Check your total all-time watchtime with detailed breakdown"""
    discord_id = ctx.author.id
    discord_username = ctx.author.name
    
    username = ctx.author.display_name
    server_stats = {}  # {server_name: {total_seconds, total_plays, movies, episodes, by_date}}
    
    # Gather user lookups in parallel
    tasks = {}
    if bot.jellyfin:
        tasks["Jellyfin"] = bot.jellyfin.get_user_by_discord_id(discord_id, discord_username)
    if bot.emby:
        tasks["Emby"] = bot.emby.get_user_by_discord_id(discord_id, discord_username)
    
    users = {}
    if tasks:
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for server, result in zip(tasks.keys(), results):
            if result and not isinstance(result, Exception):
                users[server] = result
                if not username or username == ctx.author.display_name:
                    username = result.get("username", username)
    
    if not users:
        embed = create_embed("📊 Total Watchtime", "")
        embed.description = "❌ No linked accounts found. Use `!link` to link your account first."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Gather stats in parallel
    stats_tasks = {}
    for server, user in users.items():
        if server == "Jellyfin" and bot.jellyfin:
            stats_tasks[server] = bot.jellyfin.get_playback_stats(user.get("jellyfin_id"))
        elif server == "Emby" and bot.emby:
            stats_tasks[server] = bot.emby.get_playback_stats(user.get("emby_id"))
    
    if stats_tasks:
        results = await asyncio.gather(*stats_tasks.values(), return_exceptions=True)
        for server, result in zip(stats_tasks.keys(), results):
            if result and not isinstance(result, Exception):
                server_stats[server] = {
                    "total_seconds": result.get("total_seconds", 0),
                    "total_plays": result.get("total_plays", 0),
                    "movies": result.get("movies", 0),
                    "episodes": result.get("episodes", 0),
                    "by_date": result.get("by_date", {})
                }
    
    if not server_stats:
        embed = create_embed("📊 Total Watchtime", "")
        embed.description = "❌ No linked accounts found. Use `!link` to link your account first."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Calculate grand totals
    grand_total_seconds = sum(s["total_seconds"] for s in server_stats.values())
    grand_total_plays = sum(s["total_plays"] for s in server_stats.values())
    grand_movies = sum(s["movies"] for s in server_stats.values())
    grand_episodes = sum(s["episodes"] for s in server_stats.values())
    
    # Merge by_date from all servers
    all_dates = {}
    for server, stats in server_stats.items():
        for d, secs in stats.get("by_date", {}).items():
            if d not in all_dates:
                all_dates[d] = 0
            all_dates[d] += secs
    
    # Calculate monthly breakdown (last 6 months)
    from datetime import date
    today = date.today()
    monthly_hours = {}  # {YYYY-MM: hours}
    
    for d_str, secs in all_dates.items():
        try:
            month_key = d_str[:7]  # YYYY-MM
            if month_key not in monthly_hours:
                monthly_hours[month_key] = 0
            monthly_hours[month_key] += secs / 3600
        except:
            pass
    
    # Sort months and get last 6
    sorted_months = sorted(monthly_hours.keys(), reverse=True)[:6]
    
    # Format total time
    total_hours = grand_total_seconds // 3600
    total_days = total_hours // 24
    remaining_hours = total_hours % 24
    
    if total_days > 0:
        total_time_str = f"{total_days}d {remaining_hours}h"
    else:
        total_time_str = format_duration(grand_total_seconds)
    
    # Build embed
    embed = discord.Embed(
        title=f"📊 {username}'s Total Watchtime",
        color=discord.Color.blue()
    )
    embed.description = "**All-Time Statistics**"
    
    # Summary stats
    summary = f"⏱️ **{total_time_str}** ({total_hours:,} hours)\n"
    summary += f"▶️ **{grand_total_plays:,}** plays\n"
    summary += f"🎬 **{grand_movies:,}** movies\n"
    summary += f"📺 **{grand_episodes:,}** episodes"
    embed.add_field(name="📊 Summary", value=summary, inline=True)
    
    # Monthly breakdown (if we have date data)
    if sorted_months:
        monthly_str = ""
        for month in sorted_months[:6]:
            try:
                month_date = date.fromisoformat(f"{month}-01")
                month_name = month_date.strftime("%b %Y")
                hours = monthly_hours[month]
                monthly_str += f"{month_name}: **{hours:.1f}h**\n"
            except:
                pass
        if monthly_str:
            embed.add_field(name="📅 Monthly", value=monthly_str.strip(), inline=True)
    
    # Per-server breakdown
    if len(server_stats) > 1:
        server_str = ""
        for server, stats in server_stats.items():
            hours = stats["total_seconds"] / 3600
            plays = stats["total_plays"]
            movies = stats["movies"]
            episodes = stats["episodes"]
            server_str += f"**{server}**\n"
            server_str += f"└ {hours:.1f}h • {plays} plays\n"
            server_str += f"└ 🎬 {movies} • 📺 {episodes}\n"
        embed.add_field(name="🖥️ Per Server", value=server_str.strip(), inline=False)
    else:
        server_name = list(server_stats.keys())[0]
        embed.add_field(name="🖥️ Server", value=f"**{server_name}**", inline=True)
    
    # Calculate some fun stats
    if grand_total_seconds > 0:
        avg_movie_length = 7200  # 2 hours
        avg_episode_length = 2700  # 45 min
        estimated_content = (grand_movies * avg_movie_length + grand_episodes * avg_episode_length)
        
        fun_stats = []
        if total_days >= 1:
            fun_stats.append(f"🌙 **{total_days}** days of content")
        if grand_total_plays > 100:
            fun_stats.append(f"🔥 Power viewer!")
        
        if fun_stats:
            embed.add_field(name="🏆 Achievements", value="\n".join(fun_stats), inline=False)
    
    embed.set_footer(text="All-time statistics from server")
    embed.timestamp = datetime.now(timezone.utc)
    
    await ctx.send(embed=embed)


@bot.command(name="devices")
async def devices(ctx: commands.Context):
    """Lists the devices currently connected to your account"""
    embed = create_embed("📱 Connected Devices", "Fetching your devices...")
    
    discord_id = ctx.author.id
    discord_username = ctx.author.name
    
    # Get users in parallel
    users = await get_linked_users(bot, discord_id, discord_username)
    
    if not users:
        embed.description = "No devices found or no linked accounts."
        embed.color = discord.Color.orange()
        await ctx.send(embed=embed)
        return
    
    # Get devices in parallel
    device_tasks = {}
    for server, user in users.items():
        if server == "Jellyfin" and bot.jellyfin:
            device_tasks[server] = bot.jellyfin.get_devices(user.get("jellyfin_id"))
        elif server == "Emby" and bot.emby:
            device_tasks[server] = bot.emby.get_devices(user.get("emby_id"))
    
    all_devices = []
    if device_tasks:
        results = await asyncio.gather(*device_tasks.values(), return_exceptions=True)
        for server, result in zip(device_tasks.keys(), results):
            if result and not isinstance(result, Exception):
                for device in result:
                    all_devices.append(
                        f"**[{server}]** {device.get('Name', 'Unknown')} - "
                        f"{device.get('AppName', 'Unknown App')}"
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
        embed.description = "No devices found."
        embed.color = discord.Color.orange()
    
    await ctx.send(embed=embed)


@bot.command(name="reset_devices")
async def reset_devices(ctx: commands.Context):
    """Deletes all your connected devices from the account (Jellyfin or Emby)"""
    embed = create_embed("🔄 Reset Devices", "Removing all connected devices...")
    
    discord_id = ctx.author.id
    discord_username = ctx.author.name
    
    # Get users in parallel
    users = await get_linked_users(bot, discord_id, discord_username)
    
    if not users:
        embed.description = "❌ No linked Jellyfin or Emby accounts found."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Delete devices in parallel
    delete_tasks = {}
    for server, user in users.items():
        if server == "Jellyfin" and bot.jellyfin:
            delete_tasks[server] = bot.jellyfin.delete_devices(user.get("jellyfin_id"))
        elif server == "Emby" and bot.emby:
            delete_tasks[server] = bot.emby.delete_devices(user.get("emby_id"))
    
    results = []
    if delete_tasks:
        task_results = await asyncio.gather(*delete_tasks.values(), return_exceptions=True)
        for server, result in zip(delete_tasks.keys(), task_results):
            if isinstance(result, Exception):
                results.append(f"**{server}:** ❌ Error")
            else:
                status = "✅ Cleared" if result else "❌ Failed"
                results.append(f"**{server}:** {status}")
    
    embed.description = "\n".join(results)
    embed.add_field(
        name="Note",
        value="You may need to sign in again on your devices.",
        inline=False
    )
    
    await ctx.send(embed=embed)


@bot.command(name="reset_password")
async def reset_password(ctx: commands.Context):
    """Resets your password and sends you the new credentials (Jellyfin or Emby)"""
    # Send initial response
    await ctx.send("🔐 Resetting your password... Check your DMs!")
    
    discord_id = ctx.author.id
    discord_username = ctx.author.name
    
    # Get users in parallel
    users = await get_linked_users(bot, discord_id, discord_username)
    
    if not users:
        await ctx.send("❌ No linked Jellyfin or Emby accounts found.")
        return
    
    # Reset passwords in parallel
    reset_tasks = {}
    for server, user in users.items():
        if server == "Jellyfin" and bot.jellyfin:
            reset_tasks[server] = (bot.jellyfin.reset_password(user.get("jellyfin_id")), user)
        elif server == "Emby" and bot.emby:
            reset_tasks[server] = (bot.emby.reset_password(user.get("emby_id")), user)
    
    results = []
    task_coros = [t[0] for t in reset_tasks.values()]
    if task_coros:
        task_results = await asyncio.gather(*task_coros, return_exceptions=True)
        for (server, (_, user)), result in zip(reset_tasks.items(), task_results):
            if isinstance(result, Exception) or not result:
                results.append(f"**{server}:** ❌ Failed to reset password")
            else:
                results.append(f"**{server}**\nUsername: {user.get('username')}\nNew Password: ||{result}||")
    
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


@bot.command(name="stream")
async def stream(ctx: commands.Context):
    """Shows details about current streaming tracks"""
    embed = discord.Embed(
        title="🎬 Active Streams",
        color=discord.Color.blue()
    )
    
    # Fetch streams from all servers in parallel
    stream_tasks = {}
    if bot.jellyfin:
        stream_tasks["Jellyfin"] = bot.jellyfin.get_active_streams()
    if bot.emby:
        stream_tasks["Emby"] = bot.emby.get_active_streams()
    
    all_streams = []
    stream_count = 0
    transcode_count = 0
    direct_count = 0
    
    if stream_tasks:
        results = await asyncio.gather(*stream_tasks.values(), return_exceptions=True)
        
        for server, streams in zip(stream_tasks.keys(), results):
            if isinstance(streams, Exception) or not streams:
                continue
                
            for s in streams:
                stream_count += 1
                item = s.get("NowPlayingItem", {})
                play_state = s.get("PlayState", {})
                transcode_info = s.get("TranscodingInfo")
                
                user = s.get("UserName", "Unknown")
                title = item.get("Name", "Unknown")
                series_name = item.get("SeriesName", "")
                stream_type = item.get("Type", "Unknown")
                
                # Build title with series name if it's an episode
                if series_name:
                    display_title = f"{series_name} - {title}"
                else:
                    display_title = title
                
                # Get quality info
                media_streams = item.get("MediaStreams", [])
                video_stream = next((m for m in media_streams if m.get("Type") == "Video"), {})
                resolution = video_stream.get("Height", 0)
                if resolution >= 2160:
                    quality = "4K"
                elif resolution >= 1080:
                    quality = "1080p"
                elif resolution >= 720:
                    quality = "720p"
                else:
                    quality = f"{resolution}p" if resolution else "Unknown"
                
                # Get progress
                position_ticks = play_state.get("PositionTicks", 0)
                runtime_ticks = item.get("RunTimeTicks", 1)
                if runtime_ticks > 0:
                    progress_pct = int((position_ticks / runtime_ticks) * 100)
                    position_min = int(position_ticks / 600000000)
                    runtime_min = int(runtime_ticks / 600000000)
                    progress = f"{position_min}m / {runtime_min}m ({progress_pct}%)"
                else:
                    progress = "Unknown"
                
                # Transcoding or Direct Play
                if transcode_info:
                    transcode_count += 1
                    play_method = "🔄 Transcode"
                    transcode_reason = transcode_info.get("TranscodeReasons", ["Unknown"])
                    if isinstance(transcode_reason, list):
                        transcode_reason = transcode_reason[0] if transcode_reason else "Unknown"
                else:
                    direct_count += 1
                    play_method = "▶️ Direct Play"
                    transcode_reason = None
                
                # Device/Client
                client = s.get("Client", "Unknown")
                device = s.get("DeviceName", "Unknown")
                
                # Build stream info
                stream_info = f"**[{server}] {user}**\n"
                stream_info += f"📺 {display_title}\n"
                stream_info += f"🎬 {stream_type} • {quality} • {play_method}\n"
                stream_info += f"⏱️ {progress}\n"
                stream_info += f"📱 {client} ({device})"
                if transcode_reason:
                    stream_info += f"\n⚠️ Reason: {transcode_reason}"
                
                all_streams.append(stream_info)
    
    if all_streams:
        # Add each stream as a separate section
        embed.description = "\n\n".join(all_streams)
        
        # Summary footer
        embed.add_field(name="📊 Total Streams", value=str(stream_count), inline=True)
        embed.add_field(name="▶️ Direct Play", value=str(direct_count), inline=True)
        embed.add_field(name="🔄 Transcoding", value=str(transcode_count), inline=True)
        
        embed.color = discord.Color.green()
    else:
        embed.description = "No active streams at the moment."
        embed.color = discord.Color.orange()
    
    embed.set_footer(text=f"Requested by {ctx.author.display_name} • {datetime.now(timezone.utc).strftime('%m/%d/%Y %I:%M %p')}")
    embed.timestamp = datetime.now(timezone.utc)
    
    await ctx.send(embed=embed)


@bot.command(name="status")
async def status(ctx: commands.Context):
    """Displays the current operational status and health of the server"""
    discord_id = ctx.author.id
    
    # Get user info for the header
    db_user = db.get_user_by_discord_id(discord_id)
    username = ctx.author.display_name
    
    import time
    
    # Build tasks for parallel execution
    info_tasks = {}
    start_times = {}
    
    if bot.jellyfin:
        start_times["Jellyfin"] = time.time()
        info_tasks["Jellyfin"] = bot.jellyfin.get_server_info()
    if bot.emby:
        start_times["Emby"] = time.time()
        info_tasks["Emby"] = bot.emby.get_server_info()
    
    server_name = "Media Server"
    server_online = False
    latency_ms = 0
    streams_data = {"total": 0, "transcoding": 0, "direct": 0}
    
    if info_tasks:
        # Get server info in parallel
        results = await asyncio.gather(*info_tasks.values(), return_exceptions=True)
        
        for server, info in zip(info_tasks.keys(), results):
            if info and not isinstance(info, Exception):
                server_online = True
                server_name = server
                latency_ms = round((time.time() - start_times[server]) * 1000, 1)
                break
    
    # Get streams in parallel if server is online
    if server_online:
        stream_tasks = {}
        if bot.jellyfin and server_name == "Jellyfin":
            stream_tasks["Jellyfin"] = bot.jellyfin.get_active_streams()
        elif bot.emby and server_name == "Emby":
            stream_tasks["Emby"] = bot.emby.get_active_streams()
        
        if stream_tasks:
            stream_results = await asyncio.gather(*stream_tasks.values(), return_exceptions=True)
            for streams in stream_results:
                if streams and not isinstance(streams, Exception):
                    streams_data["total"] = len(streams)
                    for s in streams:
                        if s.get("TranscodingInfo"):
                            streams_data["transcoding"] += 1
                        else:
                            streams_data["direct"] += 1
    
    # Calculate membership duration
    member_duration = ""
    if db_user:
        created_at = db_user.get("created_at")
        if created_at:
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
    
    tier = "Member"
    
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
    embed.set_thumbnail(url="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/urbackup-server.png")  # Default server icon
    
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
    discord_username = ctx.author.name
    
    # Get users in parallel
    users = await get_linked_users(bot, discord_id, discord_username)
    
    if not users:
        embed.description = "❌ No linked accounts found."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Enable library access in parallel
    enable_tasks = {}
    for server, user in users.items():
        library_name = library_info.get(server.lower())
        if library_name:
            if server == "Jellyfin" and bot.jellyfin:
                enable_tasks[server] = bot.jellyfin.set_library_access_by_name(
                    user.get("jellyfin_id"), library_name, True
                )
            elif server == "Emby" and bot.emby:
                enable_tasks[server] = bot.emby.set_library_access_by_name(
                    user.get("emby_id"), library_name, True
                )
    
    results = []
    if enable_tasks:
        task_results = await asyncio.gather(*enable_tasks.values(), return_exceptions=True)
        for server, result in zip(enable_tasks.keys(), task_results):
            if isinstance(result, Exception):
                results.append(f"**{server}:** ❌ Error")
            else:
                status = "✅ Enabled" if result else "❌ Failed (library not found)"
                results.append(f"**{server}:** {status}")
    
    embed.description = f"**{display_name}**\n\n" + "\n".join(results)
    embed.color = discord.Color.green()
    
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
    discord_username = ctx.author.name
    
    # Get users in parallel
    users = await get_linked_users(bot, discord_id, discord_username)
    
    if not users:
        embed.description = "❌ No linked accounts found."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Disable library access in parallel
    disable_tasks = {}
    for server, user in users.items():
        library_name = library_info.get(server.lower())
        if library_name:
            if server == "Jellyfin" and bot.jellyfin:
                disable_tasks[server] = bot.jellyfin.set_library_access_by_name(
                    user.get("jellyfin_id"), library_name, False
                )
            elif server == "Emby" and bot.emby:
                disable_tasks[server] = bot.emby.set_library_access_by_name(
                    user.get("emby_id"), library_name, False
                )
    
    results = []
    if disable_tasks:
        task_results = await asyncio.gather(*disable_tasks.values(), return_exceptions=True)
        for server, result in zip(disable_tasks.keys(), task_results):
            if isinstance(result, Exception):
                results.append(f"**{server}:** ❌ Error")
            else:
                status = "✅ Disabled" if result else "❌ Failed (library not found)"
                results.append(f"**{server}:** {status}")
    
    embed.description = f"**{display_name}**\n\n" + "\n".join(results)
    embed.color = discord.Color.orange()
    
    await ctx.send(embed=embed)


@bot.command(name="link")
async def link_account(ctx: commands.Context, server_type: str = None, *, username: str = None):
    """Link your Discord account to your media server account
    
    Usage: 
        !link jellyfin <username>
        !link emby <username>
    """
    if not server_type or not username:
        embed = create_embed("🔗 Link Account", "")
        embed.description = """**Usage:** `!link <server> <username>`

**Examples:**
• `!link jellyfin MyUsername`
• `!link emby MyUsername`

**Available servers:** `jellyfin`, `emby`

**Note:** If your Discord username matches your server username, linking is automatic!"""
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
                
                # Add link indicator to nickname
                await update_member_link_indicator(ctx.author, "jellyfin")
                
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
                
                # Add link indicator to nickname
                await update_member_link_indicator(ctx.author, "emby")
                
                embed.description = f"✅ Successfully linked to Emby account: **{emby_username}**"
                embed.color = discord.Color.green()
            else:
                embed.description = f"❌ User **{username}** not found on Emby.\n\nMake sure you're using your exact Emby username."
                embed.color = discord.Color.red()
        except Exception as e:
            print(f"Emby link error: {e}")
            embed.description = f"❌ Error connecting to Emby: `{str(e)[:100]}`"
            embed.color = discord.Color.red()
    
    else:
        embed.description = f"❌ Unknown server type: **{server_type}**\n\nAvailable: `jellyfin`, `emby`"
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

**Available servers:** `jellyfin`, `emby`"""
        embed.color = discord.Color.blue()
        await ctx.send(embed=embed)
        return
    
    server_type = server_type.lower()
    discord_id = ctx.author.id
    
    if server_type not in ["jellyfin", "emby"]:
        embed = create_embed("🔓 Unlink Account", "")
        embed.description = f"❌ Unknown server type: **{server_type}**\n\nAvailable: `jellyfin`, `emby`"
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    success = db.unlink_account(discord_id, server_type)
    
    embed = create_embed("🔓 Unlink Account", "")
    if success:
        db.log_action(discord_id, f"unlink_{server_type}", f"Unlinked from {server_type}")
        
        # Update link indicator (will show remaining links or unlinked indicator)
        await update_member_link_indicator(ctx.author, server_type)
        
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
**!link [server] [username]** - Link your Discord to a media server
**!unlink [server]** - Unlink your Discord from a media server
**!watchtime** - Check your watchtime (last 30 days)
**!totaltime** - Check your total all-time watchtime
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
    
    await ctx.send(embed=embed)


# ============== ADMIN COMMANDS ==============

# Get admin user IDs from environment variable (comma-separated)
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]


def is_admin():
    """Check if user is an admin"""
    async def predicate(ctx: commands.Context):
        return ctx.author.id in ADMIN_IDS or ctx.author.guild_permissions.administrator
    return commands.check(predicate)


@bot.command(name="syncusers")
@is_admin()
async def sync_users(ctx: commands.Context):
    """[ADMIN] Sync all existing users from media servers to database
    
    This imports all Jellyfin/Emby users into the bot's database.
    Users are automatically synced on bot startup, but this command
    can be used to manually trigger a sync.
    """
    embed = create_embed("🔄 Syncing Users", "Importing users from media servers...")
    message = await ctx.send(embed=embed)
    
    synced_count = 0
    skipped_count = 0
    
    # Sync Jellyfin users
    if bot.jellyfin:
        try:
            jf_users = await bot.jellyfin.get_all_users()
            for user in jf_users:
                user_id = user.get("Id")
                username = user.get("Name")
                is_admin = user.get("Policy", {}).get("IsAdministrator", False)
                
                if is_admin:
                    continue
                
                existing = db.get_user_by_server_id(user_id, "jellyfin")
                if not existing:
                    db_user_id = db.create_server_user(username, user_id, "jellyfin")
                    if db_user_id:
                        synced_count += 1
                else:
                    skipped_count += 1
        except Exception as e:
            print(f"Error syncing Jellyfin users: {e}")
    
    # Sync Emby users
    if bot.emby:
        try:
            emby_users = await bot.emby.get_all_users()
            for user in emby_users:
                user_id = user.get("Id")
                username = user.get("Name")
                is_admin = user.get("Policy", {}).get("IsAdministrator", False)
                
                if is_admin:
                    continue
                
                existing = db.get_user_by_server_id(user_id, "emby")
                if not existing:
                    db_user_id = db.create_server_user(username, user_id, "emby")
                    if db_user_id:
                        synced_count += 1
                else:
                    skipped_count += 1
        except Exception as e:
            print(f"Error syncing Emby users: {e}")
    
    embed = create_embed("✅ User Sync Complete", "")
    embed.add_field(name="New Users Added", value=str(synced_count), inline=True)
    embed.add_field(name="Already Existed", value=str(skipped_count), inline=True)
    embed.color = discord.Color.green()
    
    await message.edit(embed=embed)


@bot.command(name="syncindicators")
@is_admin()
async def sync_indicators(ctx: commands.Context):
    """[ADMIN] Sync link indicators for all Discord members
    
    Updates nicknames with the appropriate link indicator emoji
    based on their linked Jellyfin/Emby accounts.
    Members not linked will get the unlinked indicator.
    """
    embed = create_embed("🔄 Syncing Link Indicators", "Updating member nicknames...")
    message = await ctx.send(embed=embed)
    
    updated_count = 0
    error_count = 0
    skipped_count = 0
    
    for member in ctx.guild.members:
        if member.bot:
            skipped_count += 1
            continue
        
        try:
            # Update indicator for ALL members (linked or not)
            result = await update_member_link_indicator(member)
            if result:
                updated_count += 1
            else:
                skipped_count += 1
        except Exception as e:
            error_count += 1
            print(f"Error updating indicator for {member.name}: {e}")
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.1)
    
    embed = create_embed("✅ Link Indicators Synced", "")
    embed.add_field(name="Updated", value=str(updated_count), inline=True)
    embed.add_field(name="Skipped", value=str(skipped_count), inline=True)
    embed.add_field(name="Errors", value=str(error_count), inline=True)
    embed.color = discord.Color.green()
    
    await message.edit(embed=embed)


@bot.command(name="syncwatch")
@is_admin()
async def sync_watchtime(ctx: commands.Context, member: discord.Member = None):
    """[ADMIN] Sync/import historical watchtime from media servers
    
    Usage: 
        !syncwatch @user - Sync specific user
        !syncwatch - Sync all linked users
    """
    embed = create_embed("🔄 Syncing Watchtime", "This may take a while...")
    message = await ctx.send(embed=embed)
    
    synced_users = []
    failed_users = []
    total_hours = 0
    
    if member:
        # Sync single user
        users_to_sync = [(member.id, str(member))]
    else:
        # Sync all linked users
        all_users = db.get_all_linked_users()
        users_to_sync = [(u.get("discord_id"), u.get("discord_username")) for u in all_users]
    
    # Update progress
    total_users = len(users_to_sync)
    
    for idx, (discord_id, discord_username) in enumerate(users_to_sync):
        # Update progress every 5 users
        if idx % 5 == 0 and total_users > 5:
            embed.description = f"Syncing... {idx}/{total_users} users"
            await message.edit(embed=embed)
        
        db_user = db.get_user_by_discord_id(discord_id)
        if not db_user:
            continue
        
        user_id = db_user.get("id")
        user_hours = 0
        
        try:
            # Sync from Jellyfin
            if bot.jellyfin and db_user.get("jellyfin_id"):
                jellyfin_id = db_user.get("jellyfin_id")
                stats = await bot.jellyfin.get_playback_stats(jellyfin_id)
                
                # Import by date
                for date_str, seconds in stats.get("by_date", {}).items():
                    db.add_watchtime(user_id, "jellyfin", seconds, date_str)
                
                user_hours += stats.get("total_seconds", 0) / 3600
            
            # Sync from Emby
            if bot.emby and db_user.get("emby_id"):
                emby_id = db_user.get("emby_id")
                stats = await bot.emby.get_playback_stats(emby_id)
                
                for date_str, seconds in stats.get("by_date", {}).items():
                    db.add_watchtime(user_id, "emby", seconds, date_str)
                
                user_hours += stats.get("total_seconds", 0) / 3600
            
            if user_hours > 0:
                synced_users.append(f"**{discord_username}**: {user_hours:.1f}h")
                total_hours += user_hours
                db.log_action(discord_id, "sync_watchtime", f"Synced {user_hours:.1f}h by {ctx.author}")
            
        except Exception as e:
            print(f"Sync error for {discord_username}: {e}")
            failed_users.append(f"**{discord_username}**: {str(e)[:50]}")
    
    # Update embed with results
    embed = create_embed("✅ Watchtime Sync Complete", "")
    
    if synced_users:
        embed.add_field(
            name=f"📊 Synced Users ({len(synced_users)})",
            value="\n".join(synced_users[:15]) + ("\n..." if len(synced_users) > 15 else ""),
            inline=False
        )
    
    if failed_users:
        embed.add_field(
            name=f"❌ Failed ({len(failed_users)})",
            value="\n".join(failed_users[:10]) + ("\n..." if len(failed_users) > 10 else ""),
            inline=False
        )
    
    embed.add_field(name="⏱️ Total Hours Synced", value=f"**{total_hours:.1f}** hours", inline=True)
    embed.add_field(name="👥 Users Synced", value=f"**{len(synced_users)}**", inline=True)
    
    # Show which sources were used
    sources = []
    if bot.jellyfin:
        sources.append("Jellyfin")
    if bot.emby:
        sources.append("Emby")
    
    if sources:
        embed.add_field(name="📡 Sources", value=", ".join(sources), inline=True)
    
    if not synced_users and not failed_users:
        embed.description = "No linked users found to sync."
        embed.color = discord.Color.orange()
    else:
        embed.color = discord.Color.green()
    
    await message.edit(embed=embed)


@bot.command(name="importwatch")
@is_admin()
async def import_watchtime(ctx: commands.Context, member: discord.Member, hours: float, server: str = "jellyfin"):
    """[ADMIN] Manually import watchtime for a user
    
    Usage: !importwatch @user <hours> [server]
    Example: !importwatch @JohnDoe 150.5 jellyfin
    """
    discord_id = member.id
    
    db_user = db.get_user_by_discord_id(discord_id)
    if not db_user:
        # Create user if not exists
        db.get_or_create_user(discord_id, str(member))
        db_user = db.get_user_by_discord_id(discord_id)
    
    user_id = db_user.get("id")
    seconds = int(hours * 3600)
    
    # Spread across multiple days to look natural
    from datetime import date, timedelta
    today = date.today()
    days_to_spread = min(30, int(hours / 2) + 1)  # Spread across ~2 hours per day
    seconds_per_day = seconds // days_to_spread
    
    try:
        for i in range(days_to_spread):
            day = today - timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            db.add_watchtime(user_id, server.lower(), seconds_per_day, date_str)
        
        db.log_action(discord_id, "import_watchtime", f"Imported {hours}h by {ctx.author}")
        
        embed = create_embed("✅ Watchtime Imported", "")
        embed.description = f"Successfully imported watchtime for **{member.display_name}**"
        embed.add_field(name="Hours", value=f"**{hours:.1f}h**", inline=True)
        embed.add_field(name="Server", value=server.title(), inline=True)
        embed.add_field(name="Spread Over", value=f"{days_to_spread} days", inline=True)
        embed.color = discord.Color.green()
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Import watchtime error: {e}")
        embed = create_embed("❌ Error", f"Failed to import watchtime: `{str(e)[:100]}`")
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)


@bot.command(name="listlibraries")
@is_admin()
async def list_libraries(ctx: commands.Context):
    """[ADMIN] List all libraries on media servers (for debugging !enable/!disable)
    
    Usage: !listlibraries
    """
    embed = create_embed("📚 Media Libraries", "Fetching libraries from servers...")
    message = await ctx.send(embed=embed)
    
    results = []
    
    if bot.jellyfin:
        try:
            libraries = await bot.jellyfin.get_libraries()
            if libraries:
                lib_list = []
                for lib in libraries:
                    name = lib.get("Name", "Unknown")
                    lib_id = lib.get("ItemId") or lib.get("Id")
                    lib_list.append(f"  `{name}` (ID: `{lib_id[:8]}...`)")
                results.append(f"**Jellyfin** ({len(libraries)} libraries):\n" + "\n".join(lib_list))
            else:
                results.append("**Jellyfin**: No libraries found")
        except Exception as e:
            results.append(f"**Jellyfin**: Error - {e}")
    
    if bot.emby:
        try:
            libraries = await bot.emby.get_libraries()
            if libraries:
                lib_list = []
                for lib in libraries:
                    name = lib.get("Name", "Unknown")
                    lib_id = lib.get("Id") or lib.get("ItemId") or lib.get("Guid") or "N/A"
                    lib_list.append(f"  `{name}` (ID: `{str(lib_id)[:8]}...`)")
                results.append(f"**Emby** ({len(libraries)} libraries):\n" + "\n".join(lib_list))
            else:
                results.append("**Emby**: No libraries found")
        except Exception as e:
            results.append(f"**Emby**: Error - {e}")
    
    if results:
        embed = create_embed("📚 Media Libraries", "\n\n".join(results))
        embed.color = discord.Color.blue()
        embed.set_footer(text="Use these exact library names in LIBRARY_MAPPING")
    else:
        embed = create_embed("📚 Media Libraries", "No media servers configured.")
        embed.color = discord.Color.orange()
    
    await message.edit(embed=embed)


# ============== SLASH COMMANDS ==============

@bot.tree.command(name="info", description="Show your account info")
async def info(interaction: discord.Interaction):
    """Show your account info"""
    discord_id = interaction.user.id
    discord_username = interaction.user.name
    
    embed = create_embed("👤 Account Information", "")
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    
    embed.add_field(name="Discord Username", value=discord_username, inline=True)
    embed.add_field(name="Discord ID", value=str(discord_id), inline=True)
    
    # Check linked accounts in parallel
    users = await get_linked_users(bot, discord_id, discord_username)
    
    linked = []
    for server in ["Jellyfin", "Emby"]:
        if server == "Jellyfin" and bot.jellyfin:
            if server in users:
                user = users[server]
                status = "🔗" if user.get("auto_matched") else "✅"
                linked.append(f"{status} Jellyfin: {user.get('username', 'Linked')}")
            else:
                linked.append("❌ Jellyfin: Not linked")
        elif server == "Emby" and bot.emby:
            if server in users:
                user = users[server]
                status = "🔗" if user.get("auto_matched") else "✅"
                linked.append(f"{status} Emby: {user.get('username', 'Linked')}")
            else:
                linked.append("❌ Emby: Not linked")
    
    if linked:
        embed.add_field(name="Linked Accounts", value="\n".join(linked), inline=False)
    
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
    
    bot.run(DISCORD_TOKEN)
