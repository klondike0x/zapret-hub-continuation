import unittest
from pathlib import Path


LOGS_PAGE = Path(__file__).parents[1] / "web_ui" / "src" / "pages" / "LogsPage.tsx"


class LogsPageLayoutTests(unittest.TestCase):
    def test_log_message_can_wrap_long_windows_paths(self) -> None:
        """Long paths must wrap when the expanded sidebar narrows the log column."""
        source = LOGS_PAGE.read_text(encoding="utf-8")

        self.assertIn(
            'className="min-w-0 flex-1 whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-fg"',
            source,
        )

    def test_zapret2_process_log_is_exposed_to_ui(self) -> None:
        source = Path(__file__).parents[1].joinpath("src/zapret_hub/ui/web_window.py").read_text(encoding="utf-8")
        self.assertIn('("zapret2", "zapret2.log", 180)', source)


if __name__ == "__main__":
    unittest.main()
