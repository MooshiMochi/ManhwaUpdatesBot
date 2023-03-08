import os
from typing import Optional

import yaml

from src.core.scanlationClasses import *

from .static import RegExpressions


def exit_bot() -> None:
    input("Press enter to continue...")
    exit(1)


async def ensure_environment(bot, logger) -> None:
    if not os.path.isdir(".git"):
        logger.critical(
            "Bot wasn't installed using Git. Please re-install using the command below:"
        )
        logger.critical(
            "       git clone https://github.com/MooshiMochi/ManhwaUpdatesBot"
        )
        await bot.close()
        exit_bot()


def ensure_configs(logger) -> Optional[dict]:
    required_keys = ["token"]

    if not os.path.exists("config.yml"):
        logger.critical(
            "   - config.yml file not found. Please follow the instructions listed in the README.md file."
        )
        exit_bot()

    with open("config.yml", "r") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.critical(
                "   - config.yml file is not a valid YAML file. Please follow the instructions "
                "listed in the README.md file."
            )
            logger.critical("   - Error: " + str(e))
            exit_bot()
            return

    if not config:
        logger.critical(
            "   - config.yml file is empty. Please follow the instructions listed in the README.md file."
        )
        exit_bot()
        return

    if not all(key in config for key in required_keys):
        missing_required_keys = [key for key in required_keys if key not in config]
        missing_required_keys_str = (
            (
                "'"
                + "', '".join([key for key in required_keys if key not in config])
                + "'"
            )
            if len(missing_required_keys) > 1
            else "'" + missing_required_keys[0] + "'"
        )
        if os.name == "nt":
            setup_file = "setup.bat"
        else:
            setup_file = "setup.sh"
        logger.critical(
            f"   - config.yml file is missing following required key(s): "
            f"{missing_required_keys_str}. Please run the {setup_file} file."
        )
        exit_bot()
        return

    default_config = {
        "debug": False,
        "privileged-intents": {
            "members": False,
            "presences": False,
            "message_content": False,
        },
        "extensions": ["src.ext.config", "src.ext.commands", "src.ext.dev"],
        "prefix": "m!",
        "constants": {
            "synced": False,
            "log-channel-id": 0,
            "owner-ids": [0],
            "test-guild-id": 0,
        },
    }

    config_edited: bool = False
    for key, value in default_config.items():
        if key not in config:
            logger.warning(
                "    - config.yml file is missing optional key: '"
                + key
                + "'."
                + " Using default configs."
            )
            config[key] = value
            config_edited = True

    if config_edited:
        logger.warning(
            "    - Using default config values may cause the bot to not function as expected."
        )
        with open("config.yml", "w") as f:
            yaml.safe_dump(config, f)
        logger.warning("    - config.yml file has been updated with default configs.")

    return config


def get_manga_scanlation_class(url: str = None, key: str = None) -> Optional[ABCScan]:
    if url is None and key is None:
        raise ValueError("Either URL or key must be provided.")

    d: dict[str, ABCScan] = SCANLATORS

    if key is not None:
        if existing_class := d.get(key):
            return existing_class

    for name, obj in RegExpressions.__dict__.items():
        if isinstance(obj, re.Pattern) and name.count("_") == 1:
            if obj.match(url):
                return d[name.split("_")[0]]
