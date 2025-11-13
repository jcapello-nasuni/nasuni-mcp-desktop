"""File system utilities."""
from html import parser
from enum import Enum
import logging
import os
from datetime import datetime
try:
    from hachoir.parser import createParser
    from hachoir.metadata import extractMetadata
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    createParser = None
    extractMetadata = None

from .config import Config
from .models import (
    FolderContents,
    FileSystemItem,
    FolderItem,
    FileItem,
    FileMetadata,
    SnapshotList,
    SnapshotSummary,
)

class SizeLimitKind(Enum):
    """Enum for file size limits kinds"""
    READ = "read"
    RETURN = "return"
    NONE = "none"

class FileSystem:
    """
    Represents the file system and provides methods to interact with it.
    """

    def __init__(self, config: Config, log: logging.Logger | None = None):
        self.config = config
        if log is not None:
            self.log = log
        else:
            self.log = logging.getLogger("null")
            self.log.addHandler(logging.NullHandler())

    def folder_contents(
        self,
        relative_path,
        scan_limit: int | None = None,
        snapshot_id: str | None = None,
    ) -> FolderContents:
        """
        Get the contents of a folder.
        """

        if relative_path == "/" or relative_path == "\\":
            relative_path = ""

        scan_first_items = self.config.max_scan_items if scan_limit is None else scan_limit
        folder_path = self._resolve_full_path(relative_path, snapshot_id)

        folder_name = os.path.basename(relative_path)
        if relative_path.endswith("/"):
            folder_name = os.path.basename(os.path.dirname(relative_path))

        if not os.path.isdir(folder_path):
            raise ValueError("Path is not a directory")

        contents = FolderContents(folder=FolderItem(name=folder_name, path=relative_path))

        items : list[FileSystemItem] = []
        for entry in os.scandir(folder_path):
            if (
                not snapshot_id
                and entry.is_dir()
                and not self.config.include_snapshot_root
                and self.config.snapshot_folder_name
                and entry.name == self.config.snapshot_folder_name
            ):
                continue

            item_path = relative_path

            if relative_path and not relative_path.endswith("/"):
                item_path += "/"

            item_path += entry.name

            if entry.is_dir():
                # Ensure this folder is not some excluded folder or inside one
                absolute_item_path = self._build_path(item_path)
                if self._check_path_is_in_excluded_folder(absolute_item_path):
                    continue
                item = FolderItem(name=entry.name, path=item_path)
            else:
                item = FileItem(
                    name=entry.name,
                    path=item_path,
                    size=entry.stat().st_size)
                if self.config.max_return_file_size:
                    item.define_if_is_too_large(self.config.max_return_file_size)

            items.append(FileSystemItem(item=item))

            if scan_first_items and len(items) >= scan_first_items:
                break

        contents.load_contents(items)
        return contents
    
    def get_metadata(self, path: str, snapshot_id: str | None = None) -> FileMetadata:
        """
        Get the metadata of a file.
        """
        if createParser is None or extractMetadata is None:
            raise ValueError("hachoir is not available to extract metadata.")

        full_path = self._resolve_full_path(path, snapshot_id)
        
        stat = os.stat(full_path)

        if os.path.isdir(full_path):
            raise ValueError("Path is a directory")

        item = FileItem(
            name=os.path.basename(path),
            path=path,
            size=stat.st_size
        )
        if self.config.max_return_file_size:
            item.define_if_is_too_large(self.config.max_return_file_size)

        metadata = FileMetadata(file_item=item, metadata={})

        parser = createParser(full_path)
        if not parser:
            raise SystemExit(f"Unable to parse file: {path}")

        extracted_metadata = extractMetadata(parser)
        if extracted_metadata:
            for item in extracted_metadata:
                if item.values:  # some items may be empty
                    # many items can have multiple values; print them all
                    vals = [v.value for v in item.values]
                    metadata[item.key] = vals if len(vals) > 1 else vals[0]

        return metadata

    def get_file_content(
        self,
        path: str,
        size_limit_kind: SizeLimitKind = SizeLimitKind.RETURN,
        snapshot_id: str | None = None,
    ) -> bytes:
        """
        Get the content of a file as bytes.
        """
        full_path = self._resolve_full_path(path, snapshot_id)
        
        self._check_file_size_is_not_too_large(full_path, size_limit_kind)
        
        with open(full_path, "rb") as f:
            return f.read()

    def get_file_content_as_string(
        self,
        path: str,
        size_limit_kind: SizeLimitKind = SizeLimitKind.RETURN,
        snapshot_id: str | None = None,
    ) -> str:
        """
        Get the content of a file as a string.
        """

        full_path = self._resolve_full_path(path, snapshot_id)
        self._check_file_size_is_not_too_large(full_path, size_limit_kind)

        with open(full_path, "r", encoding="utf-8", errors='replace') as f:
            return f.read()

    def get_image_file_format(self, path: str) -> str:
        """
        Get the image file format from the file extension.
        """
        ext = os.path.splitext(path)[1].lower()
        if ext == ".png":
            return "png"
        elif ext in [".jpg", ".jpeg"]:
            return "jpg"
        raise ValueError(f"Unsupported image format: {ext}")

    def _check_file_size_is_not_too_large(self, full_path: str, size_limit_kind: SizeLimitKind = SizeLimitKind.RETURN):
        """
        Check if the file size is not too large.
        """
        stat = os.stat(full_path)

        if size_limit_kind == SizeLimitKind.READ:
            if self.config.max_read_file_size is not None and stat.st_size > self.config.max_read_file_size:
                raise ValueError(f"File {full_path} is too large to download.")

        elif size_limit_kind == SizeLimitKind.RETURN:
            if self.config.max_return_file_size is not None and stat.st_size > self.config.max_return_file_size:
                raise ValueError(f"File {full_path} is too large to return.")

    def _require_path_is_in_excluded_folder(self, path: str):
        """
        Raise an error if the given path is in any of the excluded folders.
        """
        if self._check_path_is_in_excluded_folder(path):
            raise ValueError(f"Path {path} is not found.")
    
    def _check_path_is_in_excluded_folder(self, path: str) -> bool:
        """
        Check if the given path is in any of the excluded folders.
        """
        return any(path.startswith(excluded) for excluded in self.config.exclude_folders)

    def _build_path(self, relative_path: str) -> str:
        """
        Build the absolute path for a given relative path.
        """

        if relative_path == "" or relative_path == "/" or not relative_path or relative_path == ".":
            return self.config.file_system_path

        # some tricks to protect against path traversal
        path = os.path.join(self.config.file_system_path, relative_path)
        abs_path = os.path.abspath(path)
        base_dir = os.path.abspath(self.config.file_system_path)
        # Use os.path.commonpath to check if abs_path is within base_dir
        if os.path.commonpath([abs_path, base_dir]) != base_dir:
            raise ValueError("Access to the path is not allowed.")
        return abs_path

    def _resolve_full_path(self, relative_path: str, snapshot_id: str | None = None) -> str:
        """
        Resolve the absolute path for a relative path, optionally within a snapshot.
        """
        normalized_path = relative_path
        if normalized_path in ("", "/", "\\", None):
            normalized_path = ""

        if snapshot_id:
            self._ensure_path_allowed(normalized_path)
            resolved = self._build_snapshot_path(snapshot_id, normalized_path)
        else:
            resolved = self._build_path(normalized_path)
            self._require_path_is_in_excluded_folder(resolved)

        if not os.path.exists(resolved):
            raise ValueError(f"Path {resolved} is not found.")

        return resolved

    def _ensure_path_allowed(self, relative_path: str):
        """
        Ensure the relative path is not excluded.
        """
        canonical_path = self._build_path(relative_path)
        self._require_path_is_in_excluded_folder(canonical_path)

    def _build_snapshot_path(self, snapshot_id: str, relative_path: str) -> str:
        """
        Build the absolute path to a resource inside a snapshot.
        """
        snapshot_root = self._get_snapshot_root()
        snapshot_base = os.path.join(snapshot_root, snapshot_id)
        snapshot_base = os.path.abspath(snapshot_base)

        if not os.path.isdir(snapshot_base):
            raise ValueError(f"Snapshot {snapshot_id} is not available.")

        if relative_path in ("", "/", "\\"):
            return snapshot_base

        path = os.path.join(snapshot_base, relative_path)
        abs_path = os.path.abspath(path)

        if os.path.commonpath([abs_path, snapshot_base]) != snapshot_base:
            raise ValueError("Access to the snapshot path is not allowed.")

        return abs_path

    def _get_snapshot_root(self) -> str:
        """
        Get the absolute path to the snapshot root directory.
        """
        if not self.config.snapshot_folder_name:
            raise ValueError("Snapshot support is disabled.")

        snapshot_root = os.path.join(self.config.file_system_path, self.config.snapshot_folder_name)
        snapshot_root = os.path.abspath(snapshot_root)

        if not os.path.isdir(snapshot_root):
            raise ValueError(f"Snapshot root {snapshot_root} is not available.")

        return snapshot_root

    def _parse_snapshot_timestamp(self, snapshot_id: str) -> datetime | None:
        """
        Attempt to parse a timestamp out of a snapshot identifier.
        """
        formats = [
            "%Y_%m_%d_%H.%M%Z",
            "%Y_%m_%d_%H.%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(snapshot_id, fmt)
            except ValueError:
                continue
        return None

    def list_snapshots(self, path: str = "") -> SnapshotList:
        """
        List snapshots available for the configured path.
        """
        target_path = "" if path in ("", "/", "\\") else path
        snapshots: list[SnapshotSummary] = []

        if not self.config.snapshot_folder_name:
            return SnapshotList(
                snapshot_folder="",
                target_path=target_path,
                snapshots=[],
            )

        try:
            snapshot_root = self._get_snapshot_root()
        except ValueError:
            return SnapshotList(
                snapshot_folder=self.config.snapshot_folder_name,
                target_path=target_path,
                snapshots=[],
            )

        try:
            self._ensure_path_allowed(target_path)
        except ValueError:
            # If it is excluded, report no snapshots
            return SnapshotList(
                snapshot_folder=self.config.snapshot_folder_name,
                target_path=target_path,
                snapshots=[],
            )

        for entry in os.scandir(snapshot_root):
            if not entry.is_dir():
                continue
            snapshot_id = entry.name
            timestamp = self._parse_snapshot_timestamp(snapshot_id)

            candidate_path = os.path.join(entry.path, target_path) if target_path else entry.path
            has_path = os.path.exists(candidate_path)

            snapshots.append(
                SnapshotSummary(
                    id=snapshot_id,
                    display_name=snapshot_id,
                    timestamp=timestamp,
                    contains_path=has_path,
                )
            )

        # Sort descending by timestamp if available, otherwise alphabetically descending
        snapshots.sort(
            key=lambda item: (
                item.timestamp if item.timestamp is not None else datetime.min,
                item.id,
            ),
            reverse=True,
        )

        return SnapshotList(
            snapshot_folder=self.config.snapshot_folder_name,
            target_path=target_path,
            snapshots=snapshots,
        )
