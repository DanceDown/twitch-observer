"""Shared chat message delivery context for parallel processing."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Protocol

_current_chat_message_sequence: ContextVar[int | None] = ContextVar("current_chat_message_sequence", default=None)


class ChatMessageCompletionNotifier(Protocol):
    """Tracks chat processing milestones for ordered delivery."""

    async def reserve_message(self, sequence: int) -> None:
        """Reserve an ordered delivery slot for a chat message."""
        ...

    async def complete_message_routing(self, sequence: int) -> None:
        """Mark routing complete once all target slots are known."""
        ...

    async def complete_message(self, sequence: int) -> None:
        """Mark all delivery work complete for one chat message."""
        ...


def get_current_chat_message_sequence() -> int | None:
    """Return the chat sequence bound to the current async context."""
    return _current_chat_message_sequence.get()


def bind_chat_message_sequence(sequence: int) -> Token[int | None]:
    """Bind one chat sequence to the current async context."""
    return _current_chat_message_sequence.set(sequence)


def reset_chat_message_sequence(token: Token[int | None]) -> None:
    """Restore the previous chat sequence context."""
    _current_chat_message_sequence.reset(token)
