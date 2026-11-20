# ArchDistribution

**조사구역 주변의 유적과 조사 기록을 검토하고, 번호가 붙은 지도와 현황표를 만드는 QGIS 플러그인입니다.**

조사구역 폴리곤과 보유한 문화유산 레이어를 불러오세요. 도곽에 들어오는 기록을 모아 같은 유적을 가리킬 수 있는 후보를 보여주고, 검토한 내용을 지도 번호와 현황표에 반영합니다.

Version: `1.0.6` · QGIS `3.40` 이상

[설치](#설치) · [예제로 실행하기](#예제로-실행하기) · [사용 안내](docs/user-guide.md) · [English](docs/README.en.md)

## 설치

QGIS에서 **플러그인 → 플러그인 관리 및 설치**를 열고 **ArchDistribution**을 검색합니다. 설치한 뒤 도구 모음의 **ArchDistribution** 아이콘을 누릅니다. [QGIS 공식 플러그인 페이지](https://plugins.qgis.org/plugins/ArchDistribution/)

<details>
<summary>소스에서 설치 ZIP 만들기</summary>

저장소를 내려받고 루트 폴더에서 `python create_zip.py`를 실행합니다. 바탕화면에 생성된 `ArchDistribution-1.0.6.zip`을 QGIS의 **ZIP 파일에서 설치**로 엽니다.

</details>

## 예제로 실행하기

[예제 GeoPackage 다운로드](examples/quick-start.gpkg?raw=true) · [배경 GeoTIFF 다운로드](examples/quick-start-hillshade.tif?raw=true) (선택)

![QGIS에서 조사구역과 유적 레이어를 선택하고 500 m 버퍼를 추가해 번호가 붙은 지도를 만드는 과정](docs/media/quick-start.gif)

1. GeoPackage를 QGIS에 불러와 `가상 조사구역`과 `가상 유적분포지도`를 추가합니다. 배경도 열었다면 레이어 목록 맨 아래에 놓습니다.
2. ArchDistribution의 **데이터·도곽**에서 조사구역을 선택하고 유적 레이어를 체크합니다. 축척은 **1:25,000**으로 설정합니다.
3. **스타일·분석**의 버퍼 거리에 `500`을 입력하고 **추가 (+)**를 누릅니다. 파일도 필요하면 **파일 저장**에서 폴더와 형식을 고릅니다.
4. **분포지도 만들기**를 누릅니다. 중복 검토 창이 열리면 후보를 확인한 뒤 진행하고, QGIS의 `ArchDistribution_결과물` 그룹에서 지도 번호를 확인합니다.

예제의 조사구역과 유적은 가상입니다. 배경은 실제 Copernicus DEM에서 만든 음영기복도입니다. [예제 배경 출처](docs/user-guide.md#예제-지형-출처)

## 내 자료로 작업하기

- **기록 검토** — 같은 장소에 여러 기록이 있으면 **별도 유지**, **연결만**, **대표 번호로 묶기**를 선택합니다. 관계만 기록하면 각 번호를 유지하고, 대표 번호로 묶으면 원자료를 보존하면서 지도에 같은 번호를 씁니다.
- **법정 레이어와 보존조치** — 지정유산·보호구역·현상변경 허용기준은 해당 레이어를 지정해 표시합니다. **매장유산 유존지역** 탭에서는 별도로 보존조치별 도면을 만듭니다.
- **성과물 저장** — GeoPackage와 실행정보(JSON)에 결과 레이어·검수표·실행 설정을 남깁니다. 인쇄용 지도는 PDF·JPG, 주변유적 현황표는 HWPX·CSV로 저장할 수 있습니다.

버퍼는 분석 거리를 정하고, 법정 구역 경계는 입력 레이어에서 가져옵니다. 도형 중첩은 중복 검토의 근거 중 하나입니다. 제출용 지도와 현황표는 원자료와 대조해 확인하세요. [판정과 출력 안내](docs/user-guide.md)

## 변경 기록과 참고 자료

1.0.6에서는 기본 설정 화면을 간소화하고 영어 안내를 보강했습니다. 이전 버전의 중복 검토 결정을 다시 분석에 적용할 때는 변경된 판정 규칙에 따라 재확인합니다. [변경 기록](CHANGELOG.md)

[검증 기록](validation/results/status.md) · [문제 제보](https://github.com/lzpxilfe/ArchDistribution/issues) · [기여 안내](CONTRIBUTING.md) · [라이선스](LICENSES.md)

<details>
<summary>인용 정보</summary>

[CITATION.cff](CITATION.cff)

```bibtex
@software{ArchDistribution2026,
  author = {{lzpxilfe(balguljang2)}},
  title = {ArchDistribution: A QGIS plugin for reconciling and mapping archaeological spatial records},
  year = {2026},
  url = {https://github.com/lzpxilfe/ArchDistribution},
  version = {1.0.6}
}
```

</details>
