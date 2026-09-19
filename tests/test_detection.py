import json
import unittest
from unittest.mock import MagicMock, patch

from client.core.system_detect import PartitionInfo, SystemDetector


class TestSystemDetector(unittest.TestCase):
    """Unit tests for the system detection engine."""

    SAMPLE_LSBLK_OUTPUT = {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "mountpoint": None,
                "fstype": None,
                "uuid": None,
                "size": 512110190592,
                "children": [
                    {
                        "name": "nvme0n1p1",
                        "path": "/dev/nvme0n1p1",
                        "mountpoint": "/boot/efi",
                        "fstype": "vfat",
                        "uuid": "A1B2-C3D4",
                        "size": 536870912,
                    },
                    {
                        "name": "nvme0n1p3",
                        "path": "/dev/nvme0n1p3",
                        "mountpoint": "/home",
                        "fstype": "ext4",
                        "uuid": "b8c3d2e1-4f5a-6b7c-8d9e-0f1a2b3c4d5e",
                        "size": 250000000000,
                    },
                ],
            }
        ]
    }

    @patch("shutil.which", return_value="/usr/bin/lsblk")
    def setUp(self, mock_which):
        self.detector = SystemDetector()

    @patch("subprocess.run")
    @patch("shutil.disk_usage")
    def test_list_block_devices_success(self, mock_disk_usage, mock_run):
        """Validates recursive traversal and parsing of lsblk block devices."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(self.SAMPLE_LSBLK_OUTPUT),
        )
        # Mock disk usage for /home: total, used, free
        mock_disk_usage.return_value = MagicMock(
            total=250000000000,
            used=182536110080,
            free=67463889920,
        )

        devices = self.detector.list_block_devices()

        self.assertEqual(len(devices), 3)  # nvme0n1, nvme0n1p1, nvme0n1p3

        home_part = next((d for d in devices if d.mountpoint == "/home"), None)
        self.assertIsNotNone(home_part)
        self.assertEqual(home_part.device_path, "/dev/nvme0n1p3")
        self.assertEqual(home_part.fstype, "ext4")
        self.assertEqual(home_part.used_bytes, 182536110080)
        self.assertTrue(home_part.is_mounted)

    @patch("subprocess.run")
    def test_list_block_devices_corrupted_json(self, mock_run):
        """Tests that malformed command output fails gracefully."""
        mock_run.return_value = MagicMock(returncode=0, stdout="not-json")
        devices = self.detector.list_block_devices()
        self.assertEqual(devices, [])

    @patch.object(SystemDetector, "list_block_devices")
    def test_get_partition_by_path_or_mount(self, mock_list):
        """Tests locating partitions by either device path or mountpoint."""
        dummy_partition = PartitionInfo(
            name="nvme0n1p3",
            device_path="/dev/nvme0n1p3",
            mountpoint="/home",
            fstype="ext4",
            uuid="1234-abcd",
            total_bytes=250000000000,
            used_bytes=170000000000,
            available_bytes=80000000000,
        )
        mock_list.return_value = [dummy_partition]

        # By device path
        res1 = self.detector.get_partition_by_path_or_mount("/dev/nvme0n1p3")
        self.assertIsNotNone(res1)
        self.assertEqual(res1.mountpoint, "/home")

        # By mount point
        res2 = self.detector.get_partition_by_path_or_mount("/home")
        self.assertIsNotNone(res2)
        self.assertEqual(res2.device_path, "/dev/nvme0n1p3")

        # Non-existent
        res3 = self.detector.get_partition_by_path_or_mount("/dev/nonexistent")
        self.assertIsNone(res3)


if __name__ == "__main__":
    unittest.main()