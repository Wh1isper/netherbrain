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
        # Allow enough time for in-flight sessions to finish during shutdown.
        # Add 60s buffer on top of the drain timeout for post-drain cleanup
        # (SSE signal, Redis close, DB dispose).
        timeout_graceful_shutdown=settings.graceful_shutdown_timeout + 60,
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


# ---------------------------------------------------------------------------
# Database management
# ---------------------------------------------------------------------------


def _alembic_config():
    """Build an Alembic Config from the package's alembic.ini.

    Both alembic.ini and the alembic/ directory live inside the package,
    so this works whether running from source or from an installed package.
    """
    from pathlib import Path

    from alembic.config import Config

    ini_path = Path(__file__).parent / "agent_runtime" / "alembic.ini"
    cfg = Config(str(ini_path))
    return cfg


@main.group()
def db() -> None:
    """Database migration and management commands."""


@db.command()
@click.option("--revision", default="head", help="Target revision (default: head).")
def upgrade(revision: str) -> None:
    """Run database migrations forward."""
    from alembic import command

    command.upgrade(_alembic_config(), revision)
    click.echo(f"Database upgraded to {revision}.")


@db.command()
@click.option("--revision", default="-1", help="Target revision (default: -1, one step back).")
def downgrade(revision: str) -> None:
    """Roll back database migrations."""
    from alembic import command

    command.downgrade(_alembic_config(), revision)
    click.echo(f"Database downgraded to {revision}.")


@db.command()
@click.argument("message")
def migrate(message: str) -> None:
    """Autogenerate a new migration from model changes."""
    from alembic import command

    command.revision(_alembic_config(), message=message, autogenerate=True)
    click.echo(f"Migration generated: {message}")


@db.command()
def current() -> None:
    """Show current database revision."""
    from alembic import command

    command.current(_alembic_config(), verbose=True)


@db.command()
def history() -> None:
    """Show migration history."""
    from alembic import command

    command.history(_alembic_config(), verbose=True)


if __name__ == "__main__":
    main()
