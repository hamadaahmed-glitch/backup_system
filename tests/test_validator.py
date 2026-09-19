import unittest
from unittest.mock import MagicMock, patch

from client.core.ssh_client import SSHClient
from client.core.system_detect import PartitionInfo
from client.core.validator import SystemValidator


class TestSystemValidator(unittest.TestCase):
    """Unit tests for the pre-flight validation logic."""

    def setUp(self):
        self.mock_ssh = MagicMock(spec=SSHClient)
        self.mock_ssh.host = "192.168.1.50"
        self.mock_ssh.port = 22
        self.validator = SystemValidator(self.mock_ssh)

    @patch("pathlib.Path.is_dir", return_value=True)
    @patch("pathlib.Path.exists", return_value=True)
    @patch.object(SystemValidator, "is_host_reachable", return_value=True)
    def test_pre_flight_success(self, mock_reachable, mock_exists, mock_isdir):
        """Validates passing state when all resources and capacities check out."""
        partition = PartitionInfo(
            name="nvme0n1p3",
            device_path="/dev/nvme0n1p3",
            mountpoint="/home",
            fstype="ext4",
            uuid="abc-123",
            total_bytes=250 * 1024**3,
            used_bytes=170 * 1024**3,
            available_bytes=80 * 1024**3,
        )

        self.mock_ssh.test_connection.return_value = (True, "OK")
        self.mock_ssh.check_remote_rsync_installed.return_value = True
        # Remote has 220 GB free (> 170 GB + 10% safety margin)
        self.mock_ssh.get_remote_free_space.return_value = 220 * 1024**3

        result = self.validator.validate_pre_flight(partition, "/srv/backups")

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)

    @patch("pathlib.Path.is_dir", return_value=True)
    @patch("pathlib.Path.exists", return_value=True)
    @patch.object(SystemValidator, "is_host_reachable", return_value=True)
    def test_pre_flight_insufficient_space(self, mock_reachable, mock_exists, mock_isdir):
        """Validates rejection when destination space is insufficient for source + margin."""
        partition = PartitionInfo(
            name="nvme0n1p3",
            device_path="/dev/nvme0n1p3",
            mountpoint="/home",
            fstype="ext4",
            uuid="abc-123",
            total_bytes=250 * 1024**3,
            used_bytes=170 * 1024**3,  # Needs ~187 GB with 10% margin
            available_bytes=80 * 1024**3,
        )

        self.mock_ssh.test_connection.return_value = (True, "OK")
        self.mock_ssh.check_remote_rsync_installed.return_value = True
        # Remote has only 120 GB free
        self.mock_ssh.get_remote_free_space.return_value = 120 * 1024**3

        result = self.validator.validate_pre_flight(partition, "/srv/backups")

        self.assertFalse(result.is_valid)
        self.assertTrue(any("Insufficient disk space" in err for err in result.errors))

    def test_pre_flight_unmounted_partition(self):
        """Ensures unmounted partitions are rejected immediately."""
        unmounted_partition = PartitionInfo(
            name="sdb1",
            device_path="/dev/sdb1",
            mountpoint=None,
            fstype="ext4",
            uuid="none",
            total_bytes=100 * 1024**3,
            used_bytes=0,
            available_bytes=0,
        )

        result = self.validator.validate_pre_flight(unmounted_partition, "/srv/backups")
        self.assertFalse(result.is_valid)
        self.assertTrue(any("is not mounted" in err for err in result.errors))


if __name__ == "__main__":
    unittest.main()