from __future__ import annotations

import logging
import os

from tibiabot import config
from tibiabot.bot import TibiaBot


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)-5s %(name)s - %(message)s")
    settings = config.load()
    bot = TibiaBot(settings)
    bot.run(settings.token, log_handler=None)


if __name__ == "__main__":
    main()
