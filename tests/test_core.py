import tempfile
import unittest
from pathlib import Path

from cyberdrop_desk.core import (
    Settings,
    clean_output,
    normalize_urls,
    parse_file_progress,
    parse_supported_sites,
    write_engine_config,
)


class NormalizeUrlsTests(unittest.TestCase):
    def test_accepts_multiple_and_removes_duplicates(self) -> None:
        self.assertEqual(
            normalize_urls("https://example.com/a\nhttps://example.com/b https://example.com/a"),
            ["https://example.com/a", "https://example.com/b"],
        )

    def test_rejects_non_web_values(self) -> None:
        with self.assertRaises(ValueError):
            normalize_urls("not-a-link")


class ConfigTests(unittest.TestCase):
    def test_writes_valid_minimal_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "config.yaml"
            settings = Settings.defaults()
            settings.download_folder = r"C:\Users\Test User\Downloads"
            settings.videos = False
            write_engine_config(settings, target)
            content = target.read_text(encoding="utf-8")
            self.assertIn('download_folder: "C:\\\\Users\\\\Test User\\\\Downloads"', content)
            self.assertIn("videos: false", content)
            self.assertIn("mode: activity", content)

    def test_removes_terminal_control_codes(self) -> None:
        self.assertEqual(clean_output("\x1b[31mError\x1b[0m\r\n"), "Error")


class FileProgressTests(unittest.TestCase):
    def test_reads_cyberdrop_structured_ui_snapshot(self) -> None:
        progress = parse_file_progress(
            '{"files":{"completed":12,"prev_completed":3,"skipped":2,"failed":1,"queued":982}}'
        )
        self.assertIsNotNone(progress)
        assert progress is not None
        self.assertEqual(progress.completed, 18)
        self.assertEqual(progress.total, 1000)
        self.assertEqual(progress.downloaded, 12)
        self.assertEqual(progress.queued, 982)

    def test_ignores_normal_log_lines_and_unrelated_json(self) -> None:
        self.assertIsNone(parse_file_progress("Downloading file.jpg"))
        self.assertIsNone(parse_file_progress('{"status":"working"}'))

    def test_reads_and_sorts_supported_site_names(self) -> None:
        self.assertEqual(
            parse_supported_sites('{"Zippy":{"site":"Zippy"},"archive.org":{"site":"Archive"}}'),
            ["archive.org", "Zippy"],
        )


if __name__ == "__main__":
    unittest.main()
