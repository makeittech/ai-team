"""Onboarding wizard (TUI) flow."""

import os

from agile_agentic_os.onboarding import OnboardingWizard, ScriptedPrompter


def test_full_onboarding_flow_generates_project_and_env(tmp_path):
    proj = str(tmp_path / "space")
    env = str(tmp_path / ".env")
    prompter = ScriptedPrompter(
        texts=["розумний дім родини", proj, "777", env],
        secrets=["TG-TOKEN-123"],
        # happy?, export?, telegram?, discord?(no), write-env?
        confirms=[True, True, True, False, True],
        multiselects=[["hardware", "software"]],
    )

    result = OnboardingWizard(prompter=prompter).run()

    # A config with characters was produced and applied.
    assert result.config is not None
    assert 2 <= len(result.config.agents) <= 4
    assert result.adapters == ["hardware", "software"]

    # A runnable opencode project was exported.
    assert os.path.exists(os.path.join(proj, "opencode.json"))
    assert os.path.exists(os.path.join(proj, ".opencode", "agile_os", "config.json"))

    # Telegram captured; Discord skipped.
    assert result.channels["telegram"]["token"] == "TG-TOKEN-123"
    assert "discord" not in result.channels

    # .env written with the expected keys.
    content = open(env, encoding="utf-8").read()
    assert "TELEGRAM_BOT_TOKEN=TG-TOKEN-123" in content
    assert "AAOS_ADAPTERS=hardware,software" in content
    assert "AAOS_CONFIG=" in content
    assert result.env_file == env


def test_onboarding_regenerates_until_confirmed():
    # First "happy?" = False -> regenerate, second = True.
    prompter = ScriptedPrompter(
        texts=["space studio", "космічна студія"],   # two lore prompts
        confirms=[False, True, False, False, False],  # happy(no), happy(yes), export(no), discord(no? n/a), env(no)
        multiselects=[["hardware"]],
    )
    result = OnboardingWizard(prompter=prompter).run()
    assert result.config is not None
    # Two lore inputs were consumed (one per generation attempt).
    assert prompter._texts == []
    assert result.project_dir is None  # export declined


def test_onboarding_discord_webhook_branch(tmp_path):
    prompter = ScriptedPrompter(
        texts=["office", "https://discord.com/api/webhooks/a/b"],  # lore, webhook url
        confirms=[True, False, False, True, False],  # happy, export(no), telegram(no), discord(yes), env(no)
        selects=["webhook"],
        multiselects=[["software"]],
    )
    result = OnboardingWizard(prompter=prompter).run()
    assert result.channels["discord"]["webhook_url"].startswith("https://discord.com")


def test_cli_parser_has_all_subcommands():
    from agile_agentic_os.cli import build_parser

    parser = build_parser()
    # argparse exits on unknown; just ensure known subcommands parse.
    for cmd in ["onboard", "serve", "mcp"]:
        ns = parser.parse_args([cmd])
        assert ns.command == cmd
    ns = parser.parse_args(["export-opencode", "lore", "/tmp/x"])
    assert ns.lore == "lore" and ns.out_dir == "/tmp/x"
