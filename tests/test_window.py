import unittest

from retibbs_gui.gui import window_fits


class WindowFitsTest(unittest.TestCase):
    def test_saved_size_must_fit_the_screen(self):
        self.assertTrue(window_fits("900x600+40+30", 1366, 768))
        self.assertTrue(window_fits("900x600", 1024, 600))
        self.assertFalse(window_fits("1200x800+40+30", 1366, 768))
        self.assertFalse(window_fits("900x500+2000+30", 1366, 768))

    def test_bad_geometry(self):
        self.assertFalse(window_fits("", 1366, 768))
        self.assertFalse(window_fits("big", 1366, 768))


if __name__ == "__main__":
    unittest.main()
