"""RTCP (RTP Control Protocol) sender implementation following RFC 3550."""

from __future__ import annotations

import asyncio
import socket
import struct
from contextlib import suppress
from typing import TYPE_CHECKING

from .constants import RTCP_SR_INTERVAL

if TYPE_CHECKING:
    from logging import Logger

    from .rtp_sender import RTPSender


class RTCPSender:
    """RTCP Sender Report generator for timing synchronization (RFC 3550 Section 6.4)."""

    def __init__(
        self,
        rtp_sender: RTPSender,
        logger: Logger,
    ) -> None:
        """
        Initialize RTCP sender.

        :param rtp_sender: Associated RTP sender
        :param logger: Logger instance
        """
        self.rtp_sender = rtp_sender
        self.logger = logger
        self.socket: socket.socket | None = None
        self._sr_task: asyncio.Task[None] | None = None
        self._running = False

    def create_socket(self) -> None:
        """Create and configure multicast UDP socket for RTCP."""
        # RTCP port is always RTP port + 1 (RFC 3550 Section 11)
        rtcp_port = self.rtp_sender.rtp_port + 1

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        # Set socket to non-blocking mode to prevent event loop blocking
        self.socket.setblocking(False)

        # Use same TTL and DSCP as RTP
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.rtp_sender.ttl)

        tos_value = self.rtp_sender.dscp << 2
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos_value)

        # Allow address reuse
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.logger.info(
            "Created RTCP socket for %s:%d (non-blocking)",
            self.rtp_sender.multicast_group,
            rtcp_port,
        )

    def close_socket(self) -> None:
        """Close the RTCP socket."""
        if self.socket:
            self.socket.close()
            self.socket = None
            self.logger.debug("Closed RTCP socket")

    def _create_sender_report(self) -> bytes:
        """
        Create RTCP Sender Report (SR) packet (RFC 3550 Section 6.4.1).

        SR Packet format:
         0                   1                   2                   3
         0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |V=2|P|    RC   |   PT=SR=200   |             length            |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                         SSRC of sender                        |
        +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+
        |              NTP timestamp, most significant word             |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |             NTP timestamp, least significant word             |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                         RTP timestamp                         |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                     sender's packet count                     |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                      sender's octet count                     |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

        :return: RTCP SR packet bytes
        """
        # Get atomic snapshot of RTP state
        # This ensures NTP time and RTP timestamp are consistent (RFC 3550 requirement)
        # The RTP timestamp must correspond to the sampling instant at the NTP time
        ntp_timestamp, rtp_timestamp, packet_count, octet_count = (
            self.rtp_sender.get_rtcp_snapshot()
        )

        # Split NTP timestamp into MSW and LSW
        ntp_msw = (ntp_timestamp >> 32) & 0xFFFFFFFF  # Most significant word
        ntp_lsw = ntp_timestamp & 0xFFFFFFFF  # Least significant word

        # RTCP Header
        # V=2, P=0, RC=0 (no reception report blocks)
        version_p_rc = (2 << 6) | 0x00

        # PT=200 (SR - Sender Report)
        packet_type = 200

        # Length in 32-bit words minus 1
        # SR without reception reports: 6 words (24 bytes) + 1 word header = 7 words total
        # Length field = 7 - 1 = 6
        length = 6

        # Pack the SR packet
        return struct.pack(
            "!BBHIIIIII",
            version_p_rc,  # V, P, RC
            packet_type,  # PT=200
            length,  # Length
            self.rtp_sender.ssrc,  # SSRC of sender
            ntp_msw,  # NTP timestamp MSW
            ntp_lsw,  # NTP timestamp LSW
            rtp_timestamp & 0xFFFFFFFF,  # RTP timestamp (derived from NTP time)
            packet_count & 0xFFFFFFFF,  # Sender's packet count (snapshot)
            octet_count & 0xFFFFFFFF,  # Sender's octet count (snapshot)
        )

    def send_sender_report(self) -> None:
        """Send RTCP Sender Report."""
        if not self.socket:
            raise RuntimeError("Socket not created. Call create_socket() first.")

        # RTCP port is always RTP port + 1
        rtcp_port = self.rtp_sender.rtp_port + 1

        # Get snapshot for logging (matches what's in the SR)
        _, rtp_ts, pkt_count, oct_count = self.rtp_sender.get_rtcp_snapshot()

        # Create and send SR packet
        try:
            self.socket.sendto(
                self._create_sender_report(), (self.rtp_sender.multicast_group, rtcp_port)
            )
            self.logger.debug(
                "Sent RTCP SR: RTP_TS=%d, PKT_COUNT=%d, OCTET_COUNT=%d",
                rtp_ts,
                pkt_count,
                oct_count,
            )
        except OSError as err:
            self.logger.error("Failed to send RTCP SR: %s", err)

    async def send_sender_report_async(self) -> None:
        """Send RTCP Sender Report asynchronously."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.send_sender_report)

    async def start_periodic_sender_reports(self) -> None:
        """Start periodic RTCP Sender Report transmission."""
        self._running = True
        self._sr_task = asyncio.create_task(self._sr_loop())
        self.logger.info("Started periodic RTCP SR (interval=%ds)", RTCP_SR_INTERVAL)

    async def stop_periodic_sender_reports(self) -> None:
        """Stop periodic RTCP Sender Report transmission."""
        self._running = False
        if self._sr_task and not self._sr_task.done():
            self._sr_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._sr_task
        self._sr_task = None
        self.logger.info("Stopped periodic RTCP SR")

    async def _sr_loop(self) -> None:
        """Periodically send RTCP Sender Reports."""
        try:
            while self._running:
                await self.send_sender_report_async()
                await asyncio.sleep(RTCP_SR_INTERVAL)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            self.logger.exception("Error in RTCP SR loop: %s", err)
