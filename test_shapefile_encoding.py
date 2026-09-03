import tempfile
import unittest
from pathlib import Path

from shapefile_encoding import infer_dbf_encoding


class ShapefileEncodingTests(unittest.TestCase):
    def test_reads_korean_dbf_language_driver(self):
        header = bytearray(32)
        header[29] = 0x79
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zone.dbf"
            path.write_bytes(bytes(header) + "현상변경 2-1구역".encode("cp949"))
            self.assertEqual(infer_dbf_encoding(path), "CP949")

    def test_detects_cp949_when_utf8_decoding_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zone.dbf"
            path.write_bytes("현상변경 2-1구역".encode("cp949"))
            self.assertEqual(infer_dbf_encoding(path), "CP949")

    def test_does_not_override_valid_utf8_without_declaration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zone.dbf"
            path.write_bytes("현상변경 2-1구역".encode("utf-8"))
            self.assertIsNone(infer_dbf_encoding(path))


if __name__ == "__main__":
    unittest.main()
