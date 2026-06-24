"""Command-line interface for the Agile Agentic OS.

Subcommands:
  onboard           interactive TUI wizard (adapters -> lore -> agents -> channels)
  serve             run the OS daemon + chat channels (Telegram / Discord)
  export-opencode   boot a space from a lore string and write an opencode project
  mcp               run the opencode MCP stdio backend server
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


def _cmd_onboard(args: argparse.Namespace) -> int:
    from .onboarding import OnboardingWizard
    from .onboarding.prompter import RichPrompter

    try:
        prompter = RichPrompter()
    except Exception:  # rich not installed
        from .onboarding.prompter import ScriptedPrompter

        print("(rich not installed; falling back to defaults)")
        prompter = ScriptedPrompter()
    OnboardingWizard(prompter=prompter).run()
    return 0


def _build_orchestrator_from_env():
    from .bridge.adapters.hardware import HardwareAdapter
    from .bridge.adapters.software import SoftwareAdapter
    from .meta.schema import OSConfig
    from .orchestration.orchestrator import Orchestrator

    orch = Orchestrator()
    adapters = os.environ.get("AAOS_ADAPTERS", "hardware,software")
    if "hardware" in adapters:
        orch.add_adapter(HardwareAdapter())
    if "software" in adapters:
        orch.add_adapter(SoftwareAdapter())

    config_path = os.environ.get("AAOS_CONFIG")
    if config_path and os.path.exists(config_path):
        import json

        with open(config_path, encoding="utf-8") as fh:
            orch.apply_config(OSConfig(**json.load(fh)), orch.discovery.discover())
    else:
        orch.boot(os.environ.get("AAOS_LORE", "Smart Home"))
    return orch


def _attach_channels_from_env(orch):
    from .channels import ChannelManager, DiscordChannel, TelegramChannel

    manager = ChannelManager(orch)
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        manager.add_channel(TelegramChannel(
            token=os.environ["TELEGRAM_BOT_TOKEN"],
            default_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
        ))
    if os.environ.get("DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_WEBHOOK_URL"):
        manager.add_channel(DiscordChannel(
            token=os.environ.get("DISCORD_BOT_TOKEN"),
            webhook_url=os.environ.get("DISCORD_WEBHOOK_URL"),
            default_chat_id=os.environ.get("DISCORD_CHANNEL_ID") or None,
        ))
    return manager


def _cmd_serve(args: argparse.Namespace) -> int:
    async def _run() -> None:
        orch = _build_orchestrator_from_env()
        manager = _attach_channels_from_env(orch)
        orch.start()
        orch.slow_track.start()
        await manager.start()
        print(f"[agile-os] serving: {len(orch.agents)} agents, "
              f"{len(manager.channels)} channel(s). Ctrl-C to stop.")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
            pass
        finally:
            await manager.stop()
            await orch.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:  # pragma: no cover
        pass
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from .bridge.adapters.hardware import HardwareAdapter
    from .bridge.adapters.software import SoftwareAdapter
    from .orchestration.orchestrator import Orchestrator

    orch = Orchestrator()
    orch.add_adapter(HardwareAdapter())
    orch.add_adapter(SoftwareAdapter())
    orch.boot(args.lore)
    res = orch.export_opencode_project(args.out_dir)
    print(f"Wrote opencode project to {args.out_dir}: "
          f"{len(res['agent_files'])} agents, config at {res['config_json']}")
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .integrations.opencode.mcp_stdio import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agile-os", description="Agile Agentic OS")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("onboard", help="interactive onboarding wizard (TUI)").set_defaults(func=_cmd_onboard)
    sub.add_parser("serve", help="run the OS daemon + chat channels").set_defaults(func=_cmd_serve)

    exp = sub.add_parser("export-opencode", help="generate a runnable opencode project")
    exp.add_argument("lore", help="domain / lore description, e.g. 'серйозна веб-студія'")
    exp.add_argument("out_dir", help="output directory")
    exp.set_defaults(func=_cmd_export)

    sub.add_parser("mcp", help="run the opencode MCP stdio backend").set_defaults(func=_cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
