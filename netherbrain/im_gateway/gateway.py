import logging

logger = logging.getLogger(__name__)


class IMGateway:
    """Gateway that connects IM bots to the Agent Runtime service."""

    def __init__(self, runtime_url: str) -> None:
        self.runtime_url = runtime_url

    async def start(self) -> None:
        logger.info("Starting IM Gateway, connecting to runtime at %s", self.runtime_url)

    async def stop(self) -> None:
        logger.info("Stopping IM Gateway")
