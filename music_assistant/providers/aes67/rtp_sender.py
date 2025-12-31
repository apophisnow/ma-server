"""RTP (Real-time Transport Protocol) sender implementation following RFC 3550."""

from __future__ import annotations

import asyncio
import random
import socket
import struct
import time
from typing import TYPE_CHECKING

from .constants import (
    DSCP_DEFAULT,
    RTP_VERSION,
    TTL_DEFAULT,
)

if TYPE_CHECKING:
    from logging import Logger


class RTPSender:
    """RTP packet sender for AES67 audio streaming (RFC 3550 compliant)."""

    def __init__(
        self,
        multicast_group: str,
        rtp_port: int,
        payload_type: int,
        sample_rate: int,
        channels: int,
        bit_depth: int,
        logger: Logger,
        ttl: int = TTL_DEFAULT,
        dscp: int = DSCP_DEFAULT,
    ) -> None:
        """
        Initialize RTP sender.

        :param multicast_group: IPv4 multicast address (e.g., "239.69.83.1")
        :param rtp_port: UDP port for RTP packets
        :param payload_type: RTP payload type (96-127 for dynamic)
        :param sample_rate: Audio sample rate in Hz
        :param channels: Number of audio channels
        :param bit_depth: Audio bit depth (16 or 24)
        :param logger: Logger instance
        :param ttl: Multicast TTL (Time To Live)
        :param dscp: DSCP value for QoS marking
        """
        self.multicast_group = multicast_group
        self.rtp_port = rtp_port
        self.payload_type = payload_type
        self.sample_rate = sample_rate
        self.channels = channels
        self.bit_depth = bit_depth
        self.logger = logger
        self.ttl = ttl
        self.dscp = dscp

        # RTP state (RFC 3550 Section 5.1)
        self.sequence_number = random.randint(0, 0xFFFF)  # Random initial sequence
        self.timestamp = random.randint(0, 0xFFFFFFFF)  # Random initial timestamp
        self.ssrc = random.randint(0, 0xFFFFFFFF)  # Synchronization source identifier

        # Statistics for RTCP
        self.packet_count = 0
        self.octet_count = 0
        self.start_time = time.time()

        # Socket
        self.socket: socket.socket | None = None

    def create_socket(self) -> None:
        """Create and configure multicast UDP socket."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        # Set socket options
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl)

        # Set DSCP for QoS (Type of Service field)
        # DSCP is the upper 6 bits of the TOS byte
        tos_value = self.dscp << 2
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos_value)

        # Allow address reuse
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.logger.info(
            "Created RTP socket for %s:%d (TTL=%d, DSCP=%d)",
            self.multicast_group,
            self.rtp_port,
            self.ttl,
            self.dscp,
        )

    def close_socket(self) -> None:
        """Close the multicast socket."""
        if self.socket:
            self.socket.close()
            self.socket = None
            self.logger.debug("Closed RTP socket")

    def _create_rtp_header(self, payload_size: int, marker: bool = False) -> bytes:
        """
        Create RTP header (RFC 3550 Section 5.1).

        RTP Header format (12 bytes):
         0                   1                   2                   3
         0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |V=2|P|X|  CC   |M|     PT      |       sequence number         |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                           timestamp                           |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |           synchronization source (SSRC) identifier            |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

        :param payload_size: Size of RTP payload in bytes
        :param marker: Marker bit (typically False for continuous audio)
        :return: 12-byte RTP header
        """
        # Byte 0: V(2) | P(1) | X(1) | CC(4)
        # V=2 (version 2), P=0 (no padding), X=0 (no extension), CC=0 (no CSRCs)
        byte0 = (RTP_VERSION << 6) | 0x00

        # Byte 1: M(1) | PT(7)
        # M=marker bit, PT=payload type
        byte1 = (int(marker) << 7) | (self.payload_type & 0x7F)

        # Pack the header using big-endian (network byte order)
        return struct.pack(
            "!BBHII",
            byte0,  # V, P, X, CC
            byte1,  # M, PT
            self.sequence_number & 0xFFFF,  # Sequence number (16 bits)
            self.timestamp & 0xFFFFFFFF,  # Timestamp (32 bits)
            self.ssrc,  # SSRC (32 bits)
        )

    def send_packet(self, pcm_data: bytes) -> None:
        """
        Send PCM audio data as RTP packet.

        :param pcm_data: Raw PCM audio data
        """
        if not self.socket:
            raise RuntimeError("Socket not created. Call create_socket() first.")

        # Calculate how many samples this chunk contains
        bytes_per_sample = self.channels * (self.bit_depth // 8)
        samples_in_chunk = len(pcm_data) // bytes_per_sample

        # Create RTP header
        rtp_header = self._create_rtp_header(len(pcm_data))

        # Construct RTP packet
        rtp_packet = rtp_header + pcm_data

        # Send packet
        try:
            self.socket.sendto(rtp_packet, (self.multicast_group, self.rtp_port))

            # Update RTP state
            self.sequence_number = (self.sequence_number + 1) & 0xFFFF
            self.timestamp = (self.timestamp + samples_in_chunk) & 0xFFFFFFFF

            # Update statistics for RTCP
            self.packet_count += 1
            self.octet_count += len(pcm_data)

        except OSError as err:
            self.logger.error("Failed to send RTP packet: %s", err)

    async def send_packet_async(self, pcm_data: bytes) -> None:
        """
        Send RTP packet asynchronously (runs in executor to avoid blocking).

        :param pcm_data: Raw PCM audio data
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.send_packet, pcm_data)

    def get_ntp_timestamp(self) -> int:
        """
        Get current NTP timestamp for RTCP.

        NTP timestamp format: 64-bit value with 32-bit seconds and 32-bit fraction.

        :return: NTP timestamp as 64-bit integer
        """
        # NTP epoch starts Jan 1, 1900
        # Unix epoch starts Jan 1, 1970
        # Difference: 2208988800 seconds
        ntp_epoch_delta = 2208988800

        current_time = time.time()
        ntp_seconds = int(current_time) + ntp_epoch_delta
        ntp_fraction = int((current_time - int(current_time)) * 0xFFFFFFFF)

        # Combine into 64-bit timestamp
        return (ntp_seconds << 32) | ntp_fraction
