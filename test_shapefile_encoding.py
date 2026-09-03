import tempfile
import unittest
from pathlib import Path

from shapefile_encoding import declared_shapefile_encoding, infer_dbf_encoding


class ShapefileEncodingTests(unittest.TestCase):
    @staticmethod
    def _single_character_field_dbf(values, encoding):
        field_length = 80
        header_length = 32 + 32 + 1
        record_length = 1 + field_length
        header = bytearray(header_length)
        header[0] = 0x03
        # Deliberately invalid text bytes in the binary date header reproduce
        # the false CP949 replacements caused by sampling the whole DBF.
        header[1:4] = b"\xff\xfe\xfd"
        header[4:8] = len(values).to_bytes(4, "little")
        header[8:10] = header_length.to_bytes(2, "little")
        header[10:12] = record_length.to_bytes(2, "little")
        descriptor = 32
        field_name = "유적명".encode("cp949")
        header[descriptor:descriptor + len(field_name)] = field_name
        header[descriptor + 11] = ord("C")
        header[descriptor + 16] = field_length
        header[-1] = 0x0D
        records = []
        for value in values:
            encoded = value.encode(encoding)
            records.append(
                b" " + encoded[:field_length].ljust(field_length, b" ")
            )
        return bytes(header) + b"".join(records) + b"\x1a"

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

    def test_detects_cp949_from_character_records_not_binary_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heritage.dbf"
            path.write_bytes(self._single_character_field_dbf(
                ["공주 정지산 유적", "청동기시대 유물산포지"],
                "cp949",
            ))

            self.assertEqual(infer_dbf_encoding(path), "CP949")

    def test_structured_utf8_dbf_is_not_forced_to_cp949(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heritage.dbf"
            path.write_bytes(self._single_character_field_dbf(
                ["공주 정지산 유적", "청동기시대 유물산포지"],
                "utf-8",
            ))

            self.assertIsNone(infer_dbf_encoding(path))

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

    def test_record_detection_overrides_stale_utf8_cpg_without_driver_id(self):
        with tempfile.TemporaryDirectory() as directory:
            shp_path = Path(directory) / "heritage.shp"
            shp_path.write_bytes(b"")
            shp_path.with_suffix(".dbf").write_bytes(
                self._single_character_field_dbf(
                    ["공주 정지산 유적"],
                    "cp949",
                )
            )
            shp_path.with_suffix(".cpg").write_text(
                "UTF-8",
                encoding="ascii",
            )

            self.assertEqual(
                declared_shapefile_encoding(shp_path),
                ("CP949", "DBF automatic detection"),
            )


if __name__ == "__main__":
    unittest.main()
