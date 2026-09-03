import tempfile
import unittest
from pathlib import Path

from shapefile_encoding import declared_shapefile_encoding, infer_dbf_encoding


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

    def test_shapefile_resolver_detects_cp949_before_provider_reads_it(self):
        header = bytearray(32)
        header[29] = 0x79
        with tempfile.TemporaryDirectory() as directory:
            shp_path = Path(directory) / "heritage.shp"
            shp_path.write_bytes(b"")
            shp_path.with_suffix(".dbf").write_bytes(bytes(header))
            self.assertEqual(
                declared_shapefile_encoding(shp_path),
                ("CP949", "DBF automatic detection"),
            )

    def test_shapefile_resolver_keeps_cpg_as_authoritative(self):
        with tempfile.TemporaryDirectory() as directory:
            shp_path = Path(directory) / "heritage.shp"
            shp_path.write_bytes(b"")
            shp_path.with_suffix(".cpg").write_text("949", encoding="ascii")
            self.assertEqual(
                declared_shapefile_encoding(shp_path),
                ("CP949", ".cpg"),
            )

    def test_cp949_dbf_overrides_a_stale_utf8_cpg(self):
        header = bytearray(32)
        header[29] = 0x79
        with tempfile.TemporaryDirectory() as directory:
            shp_path = Path(directory) / "heritage.shp"
            shp_path.write_bytes(b"")
            shp_path.with_suffix(".dbf").write_bytes(bytes(header))
            shp_path.with_suffix(".cpg").write_text("UTF-8", encoding="ascii")
            self.assertEqual(
                declared_shapefile_encoding(shp_path),
                ("CP949", "DBF automatic detection"),
            )


if __name__ == "__main__":
    unittest.main()
