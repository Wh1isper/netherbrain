import click


@click.group()
def main() -> None:
    """Netherbrain - Agent service for homelab with IM integration."""


@main.command()
@click.option("--host", default=None, help="Bind host (default: from NETHER_HOST or 0.0.0.0).")
@click.option("--port", default=None, type=int, help="Bind port (default: from NETHER_PORT or 8000).")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
def agent(host: str | None, port: int | None, reload: bool) -> None:
    """Start the Agent Runtime server."""
    import uvicorn

    from netherbrain.agent_runtime.settings import NetherSettings

    settings = NetherSettings()

    uvicorn.run(
        "netherbrain.agent_runtime.app:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_level="warning",  # uvicorn's own logging is intercepted by loguru
    )


@main.command()
@click.option("--runtime-url", default="http://localhost:8000", help="Agent Runtime service URL.")
def gateway(runtime_url: str) -> None:
    """Start the IM Gateway."""
    import asyncio

    from netherbrain.agent_runtime.log import setup_logging
    from netherbrain.agent_runtime.settings import NetherSettings

    settings = NetherSettings()
    setup_logging(settings.log_level)

    from netherbrain.im_gateway.gateway import IMGateway

    gw = IMGateway(runtime_url=runtime_url)
    asyncio.run(gw.start())


if __name__ == "__main__":
    main()
