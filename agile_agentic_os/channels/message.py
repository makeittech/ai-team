"""Normalized chat message models shared by all channels."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """An inbound message from a chat platform."""

    platform: str                      # "telegram" | "discord"
    chat_id: str                       # chat / channel id (where to reply)
    user: str                          # display name / username of the sender
    text: str
    user_id: str | None = None
    message_id: str | None = None
    ts: float = Field(default_factory=time.time)


class OutboundMessage(BaseModel):
    """A message to deliver to a chat platform."""

    text: str
    chat_id: str | None = None         # None -> broadcast to default chats
    platform: str | None = None        # None -> all channels
    author: str | None = None          # agent id that produced it (for prefixing)
