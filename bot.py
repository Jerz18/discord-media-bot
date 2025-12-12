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

# Tautulli configuration (for detailed Plex stats)
TAUTULLI_URL = os.getenv("TAUTULLI_URL")
TAUTULLI_API_KEY = os.getenv("TAUTULLI_API_KEY")


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
    libraries = []
    
    try:
        async with self.session.get(
            f"{self.url}/Library/VirtualFolders",
            headers=self. headers
        ) as resp:
            if resp.status == 200:
                libraries = await resp.json()
                print(f"Jellyfin get_libraries:  Found {len(libraries)} libraries")
                for lib in libraries: 
                    lib_id = lib.get("ItemId") or lib.get("Id") or lib.get("Guid")
                    print(f"  - {lib.get('Name')}: {lib_id}")
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
        lib_id = lib. get("ItemId") or lib.get("Id") or lib.get("Guid")
        if lib_name.lower() == library_name.lower():
            print(f"Jellyfin:  Found '{lib_name}' with ID: {lib_id}")
            return lib_id
    
    print(f"Jellyfin: Library '{library_name}' not found")
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
                        enabled_folders.append(lib_id)
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
        """Get all media libraries"""
        libraries = []
        
        # Use Library/VirtualFolders - this returns the actual library configuration
        try:
            async with self.session.get(
                f"{self.url}/Library/VirtualFolders",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    libraries = await resp.json()
                    print(f"Emby get_libraries (VirtualFolders): Found {len(libraries)} libraries")
                    for lib in libraries:
                        print(f"  - {lib.get('Name')}: {lib.get('ItemId')}")
                    if libraries:
                        return libraries
        except Exception as e:
            print(f"Emby get_libraries (VirtualFolders) error: {e}")
        
        # Fallback: Try MediaFolders endpoint
        try:
            async with self.session.get(
                f"{self.url}/Library/MediaFolders",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    libraries = data.get("Items", [])
                    print(f"Emby get_libraries (MediaFolders): Found {len(libraries)} libraries")
                    for lib in libraries:
                        print(f"  - {lib.get('Name')}: {lib.get('Id')}")
                    if libraries:
                        return libraries
        except Exception as e:
            print(f"Emby get_libraries (MediaFolders) error: {e}")
        
        return []
    
    async def get_library_id_by_name(self, library_name: str) -> Optional[str]:
        """Find library ID by name"""
        libraries = await self.get_libraries()
        print(f"Emby: Looking for library '{library_name}' in {len(libraries)} libraries")
        for lib in libraries:
            lib_name = lib.get("Name", "")
            # VirtualFolders uses "ItemId", MediaFolders uses "Id"
            lib_id = lib.get("ItemId") or lib.get("Id") or lib.get("Guid")
            print(f"Emby:   Checking '{lib_name}' (ID: {lib_id})")
            if lib_name.lower() == library_name.lower():
                print(f"Emby: Found match! Library ID: {lib_id}")
                return lib_id
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
        try:
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
                        runtime_seconds = runtime_ticks // 10000000 if runtime_ticks else 0
                        last_played = user_data.get("LastPlayedDate")
                        
                        if last_played and runtime_seconds > 0:
                            history.append({
                                "title": item.get("Name", "Unknown"),
                                "type": item.get("Type", "Unknown"),
                                "series": item.get("SeriesName", ""),
                                "runtime_seconds": runtime_seconds,
                                "played_date": last_played[:10] if last_played else None,
                                "play_count": user_data.get("PlayCount", 1)
                            })
        except Exception as e:
            print(f"Emby get_watch_history error: {e}")
        
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
    
    async def get_watch_history(self, user_id: str = None, limit: int = 10000) -> list:
        """Get watch history from Plex
        
        Note: Plex watch history requires either:
        1. Tautulli integration (recommended)
        2. Plex Pass for detailed history
        """
        history = []
        try:
            # Get history from Plex
            # Note: This endpoint may require Plex Pass
            async with self.session.get(
                f"{self.url}/status/sessions/history/all",
                headers=self.headers,
                params={"sort": "viewedAt:desc", "limit": limit}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("MediaContainer", {}).get("Metadata", [])
                    
                    for item in items:
                        duration = item.get("duration", 0)  # milliseconds
                        runtime_seconds = duration // 1000 if duration else 0
                        viewed_at = item.get("viewedAt")
                        
                        if viewed_at:
                            from datetime import datetime
                            played_date = datetime.fromtimestamp(viewed_at).strftime("%Y-%m-%d")
                        else:
                            played_date = None
                        
                        if runtime_seconds > 0:
                            history.append({
                                "title": item.get("title", "Unknown"),
                                "type": item.get("type", "unknown").title(),
                                "series": item.get("grandparentTitle", ""),
                                "runtime_seconds": runtime_seconds,
                                "played_date": played_date,
                                "play_count": 1
                            })
        except Exception as e:
            print(f"Plex get_watch_history error: {e}")
        
        # Fallback: Get played items from library
        if not history:
            try:
                libraries = await self.get_libraries()
                for lib in libraries:
                    lib_key = lib.get("key")
                    async with self.session.get(
                        f"{self.url}/library/sections/{lib_key}/all",
                        headers=self.headers,
                        params={"unwatched": 0}  # Get watched items only
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            items = data.get("MediaContainer", {}).get("Metadata", [])
                            
                            for item in items:
                                if item.get("viewCount", 0) > 0:
                                    duration = item.get("duration", 0)
                                    runtime_seconds = duration // 1000 if duration else 0
                                    last_viewed = item.get("lastViewedAt")
                                    
                                    if last_viewed:
                                        from datetime import datetime
                                        played_date = datetime.fromtimestamp(last_viewed).strftime("%Y-%m-%d")
                                    else:
                                        played_date = None
                                    
                                    if runtime_seconds > 0:
                                        history.append({
                                            "title": item.get("title", "Unknown"),
                                            "type": item.get("type", "unknown").title(),
                                            "series": item.get("grandparentTitle", ""),
                                            "runtime_seconds": runtime_seconds,
                                            "played_date": played_date,
                                            "play_count": item.get("viewCount", 1)
                                        })
            except Exception as e:
                print(f"Plex get_watch_history fallback error: {e}")
        
        return history
    
    async def get_playback_stats(self, user_id: str = None) -> dict:
        """Get aggregated playback statistics from Plex"""
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
            item_type = item.get("type", "").lower()
            
            stats["total_seconds"] += runtime * play_count
            stats["total_plays"] += play_count
            
            if item_type == "movie":
                stats["movies"] += play_count
            elif item_type == "episode":
                stats["episodes"] += play_count
            
            if played_date:
                if played_date not in stats["by_date"]:
                    stats["by_date"][played_date] = 0
                stats["by_date"][played_date] += runtime
        
        return stats


class TautulliAPI:
    """Tautulli API wrapper for detailed Plex statistics"""
    
    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str):
        self.session = session
        self.url = url.rstrip('/')
        self.api_key = api_key
    
    async def _api_call(self, cmd: str, **params) -> Optional[dict]:
        """Make an API call to Tautulli"""
        try:
            params["apikey"] = self.api_key
            params["cmd"] = cmd
            
            async with self.session.get(
                f"{self.url}/api/v2",
                params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("response", {}).get("result") == "success":
                        return data.get("response", {}).get("data")
        except Exception as e:
            print(f"Tautulli API error ({cmd}): {e}")
        return None
    
    async def get_user_watch_time_stats(self, user_id: str = None, username: str = None) -> Optional[dict]:
        """Get watch time statistics for a user"""
        params = {}
        if user_id:
            params["user_id"] = user_id
        
        return await self._api_call("get_user_watch_time_stats", **params)
    
    async def get_history(self, user: str = None, user_id: str = None, 
                         length: int = 10000, start: int = 0) -> list:
        """Get watch history, optionally filtered by user"""
        params = {"length": length, "start": start}
        
        if user:
            params["user"] = user
        if user_id:
            params["user_id"] = user_id
        
        data = await self._api_call("get_history", **params)
        if data:
            return data.get("data", [])
        return []
    
    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Find a Tautulli user by Plex username"""
        data = await self._api_call("get_users")
        if data:
            for user in data:
                if user.get("username", "").lower() == username.lower():
                    return user
                if user.get("friendly_name", "").lower() == username.lower():
                    return user
        return None
    
    async def get_user_by_email(self, email: str) -> Optional[dict]:
        """Find a Tautulli user by email"""
        data = await self._api_call("get_users")
        if data:
            for user in data:
                if user.get("email", "").lower() == email.lower():
                    return user
        return None
    
    async def get_users(self) -> list:
        """Get all Tautulli users"""
        data = await self._api_call("get_users")
        return data if data else []
    
    async def get_playback_stats(self, username: str = None, user_id: str = None) -> dict:
        """Get detailed playback statistics for a user"""
        stats = {
            "total_seconds": 0,
            "total_plays": 0,
            "movies": 0,
            "episodes": 0,
            "by_date": {}
        }
        
        # Get user's Tautulli ID if we have a username
        tautulli_user_id = user_id
        if username and not tautulli_user_id:
            user = await self.get_user_by_username(username)
            if user:
                tautulli_user_id = user.get("user_id")
        
        if not tautulli_user_id:
            return stats
        
        # Get watch history
        history = await self.get_history(user_id=tautulli_user_id, length=10000)
        
        for item in history:
            # Duration watched in seconds
            duration = item.get("duration", 0)
            if not duration:
                # Use full duration if watch duration not available
                duration = item.get("full_duration", 0)
            
            stats["total_seconds"] += duration
            stats["total_plays"] += 1
            
            media_type = item.get("media_type", "")
            if media_type == "movie":
                stats["movies"] += 1
            elif media_type == "episode":
                stats["episodes"] += 1
            
            # Get date
            date_timestamp = item.get("date")
            if date_timestamp:
                played_date = datetime.fromtimestamp(date_timestamp).strftime("%Y-%m-%d")
                if played_date not in stats["by_date"]:
                    stats["by_date"][played_date] = 0
                stats["by_date"][played_date] += duration
        
        return stats
    
    async def get_user_stats_summary(self, username: str = None) -> dict:
        """Get a summary of user stats from Tautulli"""
        user = await self.get_user_by_username(username) if username else None
        
        if user:
            user_id = user.get("user_id")
            watch_stats = await self.get_user_watch_time_stats(user_id=user_id)
            
            if watch_stats:
                # Tautulli returns stats in different time periods
                total_time = 0
                total_plays = 0
                
                for period in watch_stats:
                    if period.get("query_days") == 0:  # All time
                        total_time = period.get("total_time", 0)  # in seconds
                        total_plays = period.get("total_plays", 0)
                        break
                
                return {
                    "total_seconds": total_time,
                    "total_plays": total_plays,
                    "username": user.get("username"),
                    "friendly_name": user.get("friendly_name"),
                    "user_id": user_id
                }
        
        return {"total_seconds": 0, "total_plays": 0}


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
        self.tautulli: Optional[TautulliAPI] = None
    
    async def setup_hook(self):
        """Initialize API clients and sync commands"""
        self.session = aiohttp.ClientSession()
        
        if JELLYFIN_URL and JELLYFIN_API_KEY:
            self.jellyfin = JellyfinAPI(self.session, JELLYFIN_URL, JELLYFIN_API_KEY)
        
        if EMBY_URL and EMBY_API_KEY:
            self.emby = EmbyAPI(self.session, EMBY_URL, EMBY_API_KEY)
        
        if PLEX_URL and PLEX_TOKEN:
            self.plex = PlexAPI(self.session, PLEX_URL, PLEX_TOKEN)
        
        if TAUTULLI_URL and TAUTULLI_API_KEY:
            self.tautulli = TautulliAPI(self.session, TAUTULLI_URL, TAUTULLI_API_KEY)
        
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
        print(f"Plex configured: {self.plex is not None}")
        print(f"Tautulli configured: {self.tautulli is not None}")
        
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
        "display": "Shows",
        "jellyfin": "Shows",
        "emby": "Shows",
        "plex": "Shows"
    },
    "animemovies": {
        "display": "Anime Movies",
        "jellyfin": "Anime Movies",
        "emby": "Anime Movies",
        "plex": "Anime Movies"
    },
    "animeshows": {
        "display": "Anime Shows",
        "jellyfin": "Anime Shows",
        "emby": "Anime Shows",
        "plex": "Anime Shows"
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
    """Check your watchtime statistics"""
    discord_id = ctx.author.id
    
    # Get user from database
    db_user = db.get_user_by_discord_id(discord_id)
    
    if not db_user:
        embed = create_embed("⏱️ Watchtime", "")
        embed.description = "❌ No linked accounts found. Use `!link` to link your account first."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Check if user is a subscriber
    is_subscriber = db.has_ever_subscribed(db_user.get("id"))
    
    # Determine tier
    if is_subscriber:
        tier = "Subscriber"
        tier_emoji = "💎"
        status_color = discord.Color.gold()
        status_message = "Your presence is a whisper in the dark. Even the shadows bow to you. 🥷"
    else:
        tier = "Member"
        tier_emoji = "🏆"
        status_color = discord.Color.blue()
        status_message = "Keep watching and enjoying! 🎬"
    
    # Get daily watchtime (last 30 days)
    daily_watchtime = db.get_daily_watchtime(db_user.get("id"), 30)
    
    # Calculate totals
    total_tv_seconds = sum(d.get("tv", 0) for d in daily_watchtime.values())
    total_movie_seconds = sum(d.get("movie", 0) for d in daily_watchtime.values())
    total_seconds = total_tv_seconds + total_movie_seconds
    total_hours = total_seconds / 3600
    
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
    
    # Get last 7 days
    from datetime import date
    today = date.today()
    
    for i in range(7):  # Show last 7 days
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
    period_start = today - timedelta(days=29)
    period_str = f"{period_start.strftime('%d %b')} - {today.strftime('%d %b')}"
    
    # Add stats fields
    embed.add_field(name="📅 Period", value=period_str, inline=True)
    embed.add_field(name="⏱️ This Month", value=f"{total_hours:.1f}h", inline=True)
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
    discord_id = ctx.author.id
    
    # Get user from database
    db_user = db.get_user_by_discord_id(discord_id)
    
    if not db_user:
        embed = create_embed("📊 Total Watchtime", "")
        embed.description = "❌ No linked accounts found. Use `!link` to link your account first."
        embed.color = discord.Color.red()
        await ctx.send(embed=embed)
        return
    
    # Get username
    username = ctx.author.display_name
    server_name = "Media Server"
    
    # Determine primary server and get user info
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
    
    # Get all-time watchtime from database
    all_time_stats = db.get_all_time_watchtime(db_user.get("id"))
    
    # Calculate totals
    total_seconds = all_time_stats.get("total_seconds", 0)
    total_plays = all_time_stats.get("total_plays", 0)
    first_watch = all_time_stats.get("first_watch", None)
    last_watch = all_time_stats.get("last_watch", None)
    
    # Get monthly breakdown
    monthly_stats = db.get_monthly_watchtime(db_user.get("id"), months=6)
    
    # Check subscriber status
    is_subscriber = db.has_ever_subscribed(db_user.get("id"))
    tier = "Subscriber" if is_subscriber else "Member"
    tier_emoji = "💎" if is_subscriber else "🏆"
    
    # Calculate member duration
    created_at = db_user.get("created_at")
    member_days = 0
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
        
        member_days = (now - created_date).days
    
    # Build embed
    embed = discord.Embed(
        title=f"📊 {username}'s Total Watchtime",
        color=discord.Color.gold() if is_subscriber else discord.Color.blue()
    )
    
    # Format total time nicely
    total_hours = total_seconds // 3600
    total_days = total_hours // 24
    remaining_hours = total_hours % 24
    
    if total_days > 0:
        total_time_str = f"{total_days}d {remaining_hours}h"
    else:
        total_time_str = format_duration(total_seconds)
    
    # Main stats
    embed.add_field(
        name="⏱️ Total Watch Time",
        value=f"**{total_time_str}**\n({total_hours:,} hours)",
        inline=True
    )
    
    embed.add_field(
        name="▶️ Total Plays",
        value=f"**{total_plays:,}**",
        inline=True
    )
    
    embed.add_field(
        name=f"{tier_emoji} Tier",
        value=f"**{tier}**",
        inline=True
    )
    
    # Daily average
    if member_days > 0:
        avg_hours_per_day = total_hours / member_days
        embed.add_field(
            name="📈 Daily Average",
            value=f"**{avg_hours_per_day:.1f}h** / day",
            inline=True
        )
    
    embed.add_field(
        name="📅 Member For",
        value=f"**{member_days}** days",
        inline=True
    )
    
    embed.add_field(
        name="🖥️ Server",
        value=f"**{server_name}**",
        inline=True
    )
    
    # Monthly breakdown table
    if monthly_stats:
        table = "```\n"
        table += f"{'Month':<12}| {'Hours':<10}| {'Plays':<8}\n"
        table += "-" * 35 + "\n"
        
        for month in monthly_stats[:6]:
            month_name = month.get("month", "Unknown")
            hours = month.get("hours", 0)
            plays = month.get("plays", 0)
            table += f"{month_name:<12}| {hours:<10.1f}| {plays:<8}\n"
        
        table += "```"
        embed.add_field(name="📆 Monthly Breakdown", value=table, inline=False)
    
    # Activity dates
    date_info = ""
    if first_watch:
        if isinstance(first_watch, str):
            date_info += f"**First watched:** {first_watch[:10]}\n"
        else:
            date_info += f"**First watched:** {first_watch.strftime('%Y-%m-%d')}\n"
    if last_watch:
        if isinstance(last_watch, str):
            date_info += f"**Last watched:** {last_watch[:10]}"
        else:
            date_info += f"**Last watched:** {last_watch.strftime('%Y-%m-%d')}"
    
    if date_info:
        embed.add_field(name="📅 Activity", value=date_info, inline=False)
    
    # Fun stats
    movies_equivalent = total_hours // 2  # Assuming 2 hours per movie
    episodes_equivalent = total_hours * 60 // 45  # Assuming 45 min per episode
    
    fun_stats = f"🎬 ≈ **{movies_equivalent:,}** movies watched\n"
    fun_stats += f"📺 ≈ **{episodes_equivalent:,}** TV episodes watched"
    embed.add_field(name="🎯 Fun Stats", value=fun_stats, inline=False)
    
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    embed.timestamp = datetime.now(timezone.utc)
    
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
    """Shows details about current streaming tracks"""
    embed = discord.Embed(
        title="🎬 Active Streams",
        color=discord.Color.blue()
    )
    
    all_streams = []
    stream_count = 0
    transcode_count = 0
    direct_count = 0
    
    if bot.jellyfin:
        streams = await bot.jellyfin.get_active_streams()
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
            stream_info = f"**[Jellyfin] {user}**\n"
            stream_info += f"📺 {display_title}\n"
            stream_info += f"🎬 {stream_type} • {quality} • {play_method}\n"
            stream_info += f"⏱️ {progress}\n"
            stream_info += f"📱 {client} ({device})"
            if transcode_reason:
                stream_info += f"\n⚠️ Reason: {transcode_reason}"
            
            all_streams.append(stream_info)
    
    if bot.emby:
        streams = await bot.emby.get_active_streams()
        for s in streams:
            stream_count += 1
            item = s.get("NowPlayingItem", {})
            play_state = s.get("PlayState", {})
            transcode_info = s.get("TranscodingInfo")
            
            user = s.get("UserName", "Unknown")
            title = item.get("Name", "Unknown")
            series_name = item.get("SeriesName", "")
            stream_type = item.get("Type", "Unknown")
            
            if series_name:
                display_title = f"{series_name} - {title}"
            else:
                display_title = title
            
            # Get quality
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
            
            # Progress
            position_ticks = play_state.get("PositionTicks", 0)
            runtime_ticks = item.get("RunTimeTicks", 1)
            if runtime_ticks > 0:
                progress_pct = int((position_ticks / runtime_ticks) * 100)
                position_min = int(position_ticks / 600000000)
                runtime_min = int(runtime_ticks / 600000000)
                progress = f"{position_min}m / {runtime_min}m ({progress_pct}%)"
            else:
                progress = "Unknown"
            
            if transcode_info:
                transcode_count += 1
                play_method = "🔄 Transcode"
            else:
                direct_count += 1
                play_method = "▶️ Direct Play"
            
            client = s.get("Client", "Unknown")
            device = s.get("DeviceName", "Unknown")
            
            stream_info = f"**[Emby] {user}**\n"
            stream_info += f"📺 {display_title}\n"
            stream_info += f"🎬 {stream_type} • {quality} • {play_method}\n"
            stream_info += f"⏱️ {progress}\n"
            stream_info += f"📱 {client} ({device})"
            
            all_streams.append(stream_info)
    
    if bot.plex:
        streams = await bot.plex.get_active_streams()
        for s in streams:
            stream_count += 1
            
            user = s.get("User", {}).get("title", "Unknown")
            title = s.get("title", "Unknown")
            grandparent_title = s.get("grandparentTitle", "")  # Show name for episodes
            stream_type = s.get("type", "unknown").title()
            
            if grandparent_title:
                display_title = f"{grandparent_title} - {title}"
            else:
                display_title = title
            
            # Get quality from media info
            media = s.get("Media", [{}])[0] if s.get("Media") else {}
            video_resolution = media.get("videoResolution", "")
            if video_resolution == "4k":
                quality = "4K"
            elif video_resolution:
                quality = video_resolution.upper()
            else:
                quality = "Unknown"
            
            # Bitrate
            bitrate = media.get("bitrate", 0)
            if bitrate:
                bitrate_str = f"{bitrate // 1000} Mbps" if bitrate >= 1000 else f"{bitrate} Kbps"
            else:
                bitrate_str = ""
            
            # Progress
            view_offset = s.get("viewOffset", 0)  # in milliseconds
            duration = s.get("duration", 1)  # in milliseconds
            if duration > 0:
                progress_pct = int((view_offset / duration) * 100)
                position_min = int(view_offset / 60000)
                runtime_min = int(duration / 60000)
                progress = f"{position_min}m / {runtime_min}m ({progress_pct}%)"
            else:
                progress = "Unknown"
            
            # Transcode or Direct
            session = s.get("Session", {})
            transcode_session = s.get("TranscodeSession", {})
            
            if transcode_session:
                transcode_count += 1
                play_method = "🔄 Transcode"
                video_decision = transcode_session.get("videoDecision", "")
                audio_decision = transcode_session.get("audioDecision", "")
                transcode_detail = f"V:{video_decision} A:{audio_decision}"
            else:
                direct_count += 1
                play_method = "▶️ Direct Play"
                transcode_detail = None
            
            # Player info
            player = s.get("Player", {})
            client = player.get("product", "Unknown")
            device = player.get("device", "Unknown")
            platform = player.get("platform", "")
            
            stream_info = f"**[Plex] {user}**\n"
            stream_info += f"📺 {display_title}\n"
            stream_info += f"🎬 {stream_type} • {quality}"
            if bitrate_str:
                stream_info += f" • {bitrate_str}"
            stream_info += f" • {play_method}\n"
            stream_info += f"⏱️ {progress}\n"
            stream_info += f"📱 {client} ({device})"
            if platform:
                stream_info += f" - {platform}"
            if transcode_detail:
                stream_info += f"\n⚠️ {transcode_detail}"
            
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
                success = await bot.jellyfin.set_library_access_by_name(
                    user.get("jellyfin_id"), library_name, True
                )
                status = "✅ Enabled" if success else "❌ Failed (library not found)"
                results.append(f"**Jellyfin:** {status}")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            library_name = library_info.get("emby")
            if library_name:
                success = await bot.emby.set_library_access_by_name(
                    user.get("emby_id"), library_name, True
                )
                status = "✅ Enabled" if success else "❌ Failed (library not found)"
                results.append(f"**Emby:** {status}")
    
    if bot.plex:
        user = await bot.plex.get_user_by_discord_id(discord_id)
        if user:
            results.append(f"**Plex:** ⚠️ Library management not supported (use Plex settings)")
    
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
                success = await bot.jellyfin.set_library_access_by_name(
                    user.get("jellyfin_id"), library_name, False
                )
                status = "✅ Disabled" if success else "❌ Failed (library not found)"
                results.append(f"**Jellyfin:** {status}")
    
    if bot.emby:
        user = await bot.emby.get_user_by_discord_id(discord_id)
        if user:
            library_name = library_info.get("emby")
            if library_name:
                success = await bot.emby.set_library_access_by_name(
                    user.get("emby_id"), library_name, False
                )
                status = "✅ Disabled" if success else "❌ Failed (library not found)"
                results.append(f"**Emby:** {status}")
    
    if bot.plex:
        user = await bot.plex.get_user_by_discord_id(discord_id)
        if user:
            results.append(f"**Plex:** ⚠️ Library management not supported (use Plex settings)")
    
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
**!watchtime** - Check your watchtime statistics
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
        embed.add_field(name="Status", value="🛡️ Subscriber", inline=False)
        embed.color = discord.Color.green()
        
        await ctx.send(embed=embed)
        
        # Notify the user
        try:
            user_embed = create_embed("🎉 Subscription Activated!", "")
            user_embed.description = f"Your subscription has been activated by an admin!\n\nThank you for your support! 💎"
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
            embed.add_field(name="Status", value="👤 Regular Member", inline=False)
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
            
            # Sync from Plex via Tautulli (preferred) or Plex API
            if db_user.get("plex_username") or db_user.get("plex_email"):
                plex_username = db_user.get("plex_username")
                plex_email = db_user.get("plex_email")
                
                if bot.tautulli:
                    # Use Tautulli for detailed stats (preferred)
                    stats = await bot.tautulli.get_playback_stats(username=plex_username)
                    
                    if stats.get("total_seconds", 0) == 0 and plex_email:
                        # Try with email
                        tautulli_user = await bot.tautulli.get_user_by_email(plex_email)
                        if tautulli_user:
                            stats = await bot.tautulli.get_playback_stats(
                                user_id=tautulli_user.get("user_id")
                            )
                    
                    for date_str, seconds in stats.get("by_date", {}).items():
                        db.add_watchtime(user_id, "plex", seconds, date_str)
                    
                    user_hours += stats.get("total_seconds", 0) / 3600
                    
                elif bot.plex:
                    # Fallback to Plex API (less detailed)
                    stats = await bot.plex.get_playback_stats()
                    
                    for date_str, seconds in stats.get("by_date", {}).items():
                        db.add_watchtime(user_id, "plex", seconds, date_str)
                    
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
    if bot.tautulli:
        sources.append("Tautulli")
    elif bot.plex:
        sources.append("Plex")
    
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
    
    if bot.plex:
        try:
            libraries = await bot.plex.get_libraries()
            if libraries:
                lib_list = []
                for lib in libraries:
                    name = lib.get("title", "Unknown")
                    lib_id = lib.get("key", "N/A")
                    lib_list.append(f"  `{name}` (ID: `{lib_id}`)")
                results.append(f"**Plex** ({len(libraries)} libraries):\n" + "\n".join(lib_list))
            else:
                results.append("**Plex**: No libraries found")
        except Exception as e:
            results.append(f"**Plex**: Error - {e}")
    
    if results:
        embed = create_embed("📚 Media Libraries", "\n\n".join(results))
        embed.color = discord.Color.blue()
        embed.set_footer(text="Use these exact library names in LIBRARY_MAPPING")
    else:
        embed = create_embed("📚 Media Libraries", "No media servers configured.")
        embed.color = discord.Color.orange()
    
    await message.edit(embed=embed)


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
        value="• 💎 **Subscriber Status**\n• Access to 4K content\n• Priority streaming\n• Extended device limits",
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
        # Remove all subscription records so they lose subscriber status
        db.remove_all_subscriptions(user.get("id"))
        db.log_action(discord_id, "unsubscribe", "Cancelled and removed subscription")
        embed.description = "Your subscription has been cancelled."
        embed.add_field(
            name="Status",
            value="You are now a regular member.",
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
