import os
import config


def is_paused() -> bool:
    return os.path.exists(config.PAUSE_FILE)
