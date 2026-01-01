"""AES67 Multicast Provider implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from music_assistant.models.player_provider import PlayerProvider

from .constants import (
    CONF_BIT_DEPTH,
    CONF_CHANNELS,
    CONF_DSCP,
    CONF_ENABLE_SAP,
    CONF_MULTICAST_ADDRESS,
    CONF_RTP_PORT,
    CONF_SAMPLE_RATE,
    CONF_STREAM_NAME,
    CONF_TTL,
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

    @property
    def instance_name_postfix(self) -> str | None:
        """Return instance name postfix based on the stream name."""
        stream_name = self.config.get_value(CONF_STREAM_NAME)
        return str(stream_name) if stream_name else None

    async def handle_async_init(self) -> None:
        """Handle async initialization of the provider."""
        self.logger.info("Initializing AES67 Multicast Provider")

        # Build stream config from individual config entries
        stream_config: dict[str, Any] = {
            "stream_name": self.config.get_value(CONF_STREAM_NAME),
            "multicast_address": self.config.get_value(CONF_MULTICAST_ADDRESS),
            "rtp_port": self.config.get_value(CONF_RTP_PORT),
            "sample_rate": self.config.get_value(CONF_SAMPLE_RATE),
            "bit_depth": self.config.get_value(CONF_BIT_DEPTH),
            "channels": self.config.get_value(CONF_CHANNELS),
            "ttl": self.config.get_value(CONF_TTL),
            "dscp": self.config.get_value(CONF_DSCP),
            "enable_sap": self.config.get_value(CONF_ENABLE_SAP),
        }

        # Create the AES67 player for this provider instance
        await self._create_stream_player(stream_config)

    async def _create_stream_player(self, stream_config: dict[str, Any]) -> None:
        """
        Create virtual player for a multicast stream.

        :param stream_config: Stream configuration dictionary
        """
        stream_name = stream_config["stream_name"]
        multicast_address = stream_config["multicast_address"]
        rtp_port = stream_config["rtp_port"]

        # Validate multicast address (239.x.x.x range for AES67)
        if not multicast_address.startswith("239."):
            self.logger.warning(
                "Stream '%s' multicast address '%s' is not in AES67 recommended range (239.x.x.x)",
                stream_name,
                multicast_address,
            )

        # Create player ID from provider instance ID and multicast address
        player_id = f"{self.instance_id}_{multicast_address.replace('.', '_')}_{rtp_port}"

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
