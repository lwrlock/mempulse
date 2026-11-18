import unittest
from mempulse.engine import compute_effective_headroom_gb, decode_mglru_flags


class MemPulseTests(unittest.TestCase):
    def test_mglru_decoder(self):
        decoded = decode_mglru_flags("0x0007")
        self.assertIn("LRU Gen", decoded)
        self.assertIn("PTE Walk", decoded)
        self.assertIn("Non-leaf Clear", decoded)
        self.assertEqual(decode_mglru_flags("0"), "Disabled")

    def test_headroom_math(self):
        gb = compute_effective_headroom_gb(32768.0, 16384.0, 3072.0, 1024.0)
        self.assertEqual(gb, 18.0)


if __name__ == "__main__":
    unittest.main()
