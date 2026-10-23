#!/usr/bin/env python3
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.bot import ModularBot

# Logging formatting configuration
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configures root logger with level from environment variable."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    log_dir = Path("data")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bot.log"

    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    # Silence noisy third-party loggers
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.INFO)


def main() -> None:
    """Main application entry point."""
    # Ensure current working directory is the project root
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)

    # Load environment variables from .env
    load_dotenv()

    setup_logging()
    logger = logging.getLogger("bot.main")

    token = os.getenv("DISCORD_TOKEN")
    if not token or token.strip() == "" or token == "your_token_here" or token == "seu_token_aqui":
        logger.error(
            "\n"
            "===============================================================\n"
            "ERROR: DISCORD_TOKEN is not configured!\n"
            "1. Copy `.env.example` to `.env`:\n"
            "   cp .env.example .env\n"
            "2. Edit `.env` and set your Discord bot token.\n"
            "==============================================================="
        )
        sys.exit(1)

    logger.info("Starting Modular Discord Bot...")
    bot = ModularBot()

    # Graceful shutdown handler for SIGINT / SIGTERM
    def handle_signal(sig, frame):
        logger.info("Shutdown signal received. Disconnecting...")
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(bot.close())
        else:
            asyncio.run(bot.close())
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        bot.run(token, log_handler=None)
    except Exception as e:
        logger.exception("Critical error during bot execution: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
