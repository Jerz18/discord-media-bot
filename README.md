# Media Server Discord Bot

A Discord bot for managing Jellyfin, Emby, and Plex media servers. Track watchtime, manage devices, handle subscriptions, and more.

## Features

- **Multi-Server Support**: Works with Jellyfin, Emby, and Plex simultaneously
- **Account Linking**: Link Discord accounts to media server accounts
- **Watchtime Tracking**: Monitor user activity and identify inactive users
- **Device Management**: View and reset connected devices
- **Password Reset**: Securely reset passwords via DM
- **Library Access Control**: Enable/disable content libraries (4K, Anime, etc.)
- **Subscription Management**: Handle user subscriptions
- **Audit Logging**: Track all important actions

## Commands

### Prefix Commands (!)

| Command | Description |
|---------|-------------|
| `!link <server> <username>` | Link your Discord to a media server account |
| `!unlink <server>` | Unlink your Discord from a media server |
| `!watchtime` | Check your watchtime and purge safety status |
| `!totaltime` | Check total watchtime since joining |
| `!devices` | List connected devices |
| `!reset_devices` | Clear all connected devices (Jellyfin/Emby) |
| `!reset_password` | Reset password and receive new credentials via DM |
| `!stream` | Show currently active streams |
| `!status` | Display server health and status |
| `!enable <feature>` | Enable a content library |
| `!disable <feature>` | Disable a content library |
| `!time` | Show server time |
| `!help` | List all commands |

### Slash Commands (/)

| Command | Description |
|---------|-------------|
| `/subscribe` | Get personalized subscription link |
| `/unsubscribe` | Cancel active subscription |
| `/info` | Show account information |

### Account Linking Examples

```
!link jellyfin MyUsername
!link emby MyUsername
!link plex myemail@example.com

!unlink jellyfin
!unlink emby
!unlink plex
```

### Available Features

`4k`, `3d`, `anime`, `movies`, `tvshows`, `music`, `audiobooks`, `kids`

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

| Variable | Value |
|----------|-------|
| `DISCORD_TOKEN` | Your Discord bot token |
| `SUBSCRIBE_URL` | Your payment link (Ko-fi, Patreon, PayPal, etc.) |
| `JELLYFIN_URL` | Your Jellyfin server URL |
| `JELLYFIN_API_KEY` | Your Jellyfin API key |
| `EMBY_URL` | Your Emby server URL (optional) |
| `EMBY_API_KEY` | Your Emby API key (optional) |
| `PLEX_URL` | Your Plex server URL (optional) |
| `PLEX_TOKEN` | Your Plex token (optional) |
| `PURGE_THRESHOLD_HOURS` | Hours required (default: 168) |

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
- **subscriptions** - User subscription records
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
