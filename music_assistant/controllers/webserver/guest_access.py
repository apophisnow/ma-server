"""Guest Access manager for Music Assistant webserver."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from music_assistant_models.api import EventMessage
from music_assistant_models.auth import GuestAccessInfo, UserRole
from music_assistant_models.enums import EventType

from music_assistant.constants import CONF_CORE, MASS_LOGGER_NAME

if TYPE_CHECKING:
    from music_assistant.controllers.webserver import WebserverController

LOGGER = logging.getLogger(f"{MASS_LOGGER_NAME}.guest_access")

# Configuration keys
CONF_KEY_MAIN = "guest_access"
CONF_ENABLED = "enabled"
CONF_CAN_PLAY_MEDIA = "can_play_media"
CONF_CAN_CONTROL_QUEUE = "can_control_queue"
CONF_CAN_CONTROL_PLAYBACK = "can_control_playback"
CONF_CAN_CONTROL_VOLUME = "can_control_volume"
CONF_PLAYER_FILTER = "player_filter"
CONF_PROVIDER_FILTER = "provider_filter"

# Guest user constants
GUEST_USERNAME = "guest"
GUEST_DISPLAY_NAME = "Guest"
GUEST_TOKEN_NAME = "Guest Access Token"


class GuestAccessManager:
    """Manages guest access for the webserver."""

    def __init__(self, webserver: WebserverController) -> None:
        """Initialize the guest access manager.

        :param webserver: WebserverController instance.
        """
        self.webserver = webserver
        self.mass = webserver.mass
        self.logger = LOGGER
        self._enabled: bool = False
        self._guest_user_id: str | None = None
        self._guest_token: str | None = None
        self._on_unload_callbacks: list[Callable[[], None]] = []

    async def setup(self) -> None:
        """Initialize the guest access manager."""
        enabled_value = self.mass.config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_ENABLED}", False)
        self._enabled = bool(enabled_value)
        self._register_api_commands()

        if self._enabled:
            await self._ensure_guest_user()
        else:
            await self._disable_guest_user()

        self.logger.info("Guest access manager initialized (enabled=%s)", self._enabled)

    async def close(self) -> None:
        """Cleanup on exit."""
        for unload_cb in self._on_unload_callbacks:
            unload_cb()

    def _register_api_commands(self) -> None:
        """Register API commands for guest access management."""

        async def get_guest_access_info() -> GuestAccessInfo:
            """Get current guest access information."""
            return await self.get_info()

        async def configure_guest_access(
            enabled: bool,
            can_play_media: bool | None = None,
            can_control_queue: bool | None = None,
            can_control_playback: bool | None = None,
            can_control_volume: bool | None = None,
            player_filter: list[str] | None = None,
            provider_filter: list[str] | None = None,
        ) -> GuestAccessInfo:
            """Configure guest access settings.

            :param enabled: Enable or disable guest access.
            :param can_play_media: Allow guest to play media.
            :param can_control_queue: Allow guest to control queue.
            :param can_control_playback: Allow guest to control playback.
            :param can_control_volume: Allow guest to control volume.
            :param player_filter: List of player IDs guest can access (empty = all).
            :param provider_filter: List of provider instance IDs guest can access (empty = all).
            """
            return await self.configure(
                enabled=enabled,
                can_play_media=can_play_media,
                can_control_queue=can_control_queue,
                can_control_playback=can_control_playback,
                can_control_volume=can_control_volume,
                player_filter=player_filter,
                provider_filter=provider_filter,
            )

        async def regenerate_guest_token() -> GuestAccessInfo:
            """Regenerate the guest access token."""
            return await self.regenerate_token()

        self._on_unload_callbacks.append(
            self.mass.register_api_command(
                "guest_access/info", get_guest_access_info, required_role="admin"
            )
        )
        self._on_unload_callbacks.append(
            self.mass.register_api_command(
                "guest_access/configure", configure_guest_access, required_role="admin"
            )
        )
        self._on_unload_callbacks.append(
            self.mass.register_api_command(
                "guest_access/regenerate_token", regenerate_guest_token, required_role="admin"
            )
        )

    async def get_info(self) -> GuestAccessInfo:
        """Get current guest access information."""
        # Get configuration values
        config = self.mass.config
        can_play_media = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_PLAY_MEDIA}", True)
        )
        can_control_queue = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_QUEUE}", True)
        )
        can_control_playback = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_PLAYBACK}", True)
        )
        can_control_volume = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_VOLUME}", True)
        )
        player_filter = config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PLAYER_FILTER}", [])
        provider_filter = config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PROVIDER_FILTER}", [])

        # Ensure lists
        if not isinstance(player_filter, list):
            player_filter = []
        if not isinstance(provider_filter, list):
            provider_filter = []

        # Get guest URL and token if enabled
        guest_url = None
        guest_token = None
        if self._enabled and self._guest_token:
            base_url = self.webserver.base_url
            guest_url = f"{base_url}/?guest_token={self._guest_token}"
            guest_token = self._guest_token

        return GuestAccessInfo(
            enabled=self._enabled,
            guest_url=guest_url,
            guest_token=guest_token,
            can_play_media=can_play_media,
            can_control_queue=can_control_queue,
            can_control_playback=can_control_playback,
            can_control_volume=can_control_volume,
            player_filter=player_filter,
            provider_filter=provider_filter,
        )

    async def configure(
        self,
        enabled: bool,
        can_play_media: bool | None = None,
        can_control_queue: bool | None = None,
        can_control_playback: bool | None = None,
        can_control_volume: bool | None = None,
        player_filter: list[str] | None = None,
        provider_filter: list[str] | None = None,
    ) -> GuestAccessInfo:
        """Configure guest access settings.

        :param enabled: Enable or disable guest access.
        :param can_play_media: Allow guest to play media.
        :param can_control_queue: Allow guest to control queue.
        :param can_control_playback: Allow guest to control playback.
        :param can_control_volume: Allow guest to control volume.
        :param player_filter: List of player IDs guest can access (empty = all).
        :param provider_filter: List of provider instance IDs guest can access (empty = all).
        """
        # Update enabled state
        prev_enabled = self._enabled
        self._enabled = enabled
        self.mass.config.set(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_ENABLED}", enabled)

        # Update permission settings if provided
        if can_play_media is not None:
            self.mass.config.set(
                f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_PLAY_MEDIA}", can_play_media
            )
        if can_control_queue is not None:
            self.mass.config.set(
                f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_QUEUE}", can_control_queue
            )
        if can_control_playback is not None:
            self.mass.config.set(
                f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_PLAYBACK}", can_control_playback
            )
        if can_control_volume is not None:
            self.mass.config.set(
                f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_VOLUME}", can_control_volume
            )
        if player_filter is not None:
            self.mass.config.set(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PLAYER_FILTER}", player_filter)
        if provider_filter is not None:
            self.mass.config.set(
                f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PROVIDER_FILTER}", provider_filter
            )

        # Handle guest user based on enabled state
        if enabled and not prev_enabled:
            # Enabling guest access - ensure guest user exists
            await self._ensure_guest_user()
            # Update user filters
            await self._update_guest_user_settings()
            self.logger.info("Guest access enabled")
        elif not enabled and prev_enabled:
            # Disabling guest access - disable guest user
            await self._disable_guest_user()
            self.logger.info("Guest access disabled")
        elif enabled:
            # Already enabled, just update settings
            await self._update_guest_user_settings()
            # Notify active guest sessions about the permission changes
            await self._notify_guest_sessions()
            self.logger.info("Guest access settings updated")

        return await self.get_info()

    async def regenerate_token(self) -> GuestAccessInfo:
        """Regenerate the guest access token."""
        if not self._enabled:
            self.logger.warning("Cannot regenerate token: guest access is disabled")
            return await self.get_info()

        if not self._guest_user_id:
            self.logger.warning("Cannot regenerate token: guest user does not exist")
            return await self.get_info()

        # Get guest user
        guest_user = await self.webserver.auth.get_user(self._guest_user_id)
        if not guest_user:
            self.logger.error("Guest user not found")
            return await self.get_info()

        # Revoke old token
        if self._guest_token:
            auth_tokens = await self.webserver.auth.get_user_tokens(self._guest_user_id)
            for token in auth_tokens:
                if token.name == GUEST_TOKEN_NAME:
                    await self.webserver.auth.revoke_token(token.token_id)

        # Create new token
        self._guest_token = await self.webserver.auth.create_token(
            user=guest_user,
            name=GUEST_TOKEN_NAME,
            is_long_lived=True,
        )

        self.logger.info("Guest access token regenerated")
        return await self.get_info()

    async def _ensure_guest_user(self) -> None:
        """Ensure guest user exists and is enabled."""
        auth = self.webserver.auth

        # Check if guest user exists in database (even if disabled)
        # We check the database directly because get_user_by_username filters out disabled users
        guest_user = None
        try:
            # First check database directly to see if user exists (even if disabled)
            user_row = await auth.database.get_row("users", {"username": GUEST_USERNAME})
            if user_row:
                # User exists in database, get the full user object
                self._guest_user_id = user_row["user_id"]

                # If user is disabled, enable them
                if not user_row["enabled"]:
                    await auth.enable_user(self._guest_user_id)
                    self.logger.info("Guest user enabled")

                # Now get the full user object (which will work since user is enabled)
                guest_user = await auth.get_user(self._guest_user_id)
            else:
                # User doesn't exist in database at all, create it
                guest_user = await auth.create_user(
                    username=GUEST_USERNAME,
                    role=UserRole.GUEST,
                    display_name=GUEST_DISPLAY_NAME,
                )
                self._guest_user_id = guest_user.user_id
                self.logger.info("Guest user created: %s", self._guest_user_id)

        except Exception as err:
            self.logger.exception("Failed to ensure guest user: %s", err)
            raise

        # Ensure guest token exists
        if not self._guest_token and guest_user:
            # Look for existing token
            auth_tokens = await auth.get_user_tokens(self._guest_user_id)
            token_exists = any(token.name == GUEST_TOKEN_NAME for token in auth_tokens)

            if token_exists:
                # Token exists in database but we don't have it in memory
                # (it's hashed, so we can't retrieve it)
                # We need to regenerate it to get a usable token
                # First, revoke the old token
                for token in auth_tokens:
                    if token.name == GUEST_TOKEN_NAME:
                        await auth.revoke_token(token.token_id)
                        self.logger.info("Revoked old guest access token")
                        break

            # Create a new token (either first time or after revoking old one)
            self._guest_token = await auth.create_token(
                user=guest_user,
                name=GUEST_TOKEN_NAME,
                is_long_lived=True,
            )
            self.logger.info("Guest access token created")

        # Update guest user settings
        await self._update_guest_user_settings()

    async def _update_guest_user_settings(self) -> None:
        """Update guest user filters based on configuration."""
        if not self._guest_user_id:
            return

        # Get guest user
        guest_user = await self.webserver.auth.get_user(self._guest_user_id)
        if not guest_user:
            return

        config = self.mass.config
        player_filter = config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PLAYER_FILTER}", [])
        provider_filter = config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PROVIDER_FILTER}", [])

        # Ensure lists
        if not isinstance(player_filter, list):
            player_filter = []
        if not isinstance(provider_filter, list):
            provider_filter = []

        # Update user filters
        await self.webserver.auth.update_user_filters(
            target_user=guest_user,
            player_filter=player_filter,
            provider_filter=provider_filter,
        )

    async def _disable_guest_user(self) -> None:
        """Disable the guest user."""
        if not self._guest_user_id:
            return

        try:
            guest_user = await self.webserver.auth.get_user(self._guest_user_id)
            if guest_user and guest_user.enabled:
                await self.webserver.auth.disable_user(self._guest_user_id)
                self.logger.info("Guest user disabled")
        except Exception as err:
            self.logger.debug("Failed to disable guest user: %s", err)

    async def _notify_guest_sessions(self) -> None:
        """Notify all active guest WebSocket sessions about permission changes."""
        if not self._guest_user_id:
            return

        # Get current configuration values
        config = self.mass.config
        can_play_media = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_PLAY_MEDIA}", True)
        )
        can_control_queue = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_QUEUE}", True)
        )
        can_control_playback = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_PLAYBACK}", True)
        )
        can_control_volume = bool(
            config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_CAN_CONTROL_VOLUME}", True)
        )
        player_filter = config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PLAYER_FILTER}", [])
        provider_filter = config.get(f"{CONF_CORE}/{CONF_KEY_MAIN}/{CONF_PROVIDER_FILTER}", [])

        # Ensure lists
        if not isinstance(player_filter, list):
            player_filter = []
        if not isinstance(provider_filter, list):
            provider_filter = []

        # Prepare permission data to send (exclude guest_token and guest_url)
        permission_data = {
            "can_play_media": can_play_media,
            "can_control_queue": can_control_queue,
            "can_control_playback": can_control_playback,
            "can_control_volume": can_control_volume,
            "player_filter": player_filter,
            "provider_filter": provider_filter,
        }

        # Find all WebSocket clients for the guest user
        for client in self.webserver.clients:
            if (
                hasattr(client, "_authenticated_user")
                and client._authenticated_user
                and client._authenticated_user.user_id == self._guest_user_id
            ):
                # Send a message to the client about the permission change
                # The client will need to handle this event and update its state
                try:
                    # Send as an event message so the frontend knows to update
                    event_msg = EventMessage(
                        event=EventType.AUTH_SESSION,
                        object_id="guest_permissions",
                        data=permission_data,
                    )
                    client._send_message_sync(event_msg)
                    self.logger.debug(
                        "Notified guest session about permission changes: %s",
                        client._authenticated_user.username,
                    )
                except Exception as err:
                    self.logger.warning("Failed to notify guest session: %s", err)

    def check_user_permission(self, user_id: str | None, permission: str) -> bool:
        """Check if a user has a specific permission.

        :param user_id: The user ID to check permissions for.
        :param permission: The permission to check (e.g., 'can_play_media').
        :return: True if the user has the permission, False otherwise.
        """
        # If no user_id or not the guest user, allow all permissions (admin/regular users)
        if not user_id or user_id != self._guest_user_id:
            return True

        # Get the permission setting from config
        config = self.mass.config
        permission_key = f"{CONF_CORE}/{CONF_KEY_MAIN}/{permission}"
        return bool(config.get(permission_key, True))
