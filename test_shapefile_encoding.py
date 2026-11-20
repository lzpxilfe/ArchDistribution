from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shapefile_encoding import declared_shapefile_encoding, infer_dbf_encoding


class ShapefileEncodingTests(unittest.TestCase):
    @staticmethod
    def _character_fields_dbf(rows, encoding, *, widths=(80,), driver=0):
        header_length = 32 + 32 * len(widths) + 1
        record_length = 1 + sum(widths)
        header = bytearray(header_length)
        header[0] = 0x03
        # Deliberately invalid text bytes in the binary date header reproduce
        # the false CP949 replacements caused by sampling the whole DBF.
        header[1:4] = b"\xff\xfe\xfd"
        header[4:8] = len(rows).to_bytes(4, "little")
        header[8:10] = header_length.to_bytes(2, "little")
        header[10:12] = record_length.to_bytes(2, "little")
        header[29] = driver
        for index, width in enumerate(widths):
            descriptor = 32 + index * 32
            field_name = f"NAME_{index}".encode("ascii")
            header[descriptor:descriptor + len(field_name)] = field_name
            header[descriptor + 11] = ord("C")
            header[descriptor + 16:descriptor + 18] = width.to_bytes(2, "little")
        header[-1] = 0x0D
        records = [b" " + b"".join(
            value.encode(encoding)[:width].ljust(width, b" ")
            for value, width in zip(row, widths)
        ) for row in rows]
        return bytes(header) + b"".join(records) + b"\x1a"

    def _single_character_field_dbf(self, values, encoding):
        return self._character_fields_dbf([(value,) for value in values], encoding)

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

    def test_raw_fallback_ignores_partial_multibyte_character_at_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.dbf"
            path.write_bytes(b"A" * 28 + "고려".encode("utf-8"))
            self.assertIsNone(infer_dbf_encoding(path, sample_size=32))

    def test_bounded_reads_even_if_dbf_claims_many_blank_records(self):
        class TrackedFile(BytesIO):
            def __init__(self, data):
                super().__init__(data)
                self.read_sizes = []

            def read(self, size=-1):
                if size < 0:
                    raise AssertionError("read must specify a finite length")
                self.read_sizes.append(size)
                return super().read(size)

        dbf = bytearray(self._single_character_field_dbf([""] * 100, "utf-8"))
        dbf[4:8] = (2**30).to_bytes(4, "little")
        stream = TrackedFile(dbf)
        with patch.object(Path, "open", return_value=stream):
            self.assertIsNone(infer_dbf_encoding("unused.dbf", sample_size=1024))
        self.assertLessEqual(sum(stream.read_sizes), 65 + 1024)

    def test_samples_full_character_fields_and_honors_wide_field_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heritage.dbf"
            path.write_bytes(self._character_fields_dbf(
                [("A" * 24 + "구석기", "가상 유적")], "utf-8", widths=(300, 80),
            ))
            self.assertIsNone(infer_dbf_encoding(path, sample_size=32))
            path.write_bytes(self._character_fields_dbf(
                [("", "가상 유적")], "cp949", widths=(300, 80),
            ))
            self.assertEqual(infer_dbf_encoding(path, sample_size=32), "CP949")

    def test_valid_utf8_can_override_stale_korean_dbf_driver(self):
        with tempfile.TemporaryDirectory() as directory:
            shp_path = Path(directory) / "heritage.shp"
            dbf_path = shp_path.with_suffix(".dbf")
            dbf_path.write_bytes(self._character_fields_dbf(
                [("가상 유적",)], "utf-8", driver=0x79,
            ))
            self.assertEqual(infer_dbf_encoding(dbf_path), "UTF-8")
            shp_path.with_suffix(".cpg").write_text("UTF-8", encoding="ascii")
            self.assertEqual(declared_shapefile_encoding(shp_path), ("UTF-8", ".cpg"))

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
