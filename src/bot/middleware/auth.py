"""Telegram bot authentication middleware."""

from datetime import UTC, datetime
from typing import Any, Callable, Dict, Optional, Set

import structlog

logger = structlog.get_logger()


def _is_owner_required_and_missing(
    user_id: int, event: Any, data: Dict[str, Any]
) -> bool:
    """Check if owner restriction applies and user is not an owner.

    When ``owner_users`` is configured, only those users may use the bot
    in private (DM) chats.  Returns True when the request should be
    blocked — i.e. the chat is private and the user is not an owner.
    """
    settings = data.get("settings")
    if not settings:
        return False
    owner_users: Optional[Set[int]] = None
    raw = getattr(settings, "owner_users", None)
    if raw:
        owner_users = set(raw)
    if not owner_users:
        return False  # No owner restriction configured
    chat = event.effective_chat
    chat_type = getattr(chat, "type", None) if chat else None
    if chat_type != "private":
        return False  # Only restrict private chats
    return user_id not in owner_users


async def auth_middleware(handler: Callable, event: Any, data: Dict[str, Any]) -> Any:
    """Check authentication before processing messages.

    This middleware:
    1. Checks if user is authenticated
    2. Attempts authentication if not authenticated
    3. Updates session activity
    4. Logs authentication events
    """
    # Extract user information
    user_id = event.effective_user.id if event.effective_user else None
    username = (
        getattr(event.effective_user, "username", None)
        if event.effective_user
        else None
    )

    if not user_id:
        logger.warning("No user information in update")
        return

    # Get dependencies from context
    auth_manager = data.get("auth_manager")
    audit_logger = data.get("audit_logger")

    if not auth_manager:
        logger.error("Authentication manager not available in middleware context")
        if event.effective_message:
            await event.effective_message.reply_text(
                "🔒 Authentication system unavailable. Please try again later."
            )
        return

    # Check if user is already authenticated
    if auth_manager.is_authenticated(user_id):
        # Update session activity
        if auth_manager.refresh_session(user_id):
            session = auth_manager.get_session(user_id)
            logger.debug(
                "Session refreshed",
                user_id=user_id,
                username=username,
                auth_provider=session.auth_provider if session else None,
            )

        # Block non-owners in private chats
        if _is_owner_required_and_missing(user_id, event, data):
            if event.effective_message:
                await event.effective_message.reply_text(
                    "🔒 This bot's private chat is reserved for the owner.\n"
                    "Please use it in the group chat instead."
                )
            return

        # Continue to handler
        return await handler(event, data)

    # User not authenticated - attempt authentication
    logger.info(
        "Attempting authentication for user", user_id=user_id, username=username
    )

    # Try to authenticate (providers will check whitelist and tokens)
    authentication_successful = await auth_manager.authenticate_user(user_id)

    # Log authentication attempt
    if audit_logger:
        await audit_logger.log_auth_attempt(
            user_id=user_id,
            success=authentication_successful,
            method="automatic",
            reason="message_received",
        )

    if authentication_successful:
        session = auth_manager.get_session(user_id)
        logger.info(
            "User authenticated successfully",
            user_id=user_id,
            username=username,
            auth_provider=session.auth_provider if session else None,
        )

        # Block non-owners in private chats
        if _is_owner_required_and_missing(user_id, event, data):
            if event.effective_message:
                await event.effective_message.reply_text(
                    "🔒 This bot's private chat is reserved for the owner.\n"
                    "Please use it in the group chat instead."
                )
            return

        # Welcome message for new session
        if event.effective_message:
            await event.effective_message.reply_text(
                f"🔓 Welcome! You are now authenticated.\n"
                f"Session started at {datetime.now(UTC).strftime('%H:%M:%S UTC')}"
            )

        # Continue to handler
        return await handler(event, data)

    else:
        # Authentication failed
        logger.warning("Authentication failed", user_id=user_id, username=username)

        if event.effective_message:
            await event.effective_message.reply_text(
                "🔒 <b>Authentication Required</b>\n\n"
                "You are not authorized to use this bot.\n"
                "Please contact the administrator for access.\n\n"
                f"Your Telegram ID: <code>{user_id}</code>\n"
                "Share this ID with the administrator to request access.",
                parse_mode="HTML",
            )
        return  # Stop processing


async def require_auth(handler: Callable, event: Any, data: Dict[str, Any]) -> Any:
    """Decorator-style middleware that requires authentication.

    This is a stricter version that only allows authenticated users.
    """
    user_id = event.effective_user.id if event.effective_user else None
    auth_manager = data.get("auth_manager")

    if not auth_manager or not auth_manager.is_authenticated(user_id):
        if event.effective_message:
            await event.effective_message.reply_text(
                "🔒 Authentication required to use this command."
            )
        return

    return await handler(event, data)


async def admin_required(handler: Callable, event: Any, data: Dict[str, Any]) -> Any:
    """Middleware that requires admin privileges.

    Note: This is a placeholder - admin privileges would need to be
    implemented in the authentication system.
    """
    user_id = event.effective_user.id if event.effective_user else None
    auth_manager = data.get("auth_manager")

    if not auth_manager or not auth_manager.is_authenticated(user_id):
        if event.effective_message:
            await event.effective_message.reply_text("🔒 Authentication required.")
        return

    session = auth_manager.get_session(user_id)
    if not session or not session.user_info:
        if event.effective_message:
            await event.effective_message.reply_text(
                "🔒 Session information unavailable."
            )
        return

    # Check for admin permissions (placeholder logic)
    permissions = session.user_info.get("permissions", [])
    if "admin" not in permissions:
        if event.effective_message:
            await event.effective_message.reply_text(
                "🔒 <b>Admin Access Required</b>\n\n"
                "This command requires administrator privileges.",
                parse_mode="HTML",
            )
        return

    return await handler(event, data)
