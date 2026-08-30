"""Private, bounded download history for the managed renderer."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .protocol import DownloadRecord, DownloadStatus, MAX_DOWNLOAD_HISTORY
from .runtime import APP_SUPPORT

DOWNLOAD_HISTORY_FILE = APP_SUPPORT / "downloads.json"


class DownloadHistory:
    def __init__(self, path: Path = DOWNLOAD_HISTORY_FILE, limit: int = MAX_DOWNLOAD_HISTORY):
        if limit <= 0 or limit > MAX_DOWNLOAD_HISTORY:
            raise ValueError("download history limit is invalid")
        self.path = path
        self.limit = limit

    def load(self) -> list[DownloadRecord]:
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        records: list[DownloadRecord] = []
        for item in raw[-self.limit :]:
            try:
                if not isinstance(item, dict):
                    continue
                status = DownloadStatus(int(item["status"]))
                timestamp = int(item["timestamp"])
                size = int(item["size"])
                name = str(item["name"])
                if not (0 <= timestamp <= 0xFFFFFFFF and 0 <= size <= 0xFFFFFFFF):
                    continue
                if not name or len(name.encode("cp1252", "replace")) > 180:
                    continue
                records.append(DownloadRecord(status, timestamp, size, name))
            except (KeyError, TypeError, ValueError):
                continue
        return records

    def append(
        self,
        status: DownloadStatus,
        name: str,
        size: int = 0,
        *,
        timestamp: int | None = None,
    ) -> DownloadRecord:
        record = DownloadRecord(
            status=status,
            timestamp=int(time.time()) if timestamp is None else timestamp,
            size=size,
            name=name,
        )
        records = (self.load() + [record])[-self.limit :]
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([asdict(item) for item in records], indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, self.path)
        return record
