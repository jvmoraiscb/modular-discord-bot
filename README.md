# Modular Discord Bot

Modular Discord Bot built with an independent, service-oriented architecture. Each service has its own lifecycle, dedicated configuration files, and per-guild customization support.

---

## Project Structure

```text
discord-bot/
├── core/
│   ├── bot.py               # ModularBot class (lifecycle and slash command synchronization)
│   ├── ffmpeg.py            # Centralized FFmpeg audio sources, mixing, and stream management
│   ├── voice_queue.py       # Unified guild audio queue and player (shared across all services)
│   ├── service_base.py      # BaseService abstract class for modular services
│   ├── service_manager.py     # Automatic service discovery, loading, and hot reloading
│   └── guild_persistence.py   # Thread-safe persistent storage for per-guild settings
├── config/
│   ├── bot.json             # Root bot settings (prefix, status, auto_disconnect_timeout)
│   ├── tts.json             # Default configuration for the TTS service
│   └── yt.json              # Default configuration for the YouTube music service
├── data/
│   ├── guild_settings.json  # Dynamic per-guild settings
│   ├── bot.log              # Persistent bot logs
│   └── temp/                # Synthesized temporary audio files (auto-cleaned)
├── data/
│   ├── sounds/              # Soundboard & TTS intro audio files
│   ├── temp/                # Ephemeral TTS speech synthesis files
│   └── guild_settings.db    # Dynamic per-guild SQLite database
├── services/
│   ├── tts/                 # Text-to-Speech service module
│   │   ├── service.py       # Slash commands (/tts) and chat-to-speech listener
│   │   ├── tts_engine.py    # Edge-TTS synthesizer and audio mixing
│   │   └── voice_queue.py   # Compatibility bridge to core.voice_queue
│   └── yt/                  # YouTube music streaming service
│       ├── service.py       # Slash commands (/yt play, /yt queue, /yt skip, etc.)
│       ├── music_queue.py   # Compatibility bridge to core.voice_queue
│       └── ytdl_player.py   # yt-dlp audio extraction and FFmpeg source
├── docs/
│   └── architecture.md      # Detailed technical architecture guide and flow documentation
├── .env.example             # Environment variables template
├── requirements.txt         # Project dependencies
└── main.py                  # Application entry point
```

