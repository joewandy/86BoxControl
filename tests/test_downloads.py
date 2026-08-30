from pathlib import Path

from retrobridge.downloads import DownloadHistory
from retrobridge.protocol import DownloadStatus


def test_download_history_is_private_atomic_and_bounded(tmp_path: Path) -> None:
    path = tmp_path / "state" / "downloads.json"
    history = DownloadHistory(path, limit=3)
    for index in range(5):
        history.append(DownloadStatus.COMPLETE, f"file-{index}.zip", index, timestamp=100 + index)
    records = history.load()
    assert [item.name for item in records] == ["file-2.zip", "file-3.zip", "file-4.zip"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_suffix(".tmp").exists()


def test_download_history_fails_closed_on_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "downloads.json"
    path.write_text("not json", encoding="utf-8")
    assert DownloadHistory(path).load() == []
