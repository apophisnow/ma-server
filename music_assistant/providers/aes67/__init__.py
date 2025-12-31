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
    CONF_MULTICAST_STREAMS,
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
    return (
        ConfigEntry(
            key=CONF_MULTICAST_STREAMS,
            type=ConfigEntryType.STRING,
            label="AES67 Multicast Streams",
            description=(
                "Configure one or more AES67 multicast audio streams.\n\n"
                "Each stream will appear as a virtual player in Music Assistant.\n"
                "Multiple AES67/RAVENNA/Dante receivers can listen to each stream.\n\n"
                "**Configuration Format (JSON array):**\n"
                "```json\n"
                "[\n"
                "  {\n"
                '    "stream_name": "Main Audio",\n'
                '    "multicast_address": "239.69.83.1",\n'
                '    "rtp_port": 5004,\n'
                '    "sample_rate": 48000,\n'
                '    "bit_depth": 24,\n'
                '    "channels": 2,\n'
                '    "ttl": 32,\n'
                '    "dscp": 34,\n'
                '    "enable_sap": true\n'
                "  }\n"
                "]\n"
                "```\n\n"
                "**Parameters:**\n"
                "- `stream_name`: Human-readable name (appears in MA)\n"
                "- `multicast_address`: IPv4 multicast (239.69.x.x recommended)\n"
                "- `rtp_port`: RTP port (5004-5127 recommended, RTCP uses port+1)\n"
                "- `sample_rate`: 44100, 48000, 88200, or 96000 Hz\n"
                "- `bit_depth`: 16 or 24 bits\n"
                "- `channels`: 2 for stereo (multichannel not yet supported)\n"
                "- `ttl`: Multicast TTL (1=subnet, 32=site, 255=global)\n"
                "- `dscp`: QoS marking (34=Expedited Forwarding)\n"
                "- `enable_sap`: Enable SAP/SDP announcements for discovery\n\n"
                "**Example Configurations:**\n\n"
                "*Single stereo stream:*\n"
                f'`[{{"stream_name": "Studio A", '
                f'"multicast_address": "{AES67_MULTICAST_BASE}"}}]`\n\n'
                "*Multiple streams:*\n"
                "```json\n"
                "[\n"
                '  {"stream_name": "Zone 1", "multicast_address": "239.69.83.1"},\n'
                '  {"stream_name": "Zone 2", "multicast_address": "239.69.83.2"}\n'
                "]\n"
                "```"
            ),
            default_value=(
                f'[{{"stream_name": "AES67 Stream 1", '
                f'"multicast_address": "{AES67_MULTICAST_BASE}", '
                f'"rtp_port": {AES67_RTP_PORT_DEFAULT}, '
                f'"sample_rate": {AES67_DEFAULT_SAMPLE_RATE}, '
                f'"bit_depth": {AES67_DEFAULT_BIT_DEPTH}, '
                f'"channels": 2, '
                f'"ttl": {TTL_DEFAULT}, '
                f'"dscp": {DSCP_DEFAULT}, '
                f'"enable_sap": true'
                "}]"
            ),
            required=True,
            multi_value=False,
        ),
        ConfigEntry(
            key="info_network_requirements",
            type=ConfigEntryType.LABEL,
            label="Network Requirements",
            description=(
                "**Important Network Configuration:**\n\n"
                "AES67 requires a properly configured network:\n\n"
                "1. **Multicast-capable switches** with IGMP snooping enabled\n"
                "2. **PTP (IEEE 1588) clock synchronization** for sample-accurate sync\n"
                "3. **Quality of Service (QoS)** configuration to prioritize audio traffic\n"
                "4. **Dedicated VLAN** recommended for professional installations\n\n"
                "**Compatible Receivers:**\n"
                "- AES67-compliant hardware (any manufacturer)\n"
                "- RAVENNA devices (fully AES67-compatible)\n"
                "- Dante devices (enable AES67 mode in Dante Controller)\n"
                "- Livewire+, Q-SYS, WHEATNet-IP, Merging+ANUBIS\n\n"
                "**Not recommended for:**\n"
                "- Home consumer routers (usually lack multicast support)\n"
                "- Wireless networks (unreliable for professional audio)\n"
                "- Networks without managed switches"
            ),
            category="advanced",
        ),
        ConfigEntry(
            key="info_standards_compliance",
            type=ConfigEntryType.LABEL,
            label="Standards Compliance",
            description=(
                "**This provider implements:**\n\n"
                "- **AES67-2018** - High-performance streaming audio-over-IP\n"
                "- **RFC 3550** - RTP (Real-time Transport Protocol)\n"
                "- **RFC 3551** - RTP Audio/Video Profile\n"
                "- **RFC 2974** - SAP (Session Announcement Protocol)\n"
                "- **RFC 4566** - SDP (Session Description Protocol)\n"
                "- **IEEE 1588-2008** - PTP reference (receivers provide clock)\n\n"
                "All implementations follow published standards with no\n"
                "proprietary protocols or vendor lock-in."
            ),
            category="advanced",
        ),
    )
