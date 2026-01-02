"""Constants for AES67 Provider following AES67-2018 specification."""

from __future__ import annotations

# AES67 Standard Sample Rates (Section 6.3)
# AES67 requires support for 48kHz, recommends 44.1, 88.2, 96 kHz
AES67_SAMPLE_RATES = [44100, 48000, 88200, 96000]
AES67_DEFAULT_SAMPLE_RATE = 48000

# AES67 Standard Bit Depths (Section 6.3)
# L16 = 16-bit linear PCM, L24 = 24-bit linear PCM
AES67_BIT_DEPTHS = [16, 24]
AES67_DEFAULT_BIT_DEPTH = 24

# RTP Payload Types (RFC 3551 + Dynamic)
# 96-127 are dynamic payload types for non-standard formats
RTP_PAYLOAD_TYPE_L16_STEREO = 10  # L16/48000/2 (if using 48kHz stereo)
RTP_PAYLOAD_TYPE_L24 = 96  # Dynamic payload type for L24
RTP_PAYLOAD_TYPE_L16 = 97  # Dynamic payload type for L16 at non-standard rates

# RTP/RTCP Ports (Section 7.2)
# AES67 recommends using ports in range 5004-5127 for RTP
AES67_RTP_PORT_DEFAULT = 5004
AES67_RTCP_PORT_DEFAULT = 5005  # Always RTP port + 1

# Multicast Address Ranges (Section 7.1)
# AES67 uses IPv4 multicast in range 239.0.0.0/8 (organization-local scope)
# Recommended: 239.69.0.0/16 for AES67 streams
AES67_MULTICAST_BASE = "239.69.83.1"  # Base address for auto-assignment
AES67_MULTICAST_RANGE_START = "239.69.0.1"
AES67_MULTICAST_RANGE_END = "239.69.255.255"

# SAP (Session Announcement Protocol) - RFC 2974
SAP_MULTICAST_ADDR_IPV4 = "239.255.255.255"  # Global SAP address
SAP_MULTICAST_ADDR_IPV6 = "ff0e::2:7ffe"  # Global SAP address for IPv6
SAP_PORT = 9875
SAP_ANNOUNCE_INTERVAL = 30  # Seconds between announcements

# RTCP Sender Report Interval (RFC 3550)
RTCP_SR_INTERVAL = 5.0  # Seconds between RTCP Sender Reports

# PTP (Precision Time Protocol) - IEEE 1588-2008
# AES67 requires PTP for synchronization
PTP_DOMAIN = 0  # Default PTP domain
PTP_MULTICAST_EVENT_ADDR = "224.0.1.129"  # PTP event messages
PTP_MULTICAST_GENERAL_ADDR = "224.0.1.130"  # PTP general messages

# RTP Packet Configuration
RTP_VERSION = 2
RTP_HEADER_SIZE = 12  # bytes
RTP_MAX_PACKET_SIZE = 1400  # Safe MTU size for Ethernet
RTP_TIMESTAMP_RATE_MULTIPLIER = 1  # Timestamp increments by sample count

# Audio Ptime (Packet Time) - Section 6.4
# AES67 recommends 1ms packet time for low latency
# Valid values: 0.125, 0.25, 0.333, 0.5, 1, 2, 4 ms
AES67_PTIME_MS_DEFAULT = 1.0
AES67_PTIME_OPTIONS = [0.125, 0.25, 0.333, 0.5, 1.0, 2.0, 4.0]

# Configuration Keys
CONF_STREAM_NAME = "stream_name"
CONF_MULTICAST_ADDRESS = "multicast_address"
CONF_RTP_PORT = "rtp_port"
CONF_SAMPLE_RATE = "sample_rate"
CONF_BIT_DEPTH = "bit_depth"
CONF_CHANNELS = "channels"
CONF_PTIME = "ptime_ms"
CONF_ENABLE_SAP = "enable_sap"
CONF_TTL = "ttl"
CONF_DSCP = "dscp"

# DSCP (Differentiated Services Code Point) for QoS
# AES67 Section 7.3 recommends DSCP 34 (EF - Expedited Forwarding) for audio
DSCP_DEFAULT = 34  # EF (Expedited Forwarding) - RFC 3246
DSCP_OPTIONS = {
    "best_effort": 0,  # BE - Default/best effort
    "expedited_forwarding": 34,  # EF - Low latency
    "assured_forwarding_41": 34,  # AF41 - High priority
}

# Multicast TTL (Time To Live)
TTL_DEFAULT = 32  # Reasonable default for local network
TTL_LINK_LOCAL = 1  # Same subnet only
TTL_SITE_LOCAL = 32  # Organization
TTL_GLOBAL = 255  # Internet-wide (use with caution)
