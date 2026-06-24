"""The onboarding wizard.

Flow:
  1. Pick I/O adapters (hardware / software).
  2. Auto-discover entities and show the inventory.
  3. Describe the space (lore) -> Meta-Agent generates the character org chart.
  4. Review characters; regenerate until happy.
  5. Optionally export a runnable opencode project.
  6. Optionally configure Telegram / Discord channels.
  7. Write a .env with all settings.

The wizard is rendering-agnostic (see :class:`~agile_agentic_os.onboarding.prompter.Prompter`)
so it powers a rich TUI in production and is fully scriptable in tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from ..bridge.adapters.hardware import HardwareAdapter
from ..bridge.adapters.software import SoftwareAdapter
from ..meta.schema import OSConfig
from ..orchestration.orchestrator import Orchestrator
from .prompter import Prompter, ScriptedPrompter


@dataclass
class OnboardingResult:
    config: OSConfig | None = None
    project_dir: str | None = None
    export: dict | None = None
    channels: dict = field(default_factory=dict)
    env_file: str | None = None
    adapters: list[str] = field(default_factory=list)


class OnboardingWizard:
    def __init__(
        self,
        prompter: Prompter | None = None,
        orchestrator_factory: Callable[[], Orchestrator] | None = None,
    ) -> None:
        self.p = prompter or ScriptedPrompter()
        self.orchestrator_factory = orchestrator_factory or (lambda: Orchestrator())
        self.orch: Orchestrator | None = None

    # --- steps ---------------------------------------------------------
    def _choose_adapters(self) -> list[str]:
        choice = self.p.multiselect(
            "Which I/O adapters should this space use?",
            choices=["hardware", "software"],
            defaults=["hardware", "software"],
        )
        return choice or ["hardware"]

    def _build_orchestrator(self, adapters: list[str]) -> Orchestrator:
        orch = self.orchestrator_factory()
        if "hardware" in adapters:
            orch.add_adapter(HardwareAdapter())
        if "software" in adapters:
            orch.add_adapter(SoftwareAdapter())
        return orch

    def _show_inventory(self, orch: Orchestrator) -> None:
        inv = orch.discovery.inventory()
        rows = [[domain, str(len(ids)), ", ".join(ids[:4]) + ("…" if len(ids) > 4 else "")]
                for domain, ids in inv.items()]
        self.p.table("Discovered entities", ["domain", "count", "examples"], rows)

    def _generate_and_review(self, orch: Orchestrator) -> OSConfig:
        entities = orch.discovery.discover()
        while True:
            lore = self.p.text("Describe your space / desired lore",
                               default="серйозна веб-студія")
            config = orch.meta.generate(entities, lore)
            self.p.panel(config.system_domain.background_lore,
                         title=f"🌌 {config.system_domain.name}")
            rows = []
            for a in config.agents:
                rows.append([
                    a.name, a.role,
                    str(len(a.permissions.execute_entities)),
                    str(len(a.permissions.read_only_entities)),
                    str(len(a.proactive_triggers)),
                ])
            self.p.table("Generated characters",
                         ["name", "role", "#exec", "#read", "#triggers"], rows)
            if self.p.confirm("Happy with this crew?", default=True):
                orch.apply_config(config, entities)
                return config

    def _maybe_export(self, orch: Orchestrator, result: OnboardingResult) -> None:
        if not self.p.confirm("Export a runnable opencode project?", default=True):
            return
        out_dir = self.p.text("Project directory", default="./aaos-space")
        export = orch.export_opencode_project(out_dir)
        result.project_dir = out_dir
        result.export = export
        self.p.success(f"opencode project written to {out_dir} "
                       f"({len(export['agent_files'])} agents). Run: cd {out_dir} && opencode")

    def _configure_channels(self, result: OnboardingResult) -> None:
        if self.p.confirm("Connect Telegram?", default=False):
            token = self.p.secret("Telegram bot token")
            chat_id = self.p.text("Default Telegram chat id", default="")
            result.channels["telegram"] = {"token": token, "default_chat_id": chat_id}
            self.p.success("Telegram configured.")
        if self.p.confirm("Connect Discord?", default=False):
            mode = self.p.select("Discord mode", choices=["bot", "webhook"], default="bot")
            if mode == "bot":
                token = self.p.secret("Discord bot token")
                chat_id = self.p.text("Default Discord channel id", default="")
                result.channels["discord"] = {"token": token, "default_chat_id": chat_id}
            else:
                webhook = self.p.text("Discord webhook URL", default="")
                result.channels["discord"] = {"webhook_url": webhook}
            self.p.success("Discord configured.")

    def _write_env(self, result: OnboardingResult) -> None:
        if not self.p.confirm("Write settings to a .env file?", default=True):
            return
        path = self.p.text("Env file path", default=".env")
        lines = [
            "# Agile Agentic OS — generated by onboarding",
            f"AAOS_ADAPTERS={','.join(result.adapters)}",
        ]
        if result.project_dir:
            cfg = os.path.join(result.project_dir, ".opencode", "agile_os", "config.json")
            lines.append(f"AAOS_CONFIG={cfg}")
        tg = result.channels.get("telegram")
        if tg:
            lines.append(f"TELEGRAM_BOT_TOKEN={tg.get('token','')}")
            lines.append(f"TELEGRAM_CHAT_ID={tg.get('default_chat_id','')}")
        dc = result.channels.get("discord")
        if dc:
            lines.append(f"DISCORD_BOT_TOKEN={dc.get('token','')}")
            lines.append(f"DISCORD_CHANNEL_ID={dc.get('default_chat_id','')}")
            lines.append(f"DISCORD_WEBHOOK_URL={dc.get('webhook_url','')}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        result.env_file = path
        self.p.success(f"Settings written to {path}")

    # --- orchestration -------------------------------------------------
    def run(self) -> OnboardingResult:
        result = OnboardingResult()
        self.p.header("Agile Agentic OS — Onboarding")

        result.adapters = self._choose_adapters()
        self.orch = self._build_orchestrator(result.adapters)
        self._show_inventory(self.orch)

        result.config = self._generate_and_review(self.orch)
        self._maybe_export(self.orch, result)
        self._configure_channels(result)
        self._write_env(result)

        self.p.success("Onboarding complete — your agentic space is ready.")
        return result
