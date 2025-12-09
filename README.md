# Media Server Discord Bot

A Discord bot for managing Jellyfin, Emby, and Plex media servers. Track watchtime, manage devices, handle subscriptions, and more.

## Features

- **Multi-Server Support**: Works with Jellyfin, Emby, and Plex simultaneously
- **Account Linking**: Link Discord accounts to media server accounts
- **Watchtime Tracking**: Monitor user activity with detailed daily breakdown
- **Purge Protection**: Subscribers are immune to purge forever
- **Device Management**: View and reset connected devices
- **Password Reset**: Securely reset passwords via DM
- **Library Access Control**: Enable/disable content libraries (4K, Anime, etc.)
- **Subscription Management**: Handle user subscriptions with admin commands
- **Server Status**: Real-time server health, latency, and stream info
- **Audit Logging**: Track all important actions

## Commands

### User Commands (!)

| Command | Description |
|---------|-------------|
| `!link <server> <username>` | Link your Discord to a media server account |
| `!unlink <server>` | Unlink your Discord from a media server |
| `!watchtime` | Check your watchtime with detailed daily breakdown |
| `!totaltime` | Check total watchtime since joining |
| `!devices` | List connected devices |
| `!reset_devices` | Clear all connected devices (Jellyfin/Emby) |
| `!reset_password` | Reset password and receive new credentials via DM |
| `!stream` | Show currently active streams |
| `!status` | Display server health, latency, and stream stats |
| `!enable <feature>` | Enable a content library |
| `!disable <feature>` | Disable a content library |
| `!time` | Show server time |
| `!help` | List all commands |

### Slash Commands (/)

| Command | Description |
|---------|-------------|
| `/subscribe` | Get your personalized subscription link |
| `/unsubscribe` | Cancel an active subscription |
| `/info` | Show your account information |

### Admin Commands (!)

These commands require admin permissions or being listed in `ADMIN_IDS`.

| Command | Description |
|---------|-------------|
| `!addsub @user [plan] [amount]` | Add a subscriber manually |
| `!removesub @user` | Remove a subscriber |
| `!listsubs` | List all subscribers |
| `!checksub @user` | Check if a user is a subscriber |

### Account Linking Examples

```
!link jellyfin MyUsername
!link emby MyUsername
!link plex myemail@example.com

!unlink jellyfin
!unlink emby
!unlink plex
```

### Admin Command Examples

```
!addsub @JohnDoe kofi 5.00
!addsub @JaneSmith patreon 10.00
!removesub @JohnDoe
!listsubs
!checksub @JohnDoe
```

### Available Libraries

| Command | Jellyfin | Emby | Plex |
|---------|----------|------|------|
| `4kmovies` | 4K Movies | 4K Movies | 4K Movies |
| `movies` | Movies | Movies | Movies |
| `shows` | Shows | TV Shows | TV Shows |
| `animemovies` | Anime Movies | Anime Movies | Anime Movies |
| `animeshows` | Anime Shows | Anime TV Shows | Anime TV Shows |

## Purge System

Users must watch a minimum amount to avoid being purged:

| Setting | Default |
|---------|---------|
| **Threshold** | 7 hours |
| **Period** | 15 days |
| **Subscribers** | Immune forever |

Once a user subscribes (even once), they are **permanently immune** to purge.

## Quick Start

Once the bot is running, users can link their accounts:

```
!link jellyfin YourUsername
```

After linking, all commands will work with your media server account.

## Installation

### Prerequisites

