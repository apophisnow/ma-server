"""AES67 Virtual Player - represents a multicast audio stream."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from music_assistant_models.enums import ContentType, PlaybackState, PlayerType
from music_assistant_models.media_items import AudioFormat
from music_assistant_models.player import DeviceInfo

from music_assistant.models.player import Player, PlayerMedia

from .constants import (
    AES67_PTIME_MS_DEFAULT,
    RTP_PAYLOAD_TYPE_L16,
    RTP_PAYLOAD_TYPE_L24,
)
from .rtcp_sender import RTCPSender
from .rtp_sender import RTPSender
from .sap_announcer import SAPAnnouncer

if TYPE_CHECKING:
    from .provider import AES67Provider


class AES67Player(Player):
    """
    AES67 Virtual Player in Music Assistant.

    Represents a single AES67 multicast stream. Each player is a virtual output
    that streams audio to a multicast group where multiple AES67/RAVENNA/Dante
    receivers can listen.
    """

    def __init__(
        self,
        provider: AES67Provider,
        player_id: str,
        stream_config: dict[str, Any],
    ) -> None:
        """
        Initialize AES67 Player.

        :param provider: AES67 provider instance
        :param player_id: Unique player ID
        :param stream_config: Stream configuration dictionary
        """
        super().__init__(provider, player_id)

        # Extract stream configuration
        self.stream_name = stream_config["stream_name"]
        self.multicast_address = stream_config["multicast_address"]
        self.rtp_port = stream_config["rtp_port"]
        self.sample_rate = stream_config["sample_rate"]
        self.bit_depth = stream_config["bit_depth"]
        self.channels = stream_config["channels"]
        self.ttl = stream_config["ttl"]
        self.dscp = stream_config["dscp"]
        self.enable_sap = stream_config["enable_sap"]

        # Player attributes
        self._attr_name = self.stream_name
        self._attr_type = PlayerType.PLAYER
        self._attr_supported_features = set()  # AES67 is send-only

        # Device info
        self._attr_device_info = DeviceInfo(
            model="AES67 Multicast Stream",
            manufacturer="Music Assistant",
            ip_address=self.multicast_address,
        )

        # RTP/RTCP/SAP components
        self.rtp_sender: RTPSender | None = None
        self.rtcp_sender: RTCPSender | None = None
        self.sap_announcer: SAPAnnouncer | None = None

        # Streaming state
        self._stream_task: asyncio.Task[None] | None = None
        self._streaming = False

        self._set_initial_state()

    def _set_initial_state(self) -> None:
        """Set initial player state."""
        self._attr_powered = True  # Virtual player is always "on"
        self._attr_volume_level = 100  # Volume controlled at receivers
        self._attr_volume_muted = False
        self._attr_playback_state = PlaybackState.IDLE

    @property
    def needs_poll(self) -> bool:
        """AES67 virtual player doesn't need polling."""
        return False

    async def play(self) -> None:
        """
        Resume/start playback.

        For AES67, this resumes streaming to the multicast group.
        """
        if self._attr_playback_state == PlaybackState.PLAYING:
            return  # Already playing

        self.logger.info("Resuming AES67 stream %s", self.display_name)
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def stop(self) -> None:
        """
        Stop playback.

        Stops streaming and cleans up RTP/RTCP/SAP resources.
        """
        self.logger.info("Stopping AES67 stream %s", self.display_name)

        # Stop streaming task
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None

        # Stop RTCP and SAP
        if self.rtcp_sender:
            await self.rtcp_sender.stop_periodic_sender_reports()
            self.rtcp_sender.close_socket()
            self.rtcp_sender = None

        if self.sap_announcer:
            await self.sap_announcer.stop_periodic_announcements()
            self.sap_announcer.close_socket()
            self.sap_announcer = None

        # Close RTP socket
        if self.rtp_sender:
            self.rtp_sender.close_socket()
            self.rtp_sender = None

        self._streaming = False
        self._attr_playback_state = PlaybackState.IDLE
        self._attr_current_media = None
        self.update_state()

    async def pause(self) -> None:
        """Pause playback - not applicable for multicast streams."""
        # AES67 multicast streams don't really "pause"
        # We could stop sending packets, but that's effectively a stop
        await self.stop()

    async def play_media(self, media: PlayerMedia) -> None:
        """
        Start playing media via RTP multicast.

        :param media: Media information with URI to stream
        """
        self.logger.info(
            "Starting AES67 stream %s to %s:%d",
            self.display_name,
            self.multicast_address,
            self.rtp_port,
        )

        # Stop any existing stream
        if self._streaming:
            await self.stop()

        # Determine RTP payload type based on bit depth
        payload_type = RTP_PAYLOAD_TYPE_L24 if self.bit_depth == 24 else RTP_PAYLOAD_TYPE_L16

        # Create RTP sender
        self.rtp_sender = RTPSender(
            multicast_group=self.multicast_address,
            rtp_port=self.rtp_port,
            payload_type=payload_type,
            sample_rate=self.sample_rate,
            channels=self.channels,
            bit_depth=self.bit_depth,
            logger=self.logger,
            ttl=self.ttl,
            dscp=self.dscp,
        )
        self.rtp_sender.create_socket()

        # Create RTCP sender for timing synchronization
        self.rtcp_sender = RTCPSender(
            rtp_sender=self.rtp_sender,
            logger=self.logger,
        )
        self.rtcp_sender.create_socket()
        await self.rtcp_sender.start_periodic_sender_reports()

        # Create SAP announcer if enabled
        if self.enable_sap:
            # Get server IP address
            server_ip = self.provider.mass.streams.bind_ip

            self.sap_announcer = SAPAnnouncer(
                rtp_sender=self.rtp_sender,
                stream_name=self.stream_name,
                logger=self.logger,
                originator_address=server_ip,
            )
            self.sap_announcer.create_socket()
            await self.sap_announcer.start_periodic_announcements()

        # Update player state
        self._attr_current_media = media
        self._attr_playback_state = PlaybackState.PLAYING
        self._streaming = True
        self.update_state()

        # Start streaming audio
        self._stream_task = asyncio.create_task(self._stream_audio(media.uri))

    async def _stream_audio(self, uri: str) -> None:
        """
        Stream audio from MA to RTP multicast.

        :param uri: Audio stream URI from Music Assistant
        """
        try:
            # Calculate samples per packet based on ptime
            samples_per_packet = int((AES67_PTIME_MS_DEFAULT / 1000.0) * self.sample_rate)

            # Calculate bytes per packet
            bytes_per_sample = self.channels * (self.bit_depth // 8)
            bytes_per_packet = samples_per_packet * bytes_per_sample

            self.logger.debug(
                "Streaming audio: %d samples/packet, %d bytes/packet",
                samples_per_packet,
                bytes_per_packet,
            )

            # Get audio stream from Music Assistant
            # We request PCM audio in the format needed for AES67
            content_type = ContentType.PCM_S24LE if self.bit_depth == 24 else ContentType.PCM_S16LE

            output_format = AudioFormat(
                content_type=content_type,
                sample_rate=self.sample_rate,
                bit_depth=self.bit_depth,
                channels=self.channels,
            )

            # Get the audio stream from the player queue
            queue = self.provider.mass.player_queues.get_active_queue(self.player_id)
            if not queue or not queue.current_item:
                self.logger.error("No active queue or current item for player %s", self.player_id)
                return

            audio_source = self.provider.mass.streams.get_queue_flow_stream(
                queue=queue,
                start_queue_item=queue.current_item,
                pcm_format=output_format,
            )

            # Stream audio packets
            buffer = b""
            async for chunk in audio_source:
                if not self._streaming:
                    break

                buffer += chunk

                # Send complete packets
                while len(buffer) >= bytes_per_packet:
                    packet_data = buffer[:bytes_per_packet]
                    buffer = buffer[bytes_per_packet:]

                    # Send RTP packet
                    if self.rtp_sender:
                        await self.rtp_sender.send_packet_async(packet_data)

            self.logger.info("Audio stream ended for %s", self.display_name)

        except asyncio.CancelledError:
            self.logger.debug("Audio streaming cancelled for %s", self.display_name)
        except Exception as err:
            self.logger.exception("Error streaming audio for %s: %s", self.display_name, err)
        finally:
            # Clean up when stream ends
            if self._streaming:
                await self.stop()

    async def on_unload(self) -> None:
        """Handle cleanup when player is unloaded."""
        await self.stop()
