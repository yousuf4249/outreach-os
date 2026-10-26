"""Secure file attachment storage service for Weblinx Outreach OS.

Supports local disk storage with strict path traversal validation,
safe file sanitization, and structured directory organization.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("quickly.attachment_storage")

# Default base directory for storing attachments
BASE_STORAGE_DIR = Path(os.environ.get("ATTACHMENT_STORAGE_DIR", "data/attachments")).resolve()


def _sanitize_filename(name: Optional[str]) -> str:
    """Sanitize filename to prevent directory traversal or filesystem issues."""
    if not name:
        return "attachment.bin"
    # Strip any directory path components
    base = os.path.basename(name.replace("\\", "/"))
    # Replace dangerous or whitespace characters
    clean = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    if not clean or clean.startswith("."):
        clean = f"file_{clean}"
    return clean[:128]


class AttachmentStorageService:
    """Handles saving, retrieving, and deleting email attachments securely."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = (base_dir or BASE_STORAGE_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_attachment(
        self,
        inbox_id: int,
        filename: Optional[str],
        content_type: Optional[str],
        data: bytes,
    ) -> Tuple[str, str, int]:
        """Save attachment bytes to disk.

        Returns (storage_type, storage_path, size_bytes).
        """
        now = datetime.utcnow()
        safe_name = _sanitize_filename(filename)
        file_uuid = uuid.uuid4().hex[:12]
        stored_name = f"{file_uuid}_{safe_name}"

        # Subdirectory by inbox_id and YYYY/MM
        sub_dir = self.base_dir / str(inbox_id) / now.strftime("%Y/%m")
        sub_dir.mkdir(parents=True, exist_ok=True)

        target_path = sub_dir / stored_name
        # Path traversal guard
        if not target_path.resolve().is_relative_to(self.base_dir):
            raise ValueError("Invalid attachment target path: traversal detected")

        target_path.write_bytes(data)
        size_bytes = len(data)

        # Store relative path so storage is portable across filesystem mounts
        rel_path = str(target_path.relative_to(self.base_dir)).replace("\\", "/")
        return "local", rel_path, size_bytes

    def get_attachment_path(self, rel_storage_path: str) -> Optional[Path]:
        """Resolve and validate a relative storage path."""
        if not rel_storage_path:
            return None
        candidate = (self.base_dir / rel_storage_path).resolve()
        if not candidate.is_relative_to(self.base_dir):
            log.warning("Security alert: path traversal attempt on attachment: %s", rel_storage_path)
            return None
        if not candidate.is_file():
            return None
        return candidate

    def delete_attachment(self, rel_storage_path: str) -> bool:
        """Delete an attachment file from disk."""
        target = self.get_attachment_path(rel_storage_path)
        if target and target.is_file():
            try:
                target.unlink()
                return True
            except Exception as e:
                log.warning("Failed to delete attachment %s: %s", rel_storage_path, e)
        return False


attachment_storage = AttachmentStorageService()
