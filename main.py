#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import signal
import sys

from dotenv import load_dotenv

from core.bot import ModularBot
from core.config import BotConfig
from core.exceptions import ConfigValidationError


def setup_logging(bot_config: BotConfig) -> None:
    """Configures root logger using parameters from BotConfig and environment variables."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    log_level_str = os.getenv("LOG_LEVEL", bot_config.default_log_level).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    log_file = Path(bot_config.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=log_level,
        format=bot_config.log_format,
        datefmt=bot_config.log_date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.INFO)


def main() -> None:
    """Main application entry point."""
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)

    load_dotenv()

    try:
        bot_config = BotConfig.from_json_file("config/bot.json")
    except ConfigValidationError as e:
        sys.stderr.write(f"Startup aborted due to configuration validation failure: {e}\n")
        sys.exit(1)

    setup_logging(bot_config)
    logger = logging.getLogger("bot.main")

    token = os.getenv("DISCORD_TOKEN")
    if not token or token.strip() == "" or token == "your_token_here":
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

    logger.info("Initializing Modular Discord Bot...")
    try:
        bot = ModularBot()
    except ConfigValidationError as e:
        logger.critical("Startup aborted due to configuration validation failure: %s", e)
        sys.exit(1)

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
    except ConfigValidationError as e:
        logger.critical("Startup aborted due to service configuration validation failure: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.exception("Critical error during bot execution: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
