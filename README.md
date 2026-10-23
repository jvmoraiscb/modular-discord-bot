# Modular Discord Bot

Modular Discord Bot built with an independent, service-oriented architecture. Each service has its own lifecycle, dedicated configuration files, and per-guild customization support.

---

## Project Structure

```text
discord-bot/
├── core/
│   ├── bot.py               # ModularBot class (lifecycle and slash command synchronization)
│   ├── service_base.py      # BaseService abstract class for modular services
│   ├── service_manager.py   # Automatic service discovery, loading, and hot reloading
│   └── guild_store.py       # Thread-safe persistent storage for per-guild settings
├── config/
│   ├── bot.json             # Root bot settings (prefix, status, auto_disconnect_timeout)
│   ├── tts.json             # Default configuration for the TTS service
│   └── yt.json              # Default configuration for the YouTube music service
├── data/
│   ├── guild_settings.json  # Dynamic per-guild settings
│   ├── bot.log              # Persistent bot logs
│   └── temp/                # Synthesized temporary audio files (auto-cleaned)
├── assets/
│   └── sounds/              # Intro audio sound effects for TTS
├── services/
│   ├── tts/                 # Text-to-Speech service module
│   │   ├── service.py       # Slash commands (/tts) and chat-to-speech listener
│   │   ├── tts_engine.py    # Edge-TTS synthesizer and audio mixing
│   │   └── voice_queue.py   # Async voice queue and voice connection manager
│   └── yt/                  # YouTube music streaming service
│       ├── service.py       # Slash commands (/yt play, /yt queue, /yt skip, etc.)
│       ├── music_queue.py   # Guild music player and playlist queue
│       └── ytdl_player.py   # yt-dlp audio extraction and FFmpeg source
├── .env.example             # Environment variables template
├── requirements.txt         # Project dependencies
└── main.py                  # Application entry point
```

---

## How the Architecture Works

1. **Dedicated Service Configuration (`config/<service>.json`)**:
   Each service has its own JSON file defining global defaults (default volume, voices, timeouts, limits).
2. **Dynamic Per-Guild Overrides (`data/guild_settings.json`)**:
   Individual servers can customize their preferences (voice, rate, intro sounds, volume) via slash commands. Overrides are loaded transparently.
3. **Auto Discovery & Pluggability**:
   Any new folder created inside `services/` containing a `service.py` subclassing `BaseService` is discovered and loaded automatically by `ServiceManager`.

---

## Running the Bot

### 1. Prerequisites
- Python 3.10+
- FFmpeg installed on the system (required by Discord for voice audio playback)

### 2. Activate Virtual Environment
```bash
source .venv/bin/activate
```

If setting up in a new environment:
```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Set your token:
```env
DISCORD_TOKEN=your_token_here
COMMAND_PREFIX=!
LOG_LEVEL=INFO
```

> **Note**: Enable **Privileged Gateway Intents** on the [Discord Developer Portal](https://discord.com/developers/applications):
> - [x] **Message Content Intent**
> - [x] **Server Members Intent**

### 4. Start the Bot
```bash
./.venv/bin/python main.py
```

---

## Core Bot Commands (/bot)

All core bot management, voice connection, and service administration commands are organized under the `/bot` command group:

| Command | Description | Permission |
|---|---|---|
| `/bot join` | Connects the bot to your current voice channel | Everyone |
| `/bot leave` | Disconnects the bot from voice and stops active playback | Everyone |
| `/bot set_auto_disconnect_timeout [seconds]` | Sets or views server voice inactivity timeout in seconds (`0` = never disconnect) | Manage Server |
| `/bot services list` | Lists all discovered services and their statuses | Administrator |
| `/bot services reload <service>` | Hot-reloads code and configuration of a service | Administrator |

---

## TTS Commands (/tts)

All TTS functionality and configuration commands are strictly organized under the `/tts` command group:

| Command | Description | Permission |
|---|---|---|
| `/tts speak <text>` | Synthesizes and speaks text in your voice channel | Everyone |
| `/tts stop` | Stops current speech playback and clears the queue | Everyone |
| `/tts skip` | Skips current speech audio | Everyone |
| `/tts voices` | Lists popular available neural voices (English, Portuguese, etc.) | Everyone |
| `/tts config` | Shows current server TTS configuration | Everyone |
| `/tts set_voice <voice>` | Changes default neural voice for this server (with autocomplete) | Manage Server |
| `/tts set_speed <speed>` | Adjusts speech speed in 0.1x increments (e.g., `1.0x`, `1.2x`, `0.8x`) | Manage Server |
| `/tts set_intro <sound>` | Sets sound cue played before messages from `assets/sounds/` (with autocomplete) | Manage Server |
| `/tts set_intro_delay <delay>` | Sets delay before speech begins over intro sound (e.g., `1.0s`, `0.5s`) | Manage Server |
| `/tts set_channel [channel]` | Sets a text channel to be automatically read aloud in voice (leave empty to disable) | Manage Server |

---

## YouTube Music Commands (/yt)

All YouTube streaming commands are strictly organized under the `/yt` command group:

| Command | Description | Permission |
|---|---|---|
| `/yt play <query>` | Plays audio from a YouTube URL or searches YouTube keywords | Everyone |
| `/yt pause` | Pauses currently playing music | Everyone |
| `/yt resume` | Resumes paused music playback | Everyone |
| `/yt skip` | Skips the currently playing song to the next in queue | Everyone |
| `/yt stop` | Stops music playback and clears the entire queue | Everyone |
| `/yt queue` | Displays the current song and upcoming queue list | Everyone |
| `/yt nowplaying` | Displays detailed info & thumbnail for currently playing track | Everyone |
| `/yt volume <1-100>` | Adjusts playback volume percentage for the server | Everyone |