> **Developer Guide**: For a comprehensive, step-by-step technical explanation of the bot internals, flow diagrams, and how to create new services, see [docs/architecture.md](file:///home/jvmoraiscb/git-repositories/discord-bot/docs/architecture.md).

---

## How the Architecture Works

1. **Global Service Configuration (`config/<service>.json`)**:
   Each service has its own JSON file defining global settings (enabled state, validation bounds `_min`/`_max`, binary paths, sound directories).
2. **Dynamic Per-Guild Overrides (`data/guild_settings.db`)**:
   Individual servers can customize their preferences (voice, rate, intro sounds, volume) via slash commands. Overrides are stored in dedicated SQLite tables (`bot_config`, `tts_config`, `yt_config`, `sounds_config`).
3. **Auto Discovery & Pluggability**:
   Any new folder created inside `services/` containing a `service.py` subclassing `BaseService` is discovered and loaded automatically by `ServiceManager`.
4. **Unified Core Audio Queue (`core/voice_queue.py`)**:
   All audio-producing services (`tts`, `yt`, `sounds`) feed into a single unified guild queue managed by the core. Each service enqueues audio with its desired playback volume defined in its service configuration (`config/<service>.json`) or per-guild settings, preventing audio conflicts and duplicate disconnect timers.
5. **Centralized FFmpeg Core (`core/ffmpeg.py`)**:
   All audio source instantiation (`discord.FFmpegPCMAudio`, `discord.PCMVolumeTransformer`), stream reconnect parameters, volume clamping, and complex audio filter mixing (e.g., intro sound overlays with speech) are centralized in `core.ffmpeg`. Services delegate all audio processing to core functions rather than managing FFmpeg processes directly.

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

## Docker / VPS Deployment

### Using Docker Compose (Recommended)
1. Configure your `.env` file with `DISCORD_TOKEN`.
2. Build and run in background:
```bash
docker compose up -d --build
```
3. View logs:
```bash
docker compose logs -f
```
4. Stop container:
```bash
docker compose down
```

### Using Plain Docker
1. Build the Docker image:
```bash
docker build -t discord-bot .
```
2. Run the container with persistent data and configuration:
```bash
docker run -d \
  --name discord-bot \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/config:/app/config" \
  discord-bot
```

---

## Core Bot Commands (/bot)

All core bot management, voice connection, audio playback controls, and service administration commands are organized under the `/bot` command group:

| Command | Description | Permission |
|---|---|---|
| `/bot help` | Displays reference list of all available bot commands and descriptions | Everyone |
| `/bot join` | Connects the bot to your current voice channel | Everyone |
| `/bot leave` | Disconnects the bot from voice and stops active playback | Everyone |
| `/bot pause` | Pauses currently playing audio | Everyone |
| `/bot resume` | Resumes paused audio playback | Everyone |
| `/bot skip` | Skips the currently playing audio track | Everyone |
| `/bot stop` | Stops audio playback and clears the entire queue | Everyone |
| `/bot queue` | Shows the unified audio queue with service tags (yt, tts, etc.) | Everyone |
| `/bot nowplaying` | Shows details of currently playing audio across all services (YouTube or TTS) | Everyone |
| `/bot config` | Displays bot configuration, guild settings, and modular service statuses | Everyone |
| `/bot set_auto_disconnect_timeout [seconds]` | Sets or views server voice inactivity timeout in seconds (`0` = never disconnect) | Manage Server |

---

## TTS Commands (/tts)

All TTS functionality and configuration commands are strictly organized under the `/tts` command group:

| Command | Description | Permission |
|---|---|---|
| `/tts speak <text>` | Synthesizes and speaks text in your voice channel | Everyone |
| `/tts config` | Shows current server TTS configuration | Everyone |
| `/tts set_voice <voice>` | Changes default neural voice for this server (with autocomplete) | Manage Server |
| `/tts set_voice_speed <speed>` | Adjusts speech speed in 0.1x increments (e.g., `1.0x`, `1.2x`, `0.8x`) | Manage Server |
| `/tts set_volume <volume>` | Sets default speech playback volume percentage for this server (1-100) | Manage Server |
| `/tts set_max_text_length <length>` | Sets maximum allowed text length for speech synthesis | Manage Server |
| `/tts set_intro <sound>` | Sets sound cue played before messages from `data/sounds/` (with autocomplete) | Manage Server |
| `/tts set_intro_delay <delay>` | Sets delay before speech begins over intro sound (e.g., `1.0s`, `0.5s`) | Manage Server |
| `/tts set_channel [channel]` | Sets a text channel to be automatically read aloud in voice (leave empty to disable) | Manage Server |
| `/tts help` | Displays available commands and usage guide for the Text-to-Speech service | Everyone |

---

## YouTube Music Commands (/yt)

All YouTube streaming commands are strictly organized under the `/yt` command group:

| Command | Description | Permission |
|---|---|---|
| `/yt play <query>` | Plays audio from a YouTube URL or searches YouTube keywords | Everyone |
| `/yt download <query> [audio_only]` | Downloads a YouTube video (MP4) or audio (MP3) directly to your computer | Everyone |
| `/yt config` | Shows current YouTube playback configuration for this server | Everyone |
| `/yt set_volume <1-100>` | Adjusts playback volume percentage for the server | Everyone |
| `/yt help` | Displays available commands and usage guide for the YouTube music service | Everyone |

---

## Soundboard Commands (/sounds)

All soundboard effects and audio file management commands are organized under the `/sounds` command group:

| Command | Description | Permission |
|---|---|---|
| `/sounds play <sound>` | Plays an audio sound effect from `data/sounds/` in your voice channel (with autocomplete) | Everyone |
| `/sounds list` | Lists all available sound effects in `data/sounds/` with file sizes | Everyone |
| `/sounds add <name> <file>` | Uploads and saves a new audio file (.mp3, .wav, .ogg, .m4a) to `data/sounds/` | Everyone |
| `/sounds set_volume <1-100>` | Adjusts default soundboard playback volume percentage for the server | Everyone |
| `/sounds help` | Displays available commands and usage guide for the Soundboard service | Everyone |
