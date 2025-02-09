import logging
import os
import sys
from typing import Optional

import yaml

from src.core.scanlators.classes import AbstractScanlator
from src.static import ScanlatorsRequiringUserAgent


def exit_bot() -> None:
    exit(1)


def load_config(logger: logging.Logger, *, auto_exit: bool = True, filepath: str = "config.yml") -> Optional[dict]:
    root_path = [x for x in sys.path if x.endswith("ManhwaUpdatesBot")][0]
    filepath = os.path.join(root_path, filepath)
    if not os.path.exists(filepath):
        logger.critical(
            "   - config.yml file not found. Please follow the instructions listed in the README.md file."
        )
        if auto_exit:
            return exit_bot()

        logger.critical(
            "   - Creating a new config.yml file..."
        )
        with open(filepath, "w"):
            pass

    with open(filepath, "r") as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.critical(
                "   - config.yml file is not a valid YAML file. Please follow the instructions "
                "listed in the README.md file."
            )
            logger.critical("   - Error: " + str(e))
            if auto_exit:
                exit_bot()
            return {}


def ensure_configs(
        logger, config: dict, scanlators: dict[str, AbstractScanlator], *, auto_exit: bool = True) -> Optional[dict]:
    required_keys = ["token"]
    if not config:
        logger.critical(
            "   - config.yml file is empty. Please follow the instructions listed in the README.md file."
        )
        if auto_exit:
            exit_bot()
            return {}

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
        if auto_exit:
            exit_bot()
            return {}

    default_config = {
        "debug": False,
        "privileged-intents": {
            "members": False,
            "presences": False,
            "message_content": False,
        },
        "extensions": [
            "src.ext.config",
            "src.ext.commands",
            "src.ext.dev",
            "src.ext.bookmark",
            "src.ext.update_check",
            "src.core.handlers.txt_command_error"
        ],
        "prefix": "m!",
        "constants": {
            "first_bot_startup": True,
            "autosync": True,
            "log-channel-id": 0,
            "command-log-channel-id": 0,
            "owner-ids": [0],
            "test-guild-ids": [0],
            "cache-retention-seconds": 300,
            "time-for-manga-to-be-considered-stale": 7776000,
        },
        "proxy": {
            "enabled": True,
            "ip": "2.56.119.93",  # use webshare.io proxy (I recommend)
            "port": 5074,
            "username": "difemjzc",  # noqa
            "password": "em03wrup0hod",  # noqa
        },
        "user-agents": {
            "toonily": None,
            "theblank": None,
        },
        "api-keys": {
            "webshare": None
        },
        "patreon": {
            "access-token": None,
            "campaign-id": None
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

        if isinstance(value, dict):
            for k, v in value.items():
                if k not in config[key]:
                    logger.warning(
                        "    - config.yml file is missing optional key: '"
                        + k
                        + "'."
                        + " Using default configs."
                    )
                    config[key][k] = v
                    config_edited = True

    if config_edited:
        logger.warning(
            "    - Using default config values may cause the bot to not function as expected."
        )
        with open("config.yml", "w") as f:
            yaml.safe_dump(config, f)
        logger.warning("    - config.yml file has been updated with default configs.")

    del_unavailable_scanlators(config, logger, scanlators)

    return config


def del_unavailable_scanlators(config: dict, logger: logging.Logger, scanlators: dict[str, AbstractScanlator]):
    for scanlator in ScanlatorsRequiringUserAgent.scanlators:
        if config.get('user-agents', {}).get(scanlator) is None:
            logger.warning(
                f"- {scanlator} WILL NOT WORK without a valid user-agent. Removing ...\nPlease contact the website "
                f"owner to get a valid user-agent."
            )
            scanlators.pop(scanlator, None)
