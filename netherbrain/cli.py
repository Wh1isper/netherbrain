import click


@click.group()
def main() -> None:
    """Netherbrain - Agent service for homelab with IM integration."""


@main.command()
@click.option("--host", default="0.0.0.0", help="Bind host.")  # noqa: S104
@click.option("--port", default=8000, type=int, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
def agent(host: str, port: int, reload: bool) -> None:
    """Start the Agent Runtime server."""
    import uvicorn

    uvicorn.run(
        "netherbrain.agent_runtime.app:app",
        host=host,
        port=port,
        reload=reload,
    )


@main.command()
@click.option("--runtime-url", default="http://localhost:8000", help="Agent Runtime service URL.")
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Log level.",
)
def gateway(runtime_url: str, log_level: str) -> None:
    """Start the IM Gateway."""
    import asyncio
    import logging

    from netherbrain.im_gateway.gateway import IMGateway

    logging.basicConfig(level=getattr(logging, log_level.upper()))
    gw = IMGateway(runtime_url=runtime_url)
    asyncio.run(gw.start())


if __name__ == "__main__":
    main()
