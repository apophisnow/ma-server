"""Tests for filesystem library sync behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from music_assistant_models.enums import MediaType

from music_assistant.providers.filesystem_local import LocalFileSystemProvider
from music_assistant.providers.filesystem_local.helpers import FileSystemItem


def _make_file_item(relative_path: str, checksum: str = "100") -> FileSystemItem:
    """Create a FileSystemItem for testing."""
    return FileSystemItem(
        filename=relative_path.rsplit("/", 1)[-1],
        relative_path=relative_path,
        absolute_path=f"/mnt/music/{relative_path}",
        is_dir=False,
        checksum=checksum,
        file_size=1000,
    )


def _create_provider(
    base_path: str = "/mnt/music",
    media_content_type: str = "music",
) -> MagicMock:
    """Create a mocked LocalFileSystemProvider with the sync_library method.

    We bind the real sync_library to a mock so we test the actual sync logic
    without needing a full MusicAssistant instance.
    """
    mock_mass = MagicMock()
    mock_mass.music.database.get_rows_from_query = AsyncMock(return_value=[])
    mock_mass.create_task = lambda coro: __import__("asyncio").get_event_loop().create_task(coro)

    provider = MagicMock(spec=LocalFileSystemProvider)
    provider.mass = mock_mass
    provider.base_path = base_path
    provider.name = "test_filesystem"
    provider.instance_id = "test_instance"
    provider.media_content_type = media_content_type
    provider.sync_running = False
    provider.config = MagicMock()
    provider.config.get_value = MagicMock(return_value=False)
    provider.logger = MagicMock()
    provider.logger.isEnabledFor = MagicMock(return_value=False)

    # Bind the real sync_library and _process_item_async methods
    provider.sync_library = LocalFileSystemProvider.sync_library.__get__(provider)
    provider._process_item_async = LocalFileSystemProvider._process_item_async.__get__(provider)
    provider._process_deletions = AsyncMock()
    provider._process_orphaned_albums_and_artists = AsyncMock()

    return provider


@pytest.mark.asyncio
async def test_failed_processing_does_not_cause_deletion() -> None:
    """Test that files which fail processing are not treated as deleted.

    Regression test: when _process_item_async raises an exception (e.g. transient
    I/O error on SMB/NFS mount), the file should still be considered present so
    it is not removed from the library. It will be retried on the next sync.
    """
    existing_files = [
        {"provider_item_id": "Artist/Album/track1.mp3", "details": "50"},
        {"provider_item_id": "Artist/Album/track2.mp3", "details": "50"},
        {"provider_item_id": "Artist/Album/track3.mp3", "details": "50"},
    ]

    # All 3 files are still on disk but with a new checksum (changed)
    disk_files = [
        _make_file_item("Artist/Album/track1.mp3", checksum="100"),
        _make_file_item("Artist/Album/track2.mp3", checksum="100"),
        _make_file_item("Artist/Album/track3.mp3", checksum="100"),
    ]

    provider = _create_provider()
    provider.mass.music.database.get_rows_from_query = AsyncMock(return_value=existing_files)

    # Make _process_item_async fail for track2 (simulates transient I/O error)
    async def _process_with_failure(item: FileSystemItem, _prev_checksum: str | None) -> bool:
        if "track2" in item.relative_path:
            raise OSError("Connection timed out")
        return True

    provider._process_item_async = _process_with_failure

    with patch(
        "music_assistant.providers.filesystem_local.recursive_iter",
        return_value=iter(disk_files),
    ):
        await provider.sync_library(MediaType.TRACK)

    # The critical assertion: _process_deletions should be called with an EMPTY set.
    # Even though track2 failed processing, it should NOT be in the deleted set
    # because it still exists on disk.
    provider._process_deletions.assert_awaited_once()
    deleted_files = provider._process_deletions.call_args[0][0]
    assert deleted_files == set(), (
        f"Files should not be deleted due to processing failure, but got: {deleted_files}"
    )


@pytest.mark.asyncio
async def test_actually_deleted_files_are_detected() -> None:
    """Test that files genuinely removed from disk are still detected as deleted."""
    existing_files = [
        {"provider_item_id": "Artist/Album/track1.mp3", "details": "50"},
        {"provider_item_id": "Artist/Album/track2.mp3", "details": "50"},
        {"provider_item_id": "Artist/Album/track3.mp3", "details": "50"},
    ]

    # Only 2 files remain on disk (track3 was deleted), both unchanged
    disk_files = [
        _make_file_item("Artist/Album/track1.mp3", checksum="50"),
        _make_file_item("Artist/Album/track2.mp3", checksum="50"),
    ]

    provider = _create_provider()
    provider.mass.music.database.get_rows_from_query = AsyncMock(return_value=existing_files)

    with patch(
        "music_assistant.providers.filesystem_local.recursive_iter",
        return_value=iter(disk_files),
    ):
        await provider.sync_library(MediaType.TRACK)

    # track3 should be detected as deleted
    provider._process_deletions.assert_awaited_once()
    deleted_files = provider._process_deletions.call_args[0][0]
    assert deleted_files == {"Artist/Album/track3.mp3"}


@pytest.mark.asyncio
async def test_unchanged_files_not_reprocessed() -> None:
    """Test that files with matching checksums are not reprocessed."""
    existing_files = [
        {"provider_item_id": "Artist/Album/track1.mp3", "details": "100"},
        {"provider_item_id": "Artist/Album/track2.mp3", "details": "100"},
    ]

    # Same checksums as database - files are unchanged
    disk_files = [
        _make_file_item("Artist/Album/track1.mp3", checksum="100"),
        _make_file_item("Artist/Album/track2.mp3", checksum="100"),
    ]

    provider = _create_provider()
    provider.mass.music.database.get_rows_from_query = AsyncMock(return_value=existing_files)

    # _process_item_async should NOT be called for unchanged files
    process_mock = AsyncMock(return_value=True)
    provider._process_item_async = process_mock

    with patch(
        "music_assistant.providers.filesystem_local.recursive_iter",
        return_value=iter(disk_files),
    ):
        await provider.sync_library(MediaType.TRACK)

    # No items should have been processed
    process_mock.assert_not_awaited()

    # No deletions should have occurred
    provider._process_deletions.assert_awaited_once()
    deleted_files = provider._process_deletions.call_args[0][0]
    assert deleted_files == set()
