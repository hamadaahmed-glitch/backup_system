import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from client.core.rsync_runner import RsyncRunner
from client.core.ssh_client import SSHClient
from client.core.verifier import Verifier
from desktop.core.storage_manager import StorageManager


class TestNetworkAndFaultScenarios(unittest.TestCase):
    """Integration and failure-mode test suites."""

    def test_ssh_connection_timeout(self):
        """Validates timeout handling during network latency spikes."""
        ssh_client = SSHClient(host="192.168.1.200", user="backup-user", connect_timeout=1)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=1)):
            success, msg = ssh_client.test_connection()
            self.assertFalse(success)
            self.assertIn("timed out", msg)

    def test_rsync_runner_interruption(self):
        """Tests that runner handles process cancellation correctly."""
        runner = RsyncRunner(
            source_dir="/home/test",
            dest_user="backup-user",
            dest_host="192.168.1.50",
            dest_path="/srv/backups",
        )

        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        mock_process.returncode = -2  # SIGINT return code
        mock_process.stdout.fileno.return_value = 10
        mock_process.stderr.fileno.return_value = 11
        mock_process.stdout.read.return_value = b""
        mock_process.stderr.read.return_value = b""

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("select.select", return_value=([], [], [])):
                res = runner.execute()
                self.assertEqual(res.exit_code, -2)

    def test_verifier_rsync_exit_codes(self):
        """Tests verifier categorization of successful, warning, and fatal exit codes."""
        mock_ssh = MagicMock(spec=SSHClient)
        verifier = Verifier(mock_ssh)

        # Code 0: Clean Success
        ok, meaning = verifier.interpret_exit_code(0)
        self.assertTrue(ok)
        self.assertEqual(meaning, "Success")

        # Code 24: Vanished source files (Non-fatal warning in live systems)
        ok_24, meaning_24 = verifier.interpret_exit_code(24)
        self.assertTrue(ok_24)
        self.assertIn("vanished", meaning_24)

        # Code 11: File I/O Error (Fatal)
        ok_11, meaning_11 = verifier.interpret_exit_code(11)
        self.assertFalse(ok_11)
        self.assertIn("file I/O", meaning_11)

    def test_storage_concurrency_lock(self):
        """Validates that concurrent operations targeting the same client are prevented."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = StorageManager(Path(tmp_dir))
            client_id = "Laptop-Test"

            # First acquisition succeeds
            first_lock = storage.acquire_lock(client_id)
            self.assertTrue(first_lock)

            # Second concurrent acquisition must be rejected
            second_lock = storage.acquire_lock(client_id)
            self.assertFalse(second_lock)

            # Release lock
            storage.release_lock(client_id)

            # Subsequent acquisition succeeds again
            third_lock = storage.acquire_lock(client_id)
            self.assertTrue(third_lock)
            storage.release_lock(client_id)


if __name__ == "__main__":
    unittest.main()