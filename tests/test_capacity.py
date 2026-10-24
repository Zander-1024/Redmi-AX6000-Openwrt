import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from firmware import budget, MIB, PEB, LEB, ENV_SIZE, RECOVERY_SIZE


class CapacityTests(unittest.TestCase):
    def test_stock_root_boundary(self):
        blocks = 80 * MIB // PEB
        maximum = (blocks - 4 - math.ceil(blocks * 20 / 1024) - math.ceil(8 * MIB / LEB)) * LEB
        self.assertGreaterEqual(budget(80 * MIB, [maximum], 8 * MIB)['logical_data_bytes'], 8 * MIB)
        with self.assertRaises(ValueError):
            budget(80 * MIB, [maximum + 1], 8 * MIB)

    def test_ubootmod_includes_recovery_and_both_environments(self):
        # Large firmware can fit without a recovery volume, but must fail with it.
        large = 96 * MIB
        self.assertGreaterEqual(budget(0x7a80000, [large], 16 * MIB)['logical_data_bytes'], 16 * MIB)
        with self.assertRaises(ValueError):
            budget(0x7a80000, [large, ENV_SIZE, ENV_SIZE, RECOVERY_SIZE], 16 * MIB)

    def test_empty_image_rejected(self):
        with self.assertRaises(ValueError):
            budget(80 * MIB, [0], 8 * MIB)
