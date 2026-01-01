"""AES67 Multicast Provider implementation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from music_assistant.models.player_provider import PlayerProvider

from .constants import (
    AES67_DEFAULT_BIT_DEPTH,
    AES67_DEFAULT_SAMPLE_RATE,
    AES67_RTP_PORT_DEFAULT,
    CONF_MULTICAST_STREAMS,
    DSCP_DEFAULT,
    TTL_DEFAULT,
)
from .player import AES67Player

if TYPE_CHECKING:
    from zeroconf import ServiceStateChange
    from zeroconf.asyncio import AsyncServiceInfo


class AES67Provider(PlayerProvider):
    """
    AES67/RAVENNA/Dante Multicast Audio Provider.

    Streams audio to professional AES67-compliant receivers via IP multicast
    using standards-compliant RTP/RTCP (RFC 3550) for transport and
    SAP/SDP (RFC 2974, RFC 4566) for stream discovery.
    """

    async def handle_async_init(self) -> None:
        """Handle async initialization of the provider."""
        self.logger.info("Initializing AES67 Multicast Provider")

        # Get configured multicast streams (stored as JSON string)
        multicast_streams_str = self.config.get_value(CONF_MULTICAST_STREAMS)

        if not multicast_streams_str:
            self.logger.warning(
                "No multicast streams configured. Please configure at least one stream."
            )
            return

        # Ensure it's a string
        if not isinstance(multicast_streams_str, str):
            self.logger.error("multicast_streams configuration must be a JSON string")
            return

        # Parse JSON configuration
        try:
            multicast_streams = json.loads(multicast_streams_str)
        except json.JSONDecodeError as err:
            self.logger.error("Invalid JSON in multicast streams configuration: %s", err)
            return

        if not isinstance(multicast_streams, list):
            self.logger.error("multicast_streams must be a JSON array")
            return

        # Create virtual player for each configured stream
        for item in multicast_streams:
            # Skip non-dict items (for type safety)
            if not isinstance(item, dict):
                continue
            # Type narrowed to dict here
            stream_config: dict[str, Any] = item
            await self._create_stream_player(stream_config)

    async def _create_stream_player(self, stream_config: dict[str, Any]) -> None:
        """
        Create virtual player for a multicast stream.

        :param stream_config: Stream configuration dictionary
        """
        # Set defaults for missing configuration keys
        stream_config.setdefault("stream_name", "AES67 Stream")
        stream_config.setdefault("rtp_port", AES67_RTP_PORT_DEFAULT)
        stream_config.setdefault("sample_rate", AES67_DEFAULT_SAMPLE_RATE)
        stream_config.setdefault("bit_depth", AES67_DEFAULT_BIT_DEPTH)
        stream_config.setdefault("channels", 2)
        stream_config.setdefault("ttl", TTL_DEFAULT)
        stream_config.setdefault("dscp", DSCP_DEFAULT)
        stream_config.setdefault("enable_sap", True)

        stream_name = stream_config["stream_name"]
        multicast_address = stream_config.get("multicast_address")
        rtp_port = stream_config["rtp_port"]

        if not multicast_address:
            self.logger.error("Stream '%s' missing multicast_address, skipping", stream_name)
            return

        # Validate multicast address (239.x.x.x range for AES67)
        if not multicast_address.startswith("239."):
            self.logger.warning(
                "Stream '%s' multicast address '%s' is not in AES67 recommended range (239.x.x.x)",
                stream_name,
                multicast_address,
            )

        # Create player ID from multicast address
        player_id = f"aes67_{multicast_address.replace('.', '_')}_{rtp_port}"

        # Check if player already exists
        if self.mass.players.get(player_id):
            self.logger.debug("Player %s already exists, skipping", player_id)
            return

        # Create AES67 player
        player = AES67Player(
            provider=self,
            player_id=player_id,
            stream_config=stream_config,
        )

        # Register player with MA
        await self.mass.players.register(player)

        self.logger.info(
            "Created AES67 stream: %s -> %s:%d (%dHz, %d-bit, %dch)",
            stream_name,
            multicast_address,
            rtp_port,
            stream_config["sample_rate"],
            stream_config["bit_depth"],
            stream_config["channels"],
        )

    async def loaded_in_mass(self) -> None:
        """Call after the provider has been loaded."""
        self.logger.info(
            "AES67 Provider loaded with %d stream(s)",
            len(self.players),
        )

    async def unload(self, is_removed: bool = False) -> None:
        """
        Handle unload/close of the provider.

        :param is_removed: Whether the provider is being removed
        """
        self.logger.info("Unloading AES67 Provider")

        # Stop and unregister all players
        for player in list(self.players):
            await player.stop()
            await self.mass.players.unregister(player.player_id)

    async def on_mdns_service_state_change(
        self, name: str, state_change: ServiceStateChange, info: AsyncServiceInfo | None
    ) -> None:
        """
        Handle MDNS service state callback.

        AES67 uses SAP/SDP for discovery, not mDNS, so this is not used.
        """
