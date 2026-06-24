"""Telegram + Discord channels and the ChannelManager routing."""

import pytest

from agile_agentic_os.bridge import HardwareAdapter, SoftwareAdapter
from agile_agentic_os.channels import (
    ChannelManager,
    DiscordChannel,
    TelegramChannel,
)
from agile_agentic_os.channels.message import ChatMessage
from agile_agentic_os.orchestration import Orchestrator


class FakeTelegramTransport:
    def __init__(self):
        self.sent = []
        self.inbox = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    async def poll(self, offset, timeout=30):
        msgs, self.inbox = self.inbox, []
        return msgs, offset + len(msgs)


class FakeDiscordTransport:
    def __init__(self):
        self.sent = []
        self._dispatch = None

    async def start(self, dispatch):
        self._dispatch = dispatch

    async def send_message(self, channel_id, text):
        self.sent.append((channel_id, text))

    async def stop(self):
        pass

    async def feed(self, msg: ChatMessage):
        await self._dispatch(msg)


def _booted_orchestrator():
    orch = Orchestrator()
    orch.add_adapter(HardwareAdapter())
    orch.add_adapter(SoftwareAdapter())
    orch.boot("Smart Home")
    return orch


@pytest.mark.asyncio
async def test_telegram_inbound_command_fast_track_and_reply():
    orch = _booted_orchestrator()
    transport = FakeTelegramTransport()
    channel = TelegramChannel(transport=transport, default_chat_id="100")
    manager = ChannelManager(orch)  # authorized_users=None -> operator grant
    manager.add_channel(channel)

    transport.inbox = [ChatMessage(platform="telegram", chat_id="100", user="owner",
                                   text="turn off the switch.server_rack")]
    await channel.poll_once()
    await orch.slow_track.drain()

    # A confirmation was sent and the device actually changed.
    assert any("✅" in text for _, text in channel.sent), channel.sent
    assert orch.mcp.get_state("switch.server_rack").data["state"] == "off"
    # The Slow Track agent reaction was also pushed to the chat.
    assert len(channel.sent) >= 2


@pytest.mark.asyncio
async def test_unauthorized_user_command_is_blocked():
    orch = _booted_orchestrator()
    transport = FakeTelegramTransport()
    channel = TelegramChannel(transport=transport, default_chat_id="100")
    manager = ChannelManager(orch, authorized_users={"owner"})
    manager.add_channel(channel)

    transport.inbox = [ChatMessage(platform="telegram", chat_id="100", user="stranger",
                                   text="turn off the switch.server_rack")]
    await channel.poll_once()

    assert any("⛔" in text or "blocked" in text for _, text in channel.sent), channel.sent


@pytest.mark.asyncio
async def test_telegram_non_command_routes_to_agent_reply():
    orch = _booted_orchestrator()
    transport = FakeTelegramTransport()
    channel = TelegramChannel(transport=transport, default_chat_id="100")
    manager = ChannelManager(orch, reply_fn=lambda agent_id, text: f"reply from {agent_id}")
    manager.add_channel(channel)

    transport.inbox = [ChatMessage(platform="telegram", chat_id="100", user="owner",
                                   text="how is everything looking today?")]
    await channel.poll_once()
    assert any("reply from" in text for _, text in channel.sent), channel.sent


@pytest.mark.asyncio
async def test_discord_channel_inbound_and_outbound():
    orch = _booted_orchestrator()
    transport = FakeDiscordTransport()
    channel = DiscordChannel(transport=transport, default_chat_id="999")
    manager = ChannelManager(orch)
    manager.add_channel(channel)
    await channel.start()

    await transport.feed(ChatMessage(platform="discord", chat_id="999", user="owner",
                                     text="turn on the light.kitchen"))
    await orch.slow_track.drain()
    assert any("✅" in text for _, text in transport.sent), transport.sent
    assert orch.mcp.get_state("light.kitchen").data["state"] == "on"


@pytest.mark.asyncio
async def test_proactive_message_broadcast_to_channel():
    from agile_agentic_os.bridge.events import EventKind, SystemEvent

    orch = _booted_orchestrator()
    transport = FakeTelegramTransport()
    channel = TelegramChannel(transport=transport, default_chat_id="100")
    manager = ChannelManager(orch)
    manager.add_channel(channel)

    # Drive a sensor above a compiled trigger threshold -> proactive agent speaks.
    await orch.bus.publish(SystemEvent(
        kind=EventKind.STATE_CHANGED, source="home_assistant",
        entity_id="sensor.living_room_temp", attribute="state", value=33,
    ))
    assert orch.proactive.fired
    # The proactive MESSAGE was forwarded out to the chat channel.
    assert channel.sent, channel.sent


def test_discord_webhook_transport_selected_without_token():
    # No bot token, but a webhook -> webhook transport (no library needed).
    ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/x/y")
    from agile_agentic_os.channels.discord_channel import WebhookDiscordTransport

    assert isinstance(ch.transport, WebhookDiscordTransport)


def test_telegram_requires_token_or_transport():
    with pytest.raises(ValueError):
        TelegramChannel()
