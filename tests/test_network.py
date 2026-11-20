import unittest

import RNS

from retibbs_gui.gui import interface_rows, single_process_stamps


class InterfaceRowsTest(unittest.TestCase):
    def test_rows_hide_per_client_interfaces(self):
        stats = {"interfaces": [
            {"name": "RNodeInterface[RNode LoRa]", "status": True, "bitrate": 1200, "rxb": 2048, "txb": 0},
            {"name": "TCPInterface[Client on Test]", "status": True, "rxb": 0, "txb": 0},
            {"name": "LocalInterface[37428]", "status": True, "rxb": 0, "txb": 0},
            {"name": "AutoInterface[Default Interface]", "status": False, "rxb": None, "txb": None},
        ]}
        rows = interface_rows(stats)
        self.assertEqual([row[0] for row in rows], ["RNode LoRa", "Default Interface"])
        self.assertEqual(rows[0][1:3], ("RNode", "Up"))
        self.assertEqual(rows[1][2], "Down")
        self.assertEqual(rows[1][3], "")

    def test_no_stats(self):
        self.assertEqual(interface_rows(None), [])


class StampTest(unittest.TestCase):
    def test_stamps_never_fork(self):
        saved = RNS.Stamps.POOLING_THRESHOLD_COST_FP
        try:
            single_process_stamps()
            self.assertEqual(RNS.Stamps.POOLING_THRESHOLD_COST_FP, float("inf"))
        finally:
            RNS.Stamps.POOLING_THRESHOLD_COST_FP = saved


if __name__ == "__main__":
    unittest.main()
