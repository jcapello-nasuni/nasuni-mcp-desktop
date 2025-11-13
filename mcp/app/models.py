""" Models for representing file system items."""
import os
from datetime import datetime
from pydantic import BaseModel, Field, computed_field

class Item(BaseModel):
    """
    Represents a file or folder in the file system.
    """
    name: str = Field(description="Name of the file or folder")
    path: str = Field(description="Path to the file or folder")

class FolderItem(Item):
    """
    Represents a folder in the file system.
    """

class FileItem(Item):
    """
    Represents a file in the file system.
    """
    size: int = Field(description="Size of the file in bytes")
    is_too_large: bool = Field(default=False, description="Whether the item is too large to download")

    @computed_field
    @property
    def is_supported_image(self) -> bool:
        """
        Check if the file or folder is a supported image.
        """
        ext = os.path.splitext(self.name)[1].lower()
        return ext in [".png", ".jpg", ".jpeg"]

    @computed_field
    @property
    def supports_text_extraction(self) -> bool:
        """
        Check if the file or folder supports text extraction.
        """
        ext = os.path.splitext(self.name)[1].lower()
        return ext in [".pdf", ".docx"]

    def define_if_is_too_large(self, max_size: int):
        """
        Define if the file is too large.
        """
        if self.size > max_size:
            self.is_too_large = True

class FileMetadata(BaseModel):
    """ Represents extended file item with metadata extracted from the file."""
    file_item: FileItem = Field(description="The file item")
    metadata: dict = Field(default_factory=dict, description="Metadata extracted from the file")

    # allow metadata[key] = value
    def __setitem__(self, key, value):
        self.metadata[key] = value

    # optional, for reads like metadata[key]
    def __getitem__(self, key):
        return self.metadata[key]

class FileSystemItem(BaseModel):
    """
    Represents a file system item (file or folder).
    """
    item: Item = Field(description="The file or folder item")
    
    @computed_field
    @property
    def is_folder(self) -> bool:
        """
        Check if the item is a folder.
        """
        return isinstance(self.item, FolderItem)

    @computed_field
    @property
    def file(self) -> FileItem:
        """
        Return the file item if it exists. Else raises an error.
        """
        if isinstance(self.item, FileItem):
            return self.item
        raise ValueError("Item is not a file")

    @computed_field
    @property
    def folder(self) -> FolderItem:
        """
        Return the folder item if it exists. Else raises an error.
        """
        if isinstance(self.item, FolderItem):
            return self.item
        raise ValueError("Item is not a folder")

class FolderContents(BaseModel):
    """
    Represents the contents of a folder in the file system.
    """
    folder: FolderItem = Field(description="The folder item")

    subfolders: list[FolderItem] = Field(default=[], description="The subfolders in the folder")
    files: list[FileItem] = Field(default=[], description="The files in the folder")

    def load_contents(self, items: list[FileSystemItem]):
        """
        Load the contents of the folder.
        """
        self.subfolders = []
        self.files = []
        for item in items:
            if item.is_folder:
                self.subfolders.append(item.folder)
            else:
                self.files.append(item.file)

class SnapshotSummary(BaseModel):
    """
    Represents a snapshot directory entry.
    """
    id: str = Field(description="Identifier of the snapshot (folder name under the snapshot root)")
    display_name: str = Field(description="Human readable name for the snapshot")
    timestamp: datetime | None = Field(default=None, description="Parsed timestamp if available")
    contains_path: bool = Field(default=False, description="Whether the requested path exists in this snapshot")

class SnapshotList(BaseModel):
    """
    Represents snapshots available for a path.
    """
    snapshot_folder: str = Field(description="Name of the snapshot folder (e.g., .snapshot)")
    target_path: str = Field(description="The relative path that was queried")
    snapshots: list[SnapshotSummary] = Field(default_factory=list, description="Snapshots available for the path")
