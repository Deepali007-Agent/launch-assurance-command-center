import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest


class UISmokeTest(unittest.TestCase):
    def test_app_renders_without_exception(self):
        app = Path(__file__).resolve().parents[1] / "app.py"
        result = AppTest.from_file(str(app), default_timeout=30).run()
        self.assertFalse(result.exception)
        self.assertTrue(any("Onboarding Intelligence" in title.value for title in result.title))


if __name__ == "__main__":
    unittest.main()
