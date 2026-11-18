"""Per-chat routing: working directories and group conversation helpers.

This module enables two related features:

**Per-chat working directories**
Map specific Telegram chat IDs to dedicated Claude sessions and working
directories via ``PERSONAL_CHAT_ID`` / ``PERSONAL_CHAT_DIRECTORY`` and
``GROUP_CHAT_ID`` / ``GROUP_CHAT_DIRECTORY`` in your ``.env``.  Messages from
an unrecognised chat fall back to ``APPROVED_DIRECTORY``.

**Group trigger command + conversation history**
In group chats Claude is silent by default.  Only the ``/<prefix>`` command
(default: ``/claude``, also ``/claude@botname``) or an @-mention of the bot
triggers a response.  All other messages are stored in a
per-chat rolling buffer so that when Claude *is* triggered it receives the
recent conversation as context, allowing it to answer questions about what
was discussed without every participant having to @-mention the bot.
"""

import re
from pathlib import Path
from typing import Optional

from src.config.settings import Settings

# Maximum number of messages kept in the per-chat history buffer.
MAX_BUFFER_SIZE = 30

# How many buffered messages are prepended as context when Claude is triggered.
HISTORY_CONTEXT_SIZE = 20


def append_to_buffer(buffer: list[dict[str, str]], sender_name: str, text: str) -> None:
    """Append a message and trim the buffer to :data:`MAX_BUFFER_SIZE`."""
    buffer.append({"sender": sender_name, "text": text})
    if len(buffer) > MAX_BUFFER_SIZE:
        del buffer[: len(buffer) - MAX_BUFFER_SIZE]


def format_history(messages: list[dict[str, str]]) -> str:
    """Return messages formatted as ``Sender: text`` lines."""
    return "\n".join(f"{msg['sender']}: {msg['text']}" for msg in messages)


def _mention_pattern(bot_username: str) -> re.Pattern[str]:
    """Match ``@bot_username`` as a whole mention, case-insensitively."""
    return re.compile(rf"(?<!\w)@{re.escape(bot_username)}(?!\w)", re.IGNORECASE)


def _is_command_trigger(message_text: str, trigger_prefix: str) -> bool:
    command = message_text.split(maxsplit=1)[0].lower() if message_text else ""
    return command.split("@", 1)[0] == f"/{trigger_prefix.lower()}"


def is_group_triggered(
    message_text: str, trigger_prefix: str, bot_username: Optional[str] = None
) -> bool:
    """Return whether a group message addresses the bot.

    True for the ``/<prefix>`` command and, when *bot_username* is given,
    for a message that @-mentions the bot.
    """
    if _is_command_trigger(message_text, trigger_prefix):
        return True
    return bool(
        bot_username
        and message_text
        and _mention_pattern(bot_username).search(message_text)
    )


def strip_group_trigger_prefix(
    message_text: str, trigger_prefix: str, bot_username: Optional[str] = None
) -> str:
    """Remove the ``/<prefix>`` command and any @-mention of the bot."""
    if _is_command_trigger(message_text, trigger_prefix):
        parts = message_text.split(maxsplit=1)
        message_text = parts[1] if len(parts) > 1 else ""
    if bot_username:
        # Tidy only the spaces around the mention: newlines (code blocks) stay.
        mention = _mention_pattern(bot_username).pattern
        message_text = re.sub(
            rf"[ \t]*{mention}[ \t]*", " ", message_text, flags=re.IGNORECASE
        ).strip()
    return message_text


def build_group_prompt(
    history: list[dict[str, str]],
    message_text: str,
    trigger_prefix: str,
    bot_username: Optional[str] = None,
) -> str:
    """Build the Claude prompt for a triggered group message."""
    stripped = strip_group_trigger_prefix(message_text, trigger_prefix, bot_username)
    context_messages = history[-HISTORY_CONTEXT_SIZE:]
    if not context_messages:
        return stripped

    history_str = format_history(context_messages)
    return f"[Recent group conversation:\n{history_str}\n]\n\n{stripped}"


def get_working_directory(chat_id: int, settings: Settings) -> Path:
    """Return the working directory to use for *chat_id*.

    Priority:
    1. ``personal_chat_directory`` if ``chat_id == personal_chat_id``
    2. ``group_chat_directory`` if ``chat_id == group_chat_id``
    3. ``approved_directory`` (the global fallback)
    """
    if (
        settings.personal_chat_id is not None
        and chat_id == settings.personal_chat_id
        and settings.personal_chat_directory is not None
    ):
        return settings.personal_chat_directory
    if (
        settings.group_chat_id is not None
        and chat_id == settings.group_chat_id
        and settings.group_chat_directory is not None
    ):
        return settings.group_chat_directory
    return settings.approved_directory
