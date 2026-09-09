from .settings import ConfigCenter
from loguru import logger

def init_config():
    logger.info("Loading configuration...")
    config_center = ConfigCenter()
    app_config = config_center.load()

    logger.info("Configuration loaded successfully.")
    logger.debug(f"Current Configuration : {app_config}")
    return app_config

app_config = init_config()

if __name__ == "__main__":
    init_config()
