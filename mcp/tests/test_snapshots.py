import os
import unittest

from app.config import Config
from app.file_system import FileSystem, SizeLimitKind

SAMPLE_SHARE = "/Users/jcapello/Desktop/UnifyDemo/AlfaDesign"
SNAPSHOT_FOLDER_NAME = ".snapshot"


@unittest.skipUnless(
    os.path.isdir(SAMPLE_SHARE) and os.path.isdir(os.path.join(SAMPLE_SHARE, SNAPSHOT_FOLDER_NAME)),
    "Sample Nasuni share with snapshots is required for snapshot tests.",
)
class SnapshotIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.file_system_path = SAMPLE_SHARE
        self.config.snapshot_folder_name = SNAPSHOT_FOLDER_NAME
        self.config.include_snapshot_root = False
        self.config.exclude_folders = []
        self.fs = FileSystem(self.config)

        snapshot_listing = self.fs.list_snapshots()
        if not snapshot_listing.snapshots:
            self.skipTest("No snapshots available for testing.")

        self.snapshot_listing = snapshot_listing
        self.snapshot_id = snapshot_listing.snapshots[0].id

    def test_snapshot_listing_contains_snapshots(self):
        self.assertGreater(len(self.snapshot_listing.snapshots), 0)
        latest_timestamp = self.snapshot_listing.snapshots[0].timestamp
        for snapshot in self.snapshot_listing.snapshots[1:]:
            if latest_timestamp and snapshot.timestamp:
                self.assertLessEqual(snapshot.timestamp, latest_timestamp)

    def test_folder_contents_from_snapshot(self):
        contents = self.fs.folder_contents("", snapshot_id=self.snapshot_id)
        file_names = {file.name for file in contents.files}
        self.assertIn("README.md", file_names)
        self.assertIn("DesignSpec.docx", file_names)

    def test_snapshot_file_contents_match_disk(self):
        relative_path = "README.md"
        snapshot_file_path = os.path.join(
            SAMPLE_SHARE, SNAPSHOT_FOLDER_NAME, self.snapshot_id, relative_path
        )
        with open(snapshot_file_path, "rb") as handle:
            expected_bytes = handle.read()

        actual_bytes = self.fs.get_file_content(
            relative_path,
            snapshot_id=self.snapshot_id,
            size_limit_kind=SizeLimitKind.RETURN,
        )
        self.assertEqual(expected_bytes, actual_bytes)

    def test_snapshot_text_extraction(self):
        text = self.fs.get_file_content_as_string("README.md", snapshot_id=self.snapshot_id)
        self.assertIsInstance(text, str)
        self.assertGreater(len(text.strip()), 0)

    def test_snapshot_visibility_toggle(self):
        contents_hidden = self.fs.folder_contents("")
        hidden_folders = {folder.name for folder in contents_hidden.subfolders}
        self.assertNotIn(SNAPSHOT_FOLDER_NAME, hidden_folders)

        config_show = Config()
        config_show.file_system_path = SAMPLE_SHARE
        config_show.snapshot_folder_name = SNAPSHOT_FOLDER_NAME
        config_show.include_snapshot_root = True
        fs_show = FileSystem(config_show)
        contents_visible = fs_show.folder_contents("")
        visible_folders = {folder.name for folder in contents_visible.subfolders}
        self.assertIn(SNAPSHOT_FOLDER_NAME, visible_folders)

    def test_snapshot_list_for_specific_file(self):
        snapshot_list = self.fs.list_snapshots("DesignSpec.docx")
        self.assertEqual(snapshot_list.target_path, "DesignSpec.docx")
        self.assertTrue(any(item.contains_path for item in snapshot_list.snapshots))

