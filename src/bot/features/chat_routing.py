"""Per-chat routing: working directories and group conversation helpers.

This module enables two related features:

**Per-chat working directories**
Map specific Telegram chat IDs to dedicated Claude sessions and working
directories via ``PERSONAL_CHAT_ID`` / ``PERSONAL_CHAT_DIRECTORY`` and
``GROUP_CHAT_ID`` / ``GROUP_CHAT_DIRECTORY`` in your ``.env``.  Messages from
an unrecognised chat fall back to ``APPROVED_DIRECTORY``.

**Group trigger command + conversation history**
In group chats Claude is silent by default.  Only the ``/<prefix>`` command
(default: ``/claude``, also ``/claude@botname``) triggers a response.  All other messages are stored in a
per-chat rolling buffer so that when Claude *is* triggered it receives the
recent conversation as context, allowing it to answer questions about what
was discussed without every participant having to @-mention the bot.
"""

from pathlib import Path

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


def is_group_triggered(message_text: str, trigger_prefix: str) -> bool:
    """Return whether a group message is the ``/<prefix>`` command."""
    command = message_text.split(maxsplit=1)[0].lower() if message_text else ""
    return command.split("@", 1)[0] == f"/{trigger_prefix.lower()}"


def strip_group_trigger_prefix(message_text: str, trigger_prefix: str) -> str:
    """Remove the ``/<prefix>`` or ``/<prefix>@botname`` command."""
    if not is_group_triggered(message_text, trigger_prefix):
        return message_text
    parts = message_text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def build_group_prompt(
    history: list[dict[str, str]], message_text: str, trigger_prefix: str
) -> str:
    """Build the Claude prompt for a triggered group message."""
    stripped = strip_group_trigger_prefix(message_text, trigger_prefix)
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
