"""
AES67 Multicast Player Provider for Music Assistant.

Streams audio to professional AES67/RAVENNA/Dante receivers via standards-compliant
IP multicast using RTP/RTCP (RFC 3550) and SAP/SDP (RFC 2974, RFC 4566).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType, ProviderFeature

from .constants import (
    AES67_DEFAULT_BIT_DEPTH,
    AES67_DEFAULT_SAMPLE_RATE,
    AES67_MULTICAST_BASE,
    AES67_RTP_PORT_DEFAULT,
    CONF_BIT_DEPTH,
    CONF_CHANNELS,
    CONF_DSCP,
    CONF_ENABLE_SAP,
    CONF_MULTICAST_ADDRESS,
    CONF_RTP_PORT,
    CONF_SAMPLE_RATE,
    CONF_STREAM_NAME,
    CONF_TTL,
    DSCP_DEFAULT,
    TTL_DEFAULT,
)
from .provider import AES67Provider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType


# No provider-level features since AES67 is send-only
SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    return AES67Provider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """
    Return Config entries to setup this provider.

    :param mass: MusicAssistant instance
    :param instance_id: id of an existing provider instance (None if new instance setup).
    :param action: [optional] action key called from config entries UI.
    :param values: the (intermediate) raw values for config entries sent with the action.
    """
    # ruff: noqa: ARG001

    # Calculate defaults for new instances based on existing AES67 providers
    default_name = "AES67 Stream"
    default_address = AES67_MULTICAST_BASE

    if instance_id is None:
        # This is a new instance - calculate next available defaults
        existing_instances = [
            provider for provider in mass.providers if provider.manifest.domain == "aes67"
        ]

        if existing_instances:
            instance_count = len(existing_instances) + 1
            default_name = f"AES67 Stream {instance_count}"

            # Increment the last octet of the multicast address
            base_parts = AES67_MULTICAST_BASE.split(".")
            last_octet = int(base_parts[3]) + len(existing_instances)
            # Wrap around if we exceed 255
            if last_octet > 255:
                last_octet = last_octet % 256
            default_address = f"{base_parts[0]}.{base_parts[1]}.{base_parts[2]}.{last_octet}"

    return (
        ConfigEntry(
            key=CONF_STREAM_NAME,
            type=ConfigEntryType.STRING,
            label="Stream Name",
            description="Name for this AES67 stream (will appear as a player in Music Assistant)",
            default_value=default_name,
            required=True,
        ),
        ConfigEntry(
            key=CONF_MULTICAST_ADDRESS,
            type=ConfigEntryType.STRING,
            label="Multicast Address",
            description="IPv4 multicast address (239.69.x.x recommended)",
            default_value=default_address,
            required=True,
        ),
        ConfigEntry(
            key=CONF_RTP_PORT,
            type=ConfigEntryType.INTEGER,
            label="RTP Port",
            description="UDP port for audio stream (recommended range: 5004-5127)",
            default_value=AES67_RTP_PORT_DEFAULT,
            required=False,
            category="advanced",
        ),
        ConfigEntry(
            key=CONF_SAMPLE_RATE,
            type=ConfigEntryType.INTEGER,
            label="Sample Rate (Hz)",
            description="Audio sample rate (48000 Hz recommended)",
            default_value=AES67_DEFAULT_SAMPLE_RATE,
            required=False,
            category="advanced",
        ),
        ConfigEntry(
            key=CONF_BIT_DEPTH,
            type=ConfigEntryType.INTEGER,
            label="Bit Depth",
            description="Audio bit depth - 16 or 24 bits (24-bit recommended)",
            default_value=AES67_DEFAULT_BIT_DEPTH,
            required=False,
            category="advanced",
        ),
        ConfigEntry(
            key=CONF_CHANNELS,
            type=ConfigEntryType.INTEGER,
            label="Channels",
            description="Number of audio channels (2 for stereo)",
            default_value=2,
            required=False,
            category="advanced",
        ),
        ConfigEntry(
            key=CONF_TTL,
            type=ConfigEntryType.INTEGER,
            label="Multicast TTL",
            description="Time-to-live for multicast packets",
            default_value=TTL_DEFAULT,
            required=False,
            category="advanced",
        ),
        ConfigEntry(
            key=CONF_DSCP,
            type=ConfigEntryType.INTEGER,
            label="DSCP (QoS)",
            description="Quality of Service priority marking (34=high priority recommended)",
            default_value=DSCP_DEFAULT,
            required=False,
            category="advanced",
        ),
        ConfigEntry(
            key=CONF_ENABLE_SAP,
            type=ConfigEntryType.BOOLEAN,
            label="Enable Stream Announcements",
            description="Broadcast stream info for automatic discovery by receivers (SAP/SDP)",
            default_value=True,
            required=False,
            category="advanced",
        ),
    )
