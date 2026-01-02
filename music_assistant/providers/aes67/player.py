"""AES67 Player implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from music_assistant_models.enums import ContentType, PlaybackState, PlayerType
from music_assistant_models.media_items import AudioFormat
from music_assistant_models.player import DeviceInfo

from music_assistant.helpers.audio import get_chunksize
from music_assistant.helpers.ffmpeg import FFMpeg
from music_assistant.models.player import Player, PlayerMedia

from .constants import RTP_PAYLOAD_TYPE_L16, RTP_PAYLOAD_TYPE_L24
from .rtcp_sender import RTCPSender
from .rtp_sender import RTPSender
from .sap_announcer import SAPAnnouncer

if TYPE_CHECKING:
    from .provider import AES67Provider


class AES67Player(Player):
    """AES67 multicast virtual player."""

    def __init__(
        self, provider: AES67Provider, player_id: str, stream_config: dict[str, Any]
    ) -> None:
        """Initialize AES67 player.

        :param provider: The AES67 provider instance.
        :param player_id: Unique player identifier.
        :param stream_config: Stream configuration dictionary.
        """
        super().__init__(provider, player_id)

        # Configuration
        self.stream_name: str = stream_config["stream_name"]
        self.multicast_address: str = stream_config["multicast_address"]
        self.rtp_port: int = stream_config["rtp_port"]
        self.sample_rate: int = stream_config["sample_rate"]
        self.bit_depth: int = stream_config["bit_depth"]
        self.channels: int = stream_config["channels"]
        self.ttl: int = stream_config.get("ttl", 64)
        self.dscp: int = stream_config.get("dscp", 0)
        self.enable_sap: bool = stream_config.get("enable_sap", True)

        # Player attributes
        self._attr_name = self.stream_name
        self._attr_type = PlayerType.PLAYER
        self._attr_supported_features = set()
        self._attr_device_info = DeviceInfo(
            model="AES67 Multicast Stream",
            manufacturer="Music Assistant",
            ip_address=self.multicast_address,
        )

        # RTP/RTCP/SAP
        self.rtp_sender: RTPSender | None = None
        self.rtcp_sender: RTCPSender | None = None
        self.sap_announcer: SAPAnnouncer | None = None

        # Streaming
        self._stream_task: asyncio.Task[None] | None = None
        self._streaming = False
        self._set_initial_state()

    def _set_initial_state(self) -> None:
        """Set initial player state attributes."""
        self._attr_powered = True
        self._attr_volume_level = 100
        self._attr_volume_muted = False
        self._attr_playback_state = PlaybackState.IDLE

    @property
    def needs_poll(self) -> bool:
        """Return if player needs polling for state updates."""
        return False

    async def play(self) -> None:
        """Handle PLAY command."""
        if self._attr_playback_state == PlaybackState.PLAYING:
            return
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def stop(self) -> None:
        """Handle STOP command."""
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stream_task
        self._streaming = False
        self._stream_task = None

        # Clean up RTCP sender
        if self.rtcp_sender:
            with suppress(Exception):
                await self.rtcp_sender.stop_periodic_sender_reports()
            with suppress(Exception):
                self.rtcp_sender.close_socket()
            self.rtcp_sender = None

        # Clean up SAP announcer
        if self.sap_announcer:
            with suppress(Exception):
                await self.sap_announcer.stop_periodic_announcements()
            with suppress(Exception):
                self.sap_announcer.close_socket()
            self.sap_announcer = None

        # Clean up RTP sender
        if self.rtp_sender:
            with suppress(Exception):
                self.rtp_sender.close_socket()
            self.rtp_sender = None

        self._attr_playback_state = PlaybackState.IDLE
        self._attr_current_media = None
        self.update_state()

    async def play_media(self, media: PlayerMedia) -> None:
        """Handle PLAY MEDIA command.

        :param media: The media to play.
        """
        self._attr_current_media = media
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stream_task
        self._streaming = False
        self._stream_task = None

        # Setup RTP/RTCP/SAP if not already
        payload_type = RTP_PAYLOAD_TYPE_L24 if self.bit_depth == 24 else RTP_PAYLOAD_TYPE_L16
        if not self.rtp_sender:
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

        if not self.rtcp_sender:
            self.rtcp_sender = RTCPSender(rtp_sender=self.rtp_sender, logger=self.logger)
            self.rtcp_sender.create_socket()
            await self.rtcp_sender.start_periodic_sender_reports()

        if not self.sap_announcer and self.enable_sap:
            server_ip = self.provider.mass.streams.bind_ip
            self.sap_announcer = SAPAnnouncer(
                rtp_sender=self.rtp_sender,
                stream_name=self.stream_name,
                logger=self.logger,
                originator_address=server_ip,
            )
            self.sap_announcer.create_socket()
            await self.sap_announcer.start_periodic_announcements()

        # Prepare the PCM format based on bit depth
        # AES67 requires big-endian (network byte order) as per RFC 3550
        # AES67 only supports 16-bit and 24-bit audio
        if self.bit_depth == 24:
            content_type = ContentType.PCM_S24BE
        elif self.bit_depth == 16:
            content_type = ContentType.PCM_S16BE
        else:
            self.logger.error(
                "Unsupported bit depth %d for AES67 (only 16 and 24-bit supported)",
                self.bit_depth,
            )
            self._attr_playback_state = PlaybackState.IDLE
            self.update_state()
            return

        pcm_format = AudioFormat(
            content_type=content_type,
            sample_rate=self.sample_rate,
            bit_depth=self.bit_depth,
            channels=self.channels,
        )

        # Get the audio stream
        audio_source = self.mass.streams.get_stream(media, pcm_format)

        # Start streaming task with real-time pacing
        self._streaming = True
        self._stream_task = asyncio.create_task(self._streamer(audio_source, pcm_format))

    async def _streamer(
        self,
        audio_source: AsyncGenerator[bytes, None],
        pcm_format: AudioFormat,
    ) -> None:
        """Stream audio via RTP multicast with real-time pacing.

        :param audio_source: Async generator yielding PCM audio chunks.
        :param pcm_format: PCM audio format specification.
        """
        try:
            # Calculate chunk size that aligns with RTP frame boundaries
            # Use small chunks (e.g., 10ms) for low latency RTP streaming
            chunk_size = get_chunksize(pcm_format, seconds=0.01)

            # Use FFMpeg to add real-time pacing (-re flag)
            # This ensures audio is streamed at the correct playback rate
            async with FFMpeg(
                audio_input=audio_source,
                input_format=pcm_format,
                output_format=pcm_format,
                extra_input_args=["-re"],  # Real-time input reading
            ) as ffmpeg_proc:
                # Stream PCM audio chunks to RTP with proper frame alignment
                async for chunk in ffmpeg_proc.iter_chunked(chunk_size):
                    if not self._streaming:
                        break
                    if self.rtp_sender:
                        await self.rtp_sender.send_packet_async(chunk)

            self.logger.info(
                "Finished streaming AES67 audio to %s:%d", self.multicast_address, self.rtp_port
            )

        except asyncio.CancelledError:
            self.logger.debug("AES67 streaming cancelled for %s", self.display_name)
        except Exception as err:
            self.logger.exception("Error streaming AES67 audio: %s", err)
            # Set playback state to IDLE on error
            self._attr_playback_state = PlaybackState.IDLE
            self.update_state()
        finally:
            # Stop everything cleanly
            if self._streaming:
                await self.stop()

    async def on_unload(self) -> None:
        """Handle player unload."""
        await self.stop()
