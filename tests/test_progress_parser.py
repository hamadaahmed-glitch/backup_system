import unittest
from client.core.progress_parser import ProgressParser, TransferProgress


class TestProgressParser(unittest.TestCase):
    """Unit tests for the rsync progress2 regex parsing engine."""

    def setUp(self):
        self.parser = ProgressParser()

    def test_parse_standard_progress2_line(self):
        """Tests parsing a standard progress update line."""
        raw_line = " 78,147,968  45%   74.52MB/s    0:01:14 (xfr#412, to-chk=85/1042)"
        result = self.parser.parse_line(raw_line)

        self.assertIsInstance(result, TransferProgress)
        self.assertEqual(result.bytes_transferred, 78147968)
        self.assertEqual(result.percentage, 45)
        self.assertEqual(result.speed_str, "74.52MB/s")
        self.assertEqual(result.eta_str, "0:01:14")
        self.assertEqual(result.files_transferred, 412)
        self.assertEqual(result.to_check_str, "85/1042")

    def test_parse_large_gigabyte_transfer(self):
        """Tests parsing 100+ GB numbers with multi-digit comma separators."""
        raw_line = " 182,536,110,080 100%  108.12MB/s  0:00:00 (xfr#9999, to-chk=0/12000)"
        result = self.parser.parse_line(raw_line)

        self.assertIsNotNone(result)
        self.assertEqual(result.bytes_transferred, 182536110080)
        self.assertEqual(result.percentage, 100)
        self.assertEqual(result.speed_str, "108.12MB/s")

    def test_parse_carriage_return_variations(self):
        """Ensures surrounding carriage returns and whitespaces are handled."""
        raw_line = "\r   524,288   1%   15.20KB/s  1:45:10\r\n"
        result = self.parser.parse_line(raw_line)

        self.assertIsNotNone(result)
        self.assertEqual(result.bytes_transferred, 524288)
        self.assertEqual(result.percentage, 1)
        self.assertEqual(result.speed_str, "15.20KB/s")
        self.assertEqual(result.eta_str, "1:45:10")
        self.assertIsNone(result.files_transferred)

    def test_parse_invalid_or_irrelevant_stdout(self):
        """Verifies arbitrary text or rsync banner text is cleanly ignored."""
        self.assertIsNone(self.parser.parse_line("sending incremental file list"))
        self.assertIsNone(self.parser.parse_line(""))
        self.assertIsNone(self.parser.parse_line("\r\n"))
        self.assertIsNone(self.parser.parse_line("total size is 182,536,110,080  speedup is 1.00"))


if __name__ == "__main__":
    unittest.main()