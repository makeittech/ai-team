"""Prompter abstraction for the onboarding TUI.

The wizard logic talks to a :class:`Prompter` so it can render a rich terminal UI
in production (:class:`RichPrompter`) while remaining fully scriptable in tests
(:class:`ScriptedPrompter`).
"""

from __future__ import annotations

from typing import Protocol


class Prompter(Protocol):
    def header(self, text: str) -> None: ...
    def info(self, text: str) -> None: ...
    def success(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...
    def panel(self, body: str, title: str = "") -> None: ...
    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None: ...
    def text(self, prompt: str, default: str | None = None) -> str: ...
    def secret(self, prompt: str) -> str: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...
    def select(self, prompt: str, choices: list[str], default: str | None = None) -> str: ...
    def multiselect(self, prompt: str, choices: list[str], defaults: list[str] | None = None) -> list[str]: ...


class RichPrompter:
    """A pretty terminal UI built on the ``rich`` library."""

    def __init__(self) -> None:
        from rich.console import Console

        self.console = Console()

    def header(self, text: str) -> None:
        from rich.panel import Panel
        from rich.text import Text

        self.console.print(Panel(Text(text, justify="center", style="bold cyan"), border_style="cyan"))

    def info(self, text: str) -> None:
        self.console.print(f"[dim]›[/] {text}")

    def success(self, text: str) -> None:
        self.console.print(f"[bold green]✔[/] {text}")

    def error(self, text: str) -> None:
        self.console.print(f"[bold red]✘[/] {text}")

    def panel(self, body: str, title: str = "") -> None:
        from rich.panel import Panel

        self.console.print(Panel(body, title=title, border_style="magenta"))

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        from rich.table import Table

        t = Table(title=title, header_style="bold")
        for c in columns:
            t.add_column(c, overflow="fold")
        for r in rows:
            t.add_row(*[str(x) for x in r])
        self.console.print(t)

    def text(self, prompt: str, default: str | None = None) -> str:
        from rich.prompt import Prompt

        return Prompt.ask(prompt, default=default, console=self.console)

    def secret(self, prompt: str) -> str:
        from rich.prompt import Prompt

        return Prompt.ask(prompt, password=True, console=self.console)

    def confirm(self, prompt: str, default: bool = True) -> bool:
        from rich.prompt import Confirm

        return Confirm.ask(prompt, default=default, console=self.console)

    def select(self, prompt: str, choices: list[str], default: str | None = None) -> str:
        from rich.prompt import Prompt

        return Prompt.ask(prompt, choices=choices, default=default or choices[0], console=self.console)

    def multiselect(self, prompt: str, choices: list[str], defaults: list[str] | None = None) -> list[str]:
        self.info(prompt)
        for i, c in enumerate(choices, 1):
            self.console.print(f"  [cyan]{i}[/]. {c}")
        default_str = "all"
        raw = self.text("Select (comma-separated numbers, or 'all')", default=default_str)
        if raw.strip().lower() == "all":
            return list(choices)
        picked: list[str] = []
        for token in raw.split(","):
            token = token.strip()
            if token.isdigit() and 1 <= int(token) <= len(choices):
                picked.append(choices[int(token) - 1])
        return picked or (defaults or list(choices))


class ScriptedPrompter:
    """Deterministic prompter for tests / non-interactive runs.

    Provide queued answers per primitive; rendering calls are captured in
    :attr:`output` for assertions.
    """

    def __init__(
        self,
        texts: list[str] | None = None,
        secrets: list[str] | None = None,
        confirms: list[bool] | None = None,
        selects: list[str] | None = None,
        multiselects: list[list[str]] | None = None,
    ) -> None:
        self._texts = list(texts or [])
        self._secrets = list(secrets or [])
        self._confirms = list(confirms or [])
        self._selects = list(selects or [])
        self._multiselects = list(multiselects or [])
        self.output: list[tuple[str, str]] = []

    # rendering -> recorded
    def header(self, text: str) -> None: self.output.append(("header", text))
    def info(self, text: str) -> None: self.output.append(("info", text))
    def success(self, text: str) -> None: self.output.append(("success", text))
    def error(self, text: str) -> None: self.output.append(("error", text))
    def panel(self, body: str, title: str = "") -> None: self.output.append(("panel", f"{title}: {body}"))

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        self.output.append(("table", f"{title} ({len(rows)} rows)"))

    # input -> queued
    def text(self, prompt: str, default: str | None = None) -> str:
        return self._texts.pop(0) if self._texts else (default or "")

    def secret(self, prompt: str) -> str:
        return self._secrets.pop(0) if self._secrets else ""

    def confirm(self, prompt: str, default: bool = True) -> bool:
        return self._confirms.pop(0) if self._confirms else default

    def select(self, prompt: str, choices: list[str], default: str | None = None) -> str:
        return self._selects.pop(0) if self._selects else (default or choices[0])

    def multiselect(self, prompt: str, choices: list[str], defaults: list[str] | None = None) -> list[str]:
        return self._multiselects.pop(0) if self._multiselects else (defaults or list(choices))
