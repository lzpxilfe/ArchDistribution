import csv
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.dom import minidom

from site_table import (
    build_site_table,
    compass_direction,
    drop_shared_province,
    format_distance,
    is_corrupted_text,
    parse_address_cell,
    summarize_address,
    summarize_periods,
    write_csv,
    write_hwpx,
)


class PeriodCellTests(unittest.TestCase):
    def test_aliases_children_and_unknowns(self):
        self.assertEqual(summarize_periods(["조선시대"]), "조선")
        self.assertEqual(summarize_periods(["삼국시대", "백제"]), "백제")
        self.assertEqual(
            summarize_periods(["고려시대", "조선", "시대미상"]), "고려·조선"
        )
        self.assertEqual(summarize_periods(["역사시대미상"]), "시대미상")
        self.assertEqual(summarize_periods(["기타"]), "시대미상")

    def test_only_unbroken_runs_become_ranges(self):
        self.assertEqual(
            summarize_periods(["삼국시대", "통일신라/발해시대", "고려시대", "조선시대"]),
            "삼국-조선",
        )
        self.assertEqual(
            summarize_periods(["청동기시대", "삼국시대", "고려시대", "조선시대"]),
            "청동기·삼국·고려·조선",
        )
        self.assertEqual(summarize_periods(["신라", "통일신라", "고려"]), "신라-고려")

    def test_parallel_and_sub_periods(self):
        self.assertEqual(summarize_periods(["통일신라시대", "발해시대"]), "통일신라·발해")
        self.assertEqual(summarize_periods(["조선시대 후기"]), "조선 후기")
        self.assertEqual(summarize_periods(["조선시대 후기", "조선시대"]), "조선")

    def test_unmapped_and_corrupted_labels(self):
        self.assertEqual(summarize_periods(["Bronze Age"]), "Bronze Age")
        self.assertEqual(summarize_periods(["怨??ㅼ????"]), "")
        self.assertTrue(is_corrupted_text("怨??ㅼ????"))
        self.assertFalse(is_corrupted_text("가상리 12-3번지?나상리 4"))


class AddressCellTests(unittest.TestCase):
    def test_enumerated_cells_and_separators_inherit_regions(self):
        entries = parse_address_cell(
            "0)가상도 가상군 가상면 가상리 12 일원,1)가상도 가상군 나상면 나상리 3"
        )
        self.assertEqual(
            [entry["places"][-1] for entry in entries], ["가상리", "나상리"]
        )
        entries = parse_address_cell("가상도 가상시 가상면 가상리 7-3번지?나상리 207 일원")
        self.assertEqual(entries[1]["places"], ("가상도", "가상시", "가상면", "나상리"))
        self.assertTrue(entries[1]["qualified"])

    def test_lot_variants(self):
        entry = parse_address_cell("가상도 가상군 가상면 가상리 445-21대?445-22")[0]
        self.assertEqual(entry["parcels"], ("445-21", "445-22"))
        entry = parse_address_cell("가상도 가상시 가상동 산44-1번지외 85필지")[0]
        self.assertEqual(entry["parcels"], ("산44-1",))
        self.assertEqual(entry["extra_parcels"], 85)
        entry = parse_address_cell("산 142-1 · 답 529-4 번지 일대")[0]
        self.assertEqual(entry["parcels"], ("산142-1", "529-4"))

    def test_region_levels_come_from_suffixes(self):
        entry = parse_address_cell("가상통합특별시 가상구 가상동 1")[0]
        self.assertEqual(entry["places"][0], "가상통합특별시")
        self.assertEqual(
            drop_shared_province(["가상통합특별시 가상구 가상동 1", "가상통합특별시 나상구"]),
            ["가상구 가상동 1", "나상구"],
        )

    def test_group_summary(self):
        self.assertEqual(
            summarize_address(["경북 가상시 가상동 320-1번지 일원", "가상시 가상동 321"],
                              preferred="경상북도 가상시 가상동 320-1"),
            "경상북도 가상시 가상동 320-1 외 1필지 일원",
        )
        self.assertEqual(
            summarize_address(["경상북도 가상시 가상동 320", "경상북도 가상시 나상동 12"]),
            "경상북도 가상시 가상동·나상동 일원",
        )
        self.assertEqual(
            summarize_address(["경상북도 가상시", "경상북도 가상시 가상동 1"]),
            "경상북도 가상시 가상동 1",
        )
        self.assertEqual(summarize_address([""]), "")


