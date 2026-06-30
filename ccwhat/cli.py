"""Main CLI entry point for ccwhat."""

import click

from ccwhat import __version__
from ccwhat.commands.clear_req_resp import clear_req_resp
from ccwhat.commands.discover import discover
from ccwhat.commands.export import export
from ccwhat.commands.import_ import import_
from ccwhat.commands.proxy import proxy
from ccwhat.commands.run import run
from ccwhat.commands.setup import setup
from ccwhat.commands.start import start
from ccwhat.commands.start_mc import start_mc
from ccwhat.commands.web_server import web_server
from ccwhat.config import DEFAULT_RAW_LOG_DIR


class CcwhatGroup(click.Group):
    """Route `ccwhat -- <cli...>` to the launch flow before subcommand lookup."""

    _OPTIONS_WITH_VALUES = {"--port", "--web-port", "--output", "--config"}

    def _has_subcommand_before_separator(self, args: list[str], sep: int) -> bool:
        skip_next = False
        for token in args[:sep]:
            if skip_next:
                skip_next = False
                continue
            if token in self._OPTIONS_WITH_VALUES:
                skip_next = True
                continue
            if token in self.commands:
                return True
        return False

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if "--" in args:
            sep = args.index("--")
            if not self._has_subcommand_before_separator(args, sep):
                ctx.meta["ccwhat_target_args"] = tuple(args[sep + 1 :])
                args = args[:sep]
        return super().parse_args(ctx, args)


@click.group(
    cls=CcwhatGroup,
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@click.option("--port", default=None, show_default="auto", type=int, help="Proxy port.")
@click.option("--web/--no-web", default=True, show_default=True, help="Start and open the viewer.")
@click.option("--web-port", default=None, show_default="auto", type=int, help="Viewer port.")
@click.option(
    "--output",
    default=str(DEFAULT_RAW_LOG_DIR),
    show_default=True,
    type=click.Path(file_okay=False),
    help="Directory where JSONL log files are written.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(dir_okay=False),
    help="Path to config.toml.",
)
@click.option("--no-setup", is_flag=True, help="Skip onboarding even if no config exists.")
@click.version_option(version=__version__, prog_name="ccwhat")
@click.pass_context
def cli(
    ctx: click.Context,
    port: int | None,
    web: bool,
    web_port: int | None,
    output: str,
    config_path: str | None,
    no_setup: bool,
) -> None:
    """ccwhat - record and analyze AI coding CLI traffic.

    Launch a CLI through ccwhat:

      ccwhat -- <cli> [args...]
    """
    if ctx.invoked_subcommand is not None:
        return
    target_args = ctx.meta.get("ccwhat_target_args") or tuple(ctx.args)
    if target_args:
        from pathlib import Path
        ctx.invoke(
            run,
            port=port,
            web=web,
            web_port=web_port,
            output=Path(output),
            config_path=Path(config_path) if config_path else None,
            no_setup=no_setup,
            runtime_recording=True,
            target_args=tuple(target_args),
        )
        return
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


cli.add_command(run)
cli.add_command(start)
cli.add_command(setup)
cli.add_command(discover)
cli.add_command(proxy)
cli.add_command(web_server)
cli.add_command(export)
cli.add_command(import_)
cli.add_command(clear_req_resp)
cli.add_command(start_mc)  # deprecated, hidden alias
