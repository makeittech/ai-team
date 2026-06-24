"""ChannelManager: bridge between chat platforms and the OS.

Inbound:  chat message -> (enter context) -> Fast Track command? -> else agent reply.
Outbound: agent / slow-track / proactive MESSAGE events on the bus -> chat.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from ..bridge.events import EventKind, SystemEvent
from ..guardrails.models import Permission
from ..orchestration.orchestrator import Orchestrator
from .base import Channel
from .message import ChatMessage

# reply_fn(agent_id, text) -> reply text (sync or async)
ReplyFn = Callable[[str, str], "Awaitable[str] | str"]

_AGENT_SOURCES = {"slow_track", "proactive", "a2a", "agent"}


class ChannelManager:
    def __init__(
        self,
        orchestrator: Orchestrator,
        reply_fn: ReplyFn | None = None,
        authorized_users: set[str] | None = None,
        operator_permissions: list[Permission] | None = None,
    ) -> None:
        self.orch = orchestrator
        self.reply_fn = reply_fn
        # None => any chat user may operate (demo-friendly). Provide a set to whitelist.
        self.authorized_users = authorized_users
        self.operator_permissions = operator_permissions or [Permission(entity_glob="*", actions=["*"])]
        self._granted: set[str] = set()
        self.channels: list[Channel] = []
        self.last_chat: tuple[str, str] | None = None  # (platform, chat_id)
        self.inbound_log: list[ChatMessage] = []
        # Forward agent-originated bus messages out to chat.
        orchestrator.bus.subscribe(self._on_bus_message, EventKind.MESSAGE.value)

    def _ensure_operator(self, user: str) -> None:
        """Grant authorized human users operator RBAC (payload limits still apply)."""
        if user in self._granted:
            return
        if self.authorized_users is not None and user not in self.authorized_users:
            return  # unauthorized -> no grant; Guardrails will block their commands
        for perm in self.operator_permissions:
            self.orch.guardrail.rbac.grant(user, perm)
        self._granted.add(user)

    # --- registration --------------------------------------------------
    def add_channel(self, channel: Channel) -> None:
        channel.bind(self._on_inbound)
        self.channels.append(channel)

    def _channels_for(self, platform: str | None):
        return [c for c in self.channels if platform is None or c.platform == platform]

    # --- inbound (chat -> OS) -----------------------------------------
    async def _on_inbound(self, msg: ChatMessage) -> None:
        self.inbound_log.append(msg)
        self.last_chat = (msg.platform, msg.chat_id)

        # 1) record the message into the OS context / event stream.
        await self.orch.bus.publish(SystemEvent(
            kind=EventKind.MESSAGE, source=msg.platform, actor=msg.user, value=msg.text,
        ))

        # 1b) authorize the human as an operator (payload limits still enforced).
        self._ensure_operator(msg.user)

        # 2) Fast Track: is this a direct command?
        result = await self.orch.fast_track.try_handle(msg.text, actor=msg.user)
        if result is not None:
            intent = result["intent"]
            if result["ok"]:
                reply = (
                    f"✅ {intent['action_type']} → {intent['entity_id']} "
                    f"(done in {result['latency_ms']:.0f} ms)"
                )
            else:
                err = result["result"].get("error", "blocked")
                reply = f"⛔ {intent['action_type']} → {intent['entity_id']} blocked: {err}"
            await self._reply_to(msg, reply)
            # The Slow Track reaction (if any) arrives via the bus and is
            # broadcast automatically by _on_bus_message.
            return

        # 3) Not a command -> route to an agent for an in-character reply.
        agent_id = self._pick_agent(msg.text)
        if agent_id is None:
            await self._reply_to(msg, "(no agents configured yet — run onboarding)")
            return
        reply = await self._generate_reply(agent_id, msg.text)
        await self._reply_to(msg, f"{self._display(agent_id)}: {reply}")

    def _pick_agent(self, text: str) -> str | None:
        low = text.lower()
        for agent in self.orch.agents.values():
            if f"@{agent.id}".lower() in low or (agent.spec.name and agent.spec.name.lower() in low):
                return agent.id
        return next(iter(self.orch.agents), None)

    def _display(self, agent_id: str) -> str:
        agent = self.orch.agents.get(agent_id)
        return agent.spec.name if agent and agent.spec.name else agent_id

    async def _generate_reply(self, agent_id: str, text: str) -> str:
        if self.reply_fn is not None:
            res = self.reply_fn(agent_id, text)
            return await res if hasattr(res, "__await__") else res
        agent = self.orch.agents.get(agent_id)
        return agent.react(text) if agent else ""

    async def _reply_to(self, msg: ChatMessage, text: str) -> None:
        for ch in self._channels_for(msg.platform):
            await ch.send(text, chat_id=msg.chat_id)

    # --- outbound (OS -> chat) ----------------------------------------
    async def _on_bus_message(self, event: SystemEvent) -> None:
        is_agent = event.actor in self.orch.agents or event.source in _AGENT_SOURCES
        if not is_agent:
            return  # skip user/echo messages
        text = str(event.value or "")
        if not text:
            return
        author = self._display(event.actor) if event.actor in self.orch.agents else event.actor
        out = f"{author}: {text}" if author and not text.startswith(f"{author}:") else text
        await self.broadcast(out)

    async def broadcast(self, text: str) -> None:
        if self.last_chat is not None:
            platform, chat_id = self.last_chat
            for ch in self._channels_for(platform):
                await ch.send(text, chat_id=chat_id)
            return
        for ch in self.channels:
            await ch.send(text, chat_id=ch.default_chat_id)

    # --- lifecycle -----------------------------------------------------
    async def start(self) -> None:
        for ch in self.channels:
            await ch.start()

    async def stop(self) -> None:
        for ch in self.channels:
            await ch.stop()