class TableTests(unittest.TestCase):
    groups = [
        {
            "number": 2, "name": "가상리 고분군",
            "address": "경상북도 가상시 가상리 산 12", "distance_m": 350,
            "direction": "북동", "roles": ["국가지정유산", "문화유적분포지도"],
            "designated": True,
            "records": [
                {"국가유산명": "가상리 고분군", "지정종목": "사적",
                 "시도명": "경상북도", "시군구명": "가상시"},
                {"명칭": "가상리 고분군", "시대": "0)삼국시대,1)신라",
                 "유적중분류": "0)무덤유적",
                 "소재지": "경상북도 가상시 가상리 산 12"},
            ],
        },
        {
            "number": 1, "name": "나상 유적 & <확인>",
            "address": "경상북도 가상시 나상동 1", "distance_m": 0,
            "direction": "", "roles": ["발굴조사"], "designated": False,
            "records": [
                {"유적명": "나상 유적", "시대": "0)청동기시대,1)조선시대",
                 "유적중분류": "0)생활유적",
                 "소재지": "경상북도 가상시 나상동 1 일원",
                 "조사기관": "가상연구원", "유적유무": "유적없음"},
            ],
        },
    ]

    def test_rows_follow_report_columns(self):
        header, rows = build_site_table(self.groups)
        self.assertEqual(header[:3], ["번호", "유적명", "시대"])
        self.assertEqual([row[0] for row in rows], ["1", "2"])
        first, second = rows
        self.assertEqual(first[2], "청동기·조선")
        self.assertEqual(first[4], "가상시 나상동 1 일원")
        self.assertEqual(first[5], "조사지역 내·접함")
        self.assertEqual(first[6], "발굴조사(가상연구원)")
        self.assertIn("유구 미확인", first[7])
        self.assertEqual(second[1], "가상리 고분군(사적)")
        self.assertEqual(second[2], "신라")
        self.assertEqual(second[3], "무덤유적")
        self.assertEqual(second[5], "북동 350m")
        self.assertIn("2건 통합", second[7])

    def test_distance_and_direction(self):
        self.assertEqual(compass_direction(1, 1), "북동")
        self.assertEqual(compass_direction(0, -5), "남")
        self.assertEqual(compass_direction(-3, 0, "en"), "W")
        self.assertEqual(format_distance(1234, "서"), "서 1.2km")
        self.assertEqual(format_distance(None), "")

    def test_hwpx_package_is_well_formed(self):
        header, rows = build_site_table(self.groups)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.hwpx"
            write_hwpx(str(path), header, rows, subtitle="가상 조사지역")
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                self.assertEqual(names[0], "mimetype")
                self.assertEqual(
                    archive.getinfo("mimetype").compress_type,
                    zipfile.ZIP_STORED,
                )
                self.assertEqual(
                    archive.read("mimetype"), b"application/hwp+zip"
                )
                for name in names:
                    if name.endswith((".xml", ".hpf")):
                        minidom.parseString(archive.read(name))
                section = archive.read("Contents/section0.xml").decode("utf-8")
            self.assertIn('rowCnt="3"', section)
            self.assertIn('repeatHeader="1"', section)
            self.assertIn("나상 유적 &amp; &lt;확인&gt;", section)

    def test_csv_has_bom_for_spreadsheets(self):
        header, rows = build_site_table(self.groups)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.csv"
            write_csv(str(path), header, rows)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with open(path, encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(len(list(csv.reader(handle))), 3)


if __name__ == "__main__":
    unittest.main()
