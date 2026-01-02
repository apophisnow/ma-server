"""SAP/SDP announcer for AES67 stream discovery (RFC 2974, RFC 4566)."""

from __future__ import annotations

import asyncio
import hashlib
import socket
import struct
import time
from contextlib import suppress
from typing import TYPE_CHECKING

from .constants import (
    AES67_PTIME_MS_DEFAULT,
    RTP_PAYLOAD_TYPE_L16,
    RTP_PAYLOAD_TYPE_L24,
    SAP_ANNOUNCE_INTERVAL,
    SAP_MULTICAST_ADDR_IPV4,
    SAP_PORT,
)

if TYPE_CHECKING:
    from logging import Logger

    from .rtp_sender import RTPSender


class SAPAnnouncer:
    """SAP (Session Announcement Protocol) announcer for AES67 stream discovery."""

    def __init__(
        self,
        rtp_sender: RTPSender,
        stream_name: str,
        logger: Logger,
        originator_address: str,
    ) -> None:
        """
        Initialize SAP announcer.

        :param rtp_sender: Associated RTP sender
        :param stream_name: Human-readable stream name
        :param logger: Logger instance
        :param originator_address: IP address of this server
        """
        self.rtp_sender = rtp_sender
        self.stream_name = stream_name
        self.logger = logger
        self.originator_address = originator_address
        self.socket: socket.socket | None = None
        self._announce_task: asyncio.Task[None] | None = None
        self._running = False

        # Generate session ID (RFC 4566 Section 5.2)
        # Use hash of stream name + time for uniqueness
        session_id = int(
            hashlib.sha256(f"{stream_name}{time.time()}".encode()).hexdigest()[:16], 16
        )
        self.session_id = session_id

    def create_socket(self) -> None:
        """Create and configure multicast UDP socket for SAP."""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

            # Use the same TTL as the RTP stream for SAP announcements
            # This ensures SAP announcements propagate to the same network scope as the stream
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.rtp_sender.ttl)

            # Allow address reuse
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # All succeeded, assign to self.socket
            self.socket = sock

            self.logger.info(
                "Created SAP socket for %s:%d (TTL=%d)",
                SAP_MULTICAST_ADDR_IPV4,
                SAP_PORT,
                self.rtp_sender.ttl,
            )
        except OSError as err:
            # Cleanup on failure
            if sock is not None:
                sock.close()
            self.logger.exception("Failed to create SAP socket: %s", err)
            raise

    def close_socket(self) -> None:
        """Close the SAP socket."""
        if self.socket:
            self.socket.close()
            self.socket = None
            self.logger.debug("Closed SAP socket")

    def _generate_sdp(self) -> str:
        """
        Generate SDP (Session Description Protocol) for AES67 stream (RFC 4566).

        Example SDP for AES67:
        v=0
        o=MusicAssistant 3840995837 3840995837 IN IP4 192.168.1.100
        s=Music Assistant Stream 1
        c=IN IP4 239.69.83.1/32
        t=0 0
        m=audio 5004 RTP/AVP 96
        a=rtpmap:96 L24/48000/2
        a=ptime:1
        a=mediaclk:direct=0
        a=ts-refclk:ptp=IEEE1588-2008:00-00-00-00-00-00-00-00:0

        :return: SDP string
        """
        # Determine encoding name based on bit depth
        if self.rtp_sender.bit_depth == 24:
            encoding_name = "L24"
            payload_type = RTP_PAYLOAD_TYPE_L24
        else:  # 16-bit
            encoding_name = "L16"
            payload_type = RTP_PAYLOAD_TYPE_L16

        # Build SDP
        sdp_lines = [
            "v=0",  # Version
            # Origin: o=<username> <sess-id> <sess-version> <nettype> <addrtype> <unicast-address>
            (
                f"o=MusicAssistant {self.session_id} {self.session_id} "
                f"IN IP4 {self.originator_address}"
            ),
            # Session name
            f"s={self.stream_name}",
            # Connection data: c=<nettype> <addrtype> <connection-address>/<ttl>
            f"c=IN IP4 {self.rtp_sender.multicast_group}/{self.rtp_sender.ttl}",
            # Time: t=<start-time> <stop-time> (0 0 = permanent session)
            "t=0 0",
            # Media description: m=<media> <port> <proto> <fmt>
            f"m=audio {self.rtp_sender.rtp_port} RTP/AVP {payload_type}",
            # RTP map: a=rtpmap:<payload type> <encoding name>/<clock rate>/<channels>
            (
                f"a=rtpmap:{payload_type} {encoding_name}/"
                f"{self.rtp_sender.sample_rate}/{self.rtp_sender.channels}"
            ),
            # Packet time (AES67 Section 6.4)
            f"a=ptime:{AES67_PTIME_MS_DEFAULT}",
            # Media clock (AES67 Section 6.3.2)
            "a=mediaclk:direct=0",
            # Timing reference clock - PTP (AES67 Section 6.3.1)
            # For now, use a placeholder PTP clock ID
            # In production, this should be the actual PTP grandmaster clock ID
            "a=ts-refclk:ptp=IEEE1588-2008:00-00-00-00-00-00-00-00:0",
        ]

        return "\r\n".join(sdp_lines) + "\r\n"

    def _create_sap_packet(self, deletion: bool = False) -> bytes:
        """
        Create SAP announcement packet (RFC 2974).

        SAP Header format:
         0                   1                   2                   3
         0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        | V=1 |A|R|T|E|C|   auth len    |         msg id hash           |
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        |                                                               |
        :                originating source (32 or 128 bits)            :
        :                                                               :
        +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

        :param deletion: Set to True to create a deletion announcement (A=1)
        :return: SAP packet bytes
        """
        # SAP Header Byte 0:
        # V=1 (version), A=announcement type (0=announcement, 1=deletion),
        # R=0 (not relayed), T=0 (not encrypted), E=0 (not compressed), C=0 (no payload type)
        version_flags = (1 << 5) | (int(deletion) << 4)  # V=1, A=deletion flag

        # Auth len = 0 (no authentication)
        auth_len = 0

        # Message ID Hash (16-bit)
        # Use hash of multicast address + port for uniqueness
        msg_id_str = f"{self.rtp_sender.multicast_group}:{self.rtp_sender.rtp_port}"
        msg_id_hash = hashlib.sha256(msg_id_str.encode()).digest()[:2]
        msg_id = struct.unpack("!H", msg_id_hash)[0]

        # Originating source (IPv4 address as 32-bit integer)
        orig_source = struct.unpack("!I", socket.inet_aton(self.originator_address))[0]

        # Pack SAP header
        sap_header = struct.pack(
            "!BBH I",
            version_flags,
            auth_len,
            msg_id,
            orig_source,
        )

        # Payload type and content
        # For SDP, we add "application/sdp" MIME type followed by SDP content
        # RFC 2974 Section 5: payload type is optional null-terminated string
        payload_type = b"application/sdp\x00"
        sdp_content = self._generate_sdp().encode("utf-8")

        # Construct full SAP packet
        return sap_header + payload_type + sdp_content

    def send_announcement(self) -> None:
        """Send SAP announcement."""
        if not self.socket:
            raise RuntimeError("Socket not created. Call create_socket() first.")

        # Create and send SAP packet
        sap_packet = self._create_sap_packet()

        try:
            self.socket.sendto(sap_packet, (SAP_MULTICAST_ADDR_IPV4, SAP_PORT))
            self.logger.debug(
                "Sent SAP announcement for %s (%d bytes)",
                self.stream_name,
                len(sap_packet),
            )
        except OSError as err:
            self.logger.exception("Failed to send SAP announcement: %s", err)

    async def send_announcement_async(self) -> None:
        """Send SAP announcement asynchronously."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.send_announcement)

    async def start_periodic_announcements(self) -> None:
        """Start periodic SAP announcements."""
        self._running = True
        self._announce_task = asyncio.create_task(self._announce_loop())
        self.logger.info(
            "Started periodic SAP announcements (interval=%ds)",
            SAP_ANNOUNCE_INTERVAL,
        )

    async def stop_periodic_announcements(self) -> None:
        """Stop periodic SAP announcements."""
        self._running = False
        if self._announce_task and not self._announce_task.done():
            self._announce_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._announce_task
        self._announce_task = None

        # Send deletion announcement (A=1 flag)
        if self.socket:
            await self._send_deletion_announcement()

        self.logger.info("Stopped periodic SAP announcements")

    async def _send_deletion_announcement(self) -> None:
        """Send SAP deletion announcement (A=1 flag)."""
        if not self.socket:
            return

        # Create deletion announcement using the shared packet creation method
        sap_packet = self._create_sap_packet(deletion=True)

        try:
            self.socket.sendto(sap_packet, (SAP_MULTICAST_ADDR_IPV4, SAP_PORT))
            self.logger.debug("Sent SAP deletion announcement for %s", self.stream_name)
        except OSError as err:
            self.logger.exception("Failed to send SAP deletion: %s", err)

    async def _announce_loop(self) -> None:
        """Periodically send SAP announcements."""
        try:
            while self._running:
                await self.send_announcement_async()
                await asyncio.sleep(SAP_ANNOUNCE_INTERVAL)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            self.logger.exception("Error in SAP announcement loop: %s", err)