- Python 3.10 or higher
- Discord Bot Token ([Create one here](https://discord.com/developers/applications))
- Media server API keys (Jellyfin/Emby/Plex)

### Local Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/media-server-bot.git
   cd media-server-bot
   ```

2. **Create virtual environment (recommended)**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp env.example .env
   ```
   
   Edit `.env` with your credentials.

5. **Run the bot**
   ```bash
   python bot.py
   ```

---

## 🚀 Railway Deployment

### Step 1: Prepare Your Repository

Make sure your GitHub repo contains these files:
```
├── bot.py
├── database.py
├── requirements.txt
├── Procfile
├── railway.toml
└── .gitignore
```

### Step 2: Deploy on Railway

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your bot repository
4. Railway will auto-detect Python and start building

### Step 3: Add PostgreSQL Database

1. In your Railway project, click **"+ New"** → **"Database"** → **"PostgreSQL"**
2. Railway automatically sets `DATABASE_URL` - no configuration needed!
3. The bot will detect PostgreSQL and use it instead of SQLite

### Step 4: Set Environment Variables

1. Click on your bot service
2. Go to **"Variables"** tab
3. Add these variables:

| Variable | Value | Required |
|----------|-------|----------|
| `DISCORD_TOKEN` | Your Discord bot token | ✅ Yes |
| `ADMIN_IDS` | Your Discord ID (comma-separated for multiple) | ✅ Yes |
| `SUBSCRIBE_URL` | Your payment link (Ko-fi, Patreon, PayPal, etc.) | Optional |
| `JELLYFIN_URL` | Your Jellyfin server URL | Optional |
| `JELLYFIN_API_KEY` | Your Jellyfin API key | Optional |
| `EMBY_URL` | Your Emby server URL | Optional |
| `EMBY_API_KEY` | Your Emby API key | Optional |
| `PLEX_URL` | Your Plex server URL | Optional |
| `PLEX_TOKEN` | Your Plex token | Optional |
| `PURGE_THRESHOLD_HOURS` | Hours required (default: 7) | Optional |
| `PURGE_PERIOD_DAYS` | Days to check (default: 15) | Optional |

> ⚠️ **Note**: `DATABASE_URL` is automatically provided by Railway when you add PostgreSQL!

### Step 5: Deploy

Railway will automatically redeploy when you push to GitHub or change variables.

### Checking Logs

- Click on your service → **"Logs"** tab to view bot output
- Look for "Database initialized successfully! (Using PostgreSQL)"

---

## Database

The bot automatically detects and uses:
- **PostgreSQL** when `DATABASE_URL` is set (Railway)
- **SQLite** when running locally (falls back to `bot_database.db`)

### Database Schema

- **users** - Discord to media server account links (Jellyfin, Emby, Plex)
- **watchtime** - Daily watchtime tracking per user
- **subscriptions** - User subscription records (for purge immunity)
- **library_access** - Per-user library permissions
- **invite_codes** - Invitation system
- **audit_log** - Action tracking (links, unlinks, password resets, etc.)

### Important Notes

⚠️ **Never commit to git:**
- `.env` (your secrets)
- `*.db` (local database files)

The `.gitignore` file handles this automatically.

---

## Getting API Keys

### Jellyfin
1. Go to Dashboard → API Keys
2. Click "+" to create a new key
3. Copy the API key to your `.env`

### Emby
1. Go to Settings → API Keys
2. Create a new key
3. Copy to your `.env`

### Plex
1. Visit https://plex.tv/claim
2. Or find your token in Plex app: Settings → Network → "View XML" → copy `X-Plex-Token`

### Discord Bot
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" → "Reset Token" → Copy token
4. Enable required intents:
   - ✅ Message Content Intent
   - ✅ Server Members Intent

### Getting Your Discord ID
1. Open Discord Settings → Advanced → Enable **Developer Mode**
2. Right-click your username → **Copy ID**
3. Add this ID to `ADMIN_IDS` in Railway variables

---

## Project Structure

```
media-server-bot/
├── bot.py              # Main bot file
├── database.py         # Database module (SQLite + PostgreSQL)
├── requirements.txt    # Python dependencies
├── Procfile            # Railway/Heroku process file
├── railway.toml        # Railway configuration
├── env.example         # Environment template
├── .gitignore          # Git ignore rules
└── README.md           # This file
```

## Screenshots

### Watchtime Command
```
Username's Jellyfin Watchtime

Day        | Date    | TV        | Movie     | Total
-------------------------------------------------------
Monday     | 01 Dec  | 1h2m31s   | 0s        | 1h2m31s
Tuesday    | 02 Dec  | 3h12m58s  | 0s        | 3h12m58s
...
-------------------------------------------------------
Total      |         | 4h15m29s  | 0s        | 4h15m29s

📅 Week Period    📅 Days Left    🔵 Status
01 Dec - 15 Dec   9 Days          ✅ Safe

⏱️ Purge Limit    ⏳ Remaining    🏆 Tier
7h                0 hrs           Member
```

### Status Command
```
Username's Plex Server

*User has joined our Discord 3 months ago and is an Elite member.*

Server Info:
🖥️ Local      🌐 Internet    ⚡ Latency
🟢 Online     🟢 Online      = 28.5 ms

📺 Streams    🔄 Transcoding  ▶️ Direct Play
[1] streams   [1V/0A]         [0] streams
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- Create an issue for bug reports
- Discussions for feature requests
- Pull requests welcome!
