"""Chat channel integrations (Telegram, Discord).

Channels connect a chat platform to the OS event bus: inbound user messages are
routed through the Fast Track (instant commands) and to agents (chatter), while
agent/slow-track/proactive messages on the bus are pushed back out to the chat.

The concrete channels use established open-source libraries when available
(``python-telegram-bot``, ``discord.py``) and fall back to dependency-light HTTP
transports otherwise. Transports are injectable so everything is testable
offline.
"""

from .message import ChatMessage, OutboundMessage
from .base import Channel
from .manager import ChannelManager
from .telegram_channel import TelegramChannel
from .discord_channel import DiscordChannel

__all__ = [
    "ChatMessage",
    "OutboundMessage",
    "Channel",
    "ChannelManager",
    "TelegramChannel",
    "DiscordChannel",
]
