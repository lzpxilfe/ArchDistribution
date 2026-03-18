<p align="center">
  <img src="icon.png" width="96" alt="ArchDistribution icon">
</p>

<h1 align="center">🏺 ArchDistribution</h1>

<p align="center">
  고고학 분포지도 제작을 빠르게 정리하는 QGIS 플러그인<br>
  A QGIS plugin for fast archaeological distribution map production
</p>

<p align="center">
  <img alt="QGIS 3.28-3.99" src="https://img.shields.io/badge/QGIS-3.28--3.99-589632?logo=qgis&logoColor=white">
  <img alt="Version 1.0.4" src="https://img.shields.io/badge/version-1.0.4-0ea5e9">
  <img alt="License GPL v2" src="https://img.shields.io/badge/license-GPL%20v2-f59e0b">
</p>

## ✨ 프로젝트 한눈에 보기 | At a Glance

| 항목 | 내용 |
|---|---|
| 현재 버전 | `1.0.4` |
| 지원 QGIS | `3.28` - `3.99` |
| 지원 언어 | `자동(QGIS)` / `한국어` / `English` |
| 주요 입력 | 조사구역, 수치지형도, 주변유적, 선택적 Zone 레이어 |
| 주요 출력 | `ArchDistribution_결과물` 그룹, 스타일링된 결과 레이어, `latest_log.txt` |
| 배포 방식 | QGIS ZIP 설치 또는 플러그인 폴더 수동 배치 |

## 🧭 프로젝트 소개 | Overview

**KR**  
ArchDistribution는 고고학 분포지도 제작 과정에서 반복적으로 수행하는 정리 작업을 줄이기 위해 만든 QGIS 플러그인입니다.  
조사구역 기준 버퍼 생성, 주변유적 병합, 번호 부여, Zone 처리, 스타일 적용, 로그 저장까지 한 흐름으로 처리할 수 있도록 구성되어 있습니다.

**EN**  
ArchDistribution is a QGIS plugin built to reduce repetitive GIS work in archaeological distribution mapping.  
It streamlines buffering, heritage-layer merging, numbering, zone processing, styling, and logging in one workflow.

## 🚀 현재 제공 기능 | Current Features

**KR**
- `조사구역 / 수치지형도 / 주변유적 / Zone` 레이어를 한 화면에서 선택
- 다중 버퍼 거리 입력 및 버퍼 라인 스타일 지정
- 주변유적 병합 후 자동 번호 부여
- `거리순 / 북→남 / 가나다순` 정렬 기준 선택
- 버퍼 밖 유적 숨김 처리와 연속 번호 재정렬
- `번호 새로고침 (현재 레이어)` 기능으로 수정 후 즉시 재번호
- Zone 레이어 자동 분할 및 코드별 스타일 적용
- `버퍼 범위 내 자르기` 옵션으로 Zone 결과를 최대 버퍼 내부로 제한
- `reference_data.json` + `smart_patterns.json` 기반 속성 분류 및 제외 제안
- `자동(QGIS) / 한국어 / 영어` UI 전환 즉시 반영
- 실행 로그를 QGIS 화면과 `latest_log.txt`에 함께 저장
- 작업 완료 후 결과 범위로 자동 확대

**EN**
- Select study area, topographic, heritage, and optional zone layers in one dialog
- Configure multiple buffer distances and buffer line styles
- Merge heritage layers and assign numbers automatically
- Choose sort order: distance, north-to-south, or alphabetical
- Hide sites outside the outermost buffer and keep numbering continuous
- Refresh numbering on the active layer after edits or deletions
- Split and style zone layers automatically by zone code
- Optionally clip zone output to the largest survey buffer
- Use `reference_data.json` and `smart_patterns.json` for smart classification and exclusion hints
- Switch UI instantly between `Auto (QGIS)`, `Korean`, and `English`
- Save progress logs in both QGIS and `latest_log.txt`
- Auto-zoom to the output extent after processing

## 🗂️ 기본 사용 흐름 | Typical Workflow

**KR**
1. QGIS에 조사구역, 수치지형도, 주변유적 레이어를 불러옵니다.
2. 필요하다면 현상변경 허용기준(Zone) 레이어도 함께 준비합니다.
3. `ArchDistribution`를 실행하고 데이터 탭에서 입력 레이어를 선택합니다.
4. 도곽 크기, 축척, 버퍼 거리, 스타일, 정렬 방식을 설정합니다.
5. `속성 분류 실행`으로 시대/성격 후보와 제외 제안 목록을 확인합니다.
6. `▶ 분석 및 지도 생성 실행`으로 결과를 생성합니다.
7. 편집 후에는 `🔄 번호 새로고침 (현재 레이어)`으로 번호를 다시 정리합니다.

**EN**
1. Load study area, topographic, and heritage layers in QGIS.
2. Prepare an optional zone layer if needed.
3. Open `ArchDistribution` and select input layers on the Data tab.
4. Configure paper size, scale, buffers, styles, and sort order.
5. Run `Attribute Scan` to review classification and exclusion suggestions.
6. Click `Run Analysis / Generate Map`.
7. If you edit results later, use `Refresh numbering (active layer)`.

## 📦 설치 방법 | Installation

### 1) ZIP 설치 (권장) | Install from ZIP (Recommended)

**KR**
1. 플러그인 ZIP 파일을 준비합니다.
2. QGIS에서 `Plugins -> Manage and Install Plugins -> Install from ZIP`으로 이동합니다.
3. ZIP을 선택해 설치합니다.
4. 플러그인 목록에서 `ArchDistribution`를 활성화합니다.

**EN**
1. Prepare the plugin ZIP package.
2. In QGIS, open `Plugins -> Manage and Install Plugins -> Install from ZIP`.
3. Select the ZIP file and install it.
4. Enable `ArchDistribution` in the plugin list.

### 2) 수동 설치 | Manual Install

**KR / EN**  
`ArchDistribution` 폴더를 아래 경로에 복사한 뒤 QGIS를 다시 시작합니다.

`.../QGIS/QGIS3/profiles/default/python/plugins/ArchDistribution`

## 🛠️ 개발 및 배포 | Development & Release

현재 저장소에는 ZIP 생성과 기본 검증을 위한 스크립트가 포함되어 있습니다.

```bash
python -m py_compile arch_distribution.py arch_distribution_dialog.py
python verify_guardrails.py
python create_zip.py
```

**KR**
- `create_zip.py`는 `metadata.txt`의 버전을 읽어 `~/Desktop/ArchDistribution-1.0.4.zip` 형태로 패키징합니다.
- ZIP 내부 루트는 반드시 `ArchDistribution/` 폴더 1개만 들어가도록 구성됩니다.
- 배포용 ZIP에는 플러그인 런타임에 필요한 추적 파일만 포함됩니다.

**EN**
- `create_zip.py` reads the version from `metadata.txt` and builds `~/Desktop/ArchDistribution-1.0.4.zip`.
- The archive is created with a single top-level `ArchDistribution/` folder for QGIS compatibility.
- Only tracked runtime files needed by the plugin are packaged.

## 🎨 결과 확인과 PDF 반출 팁 | Output & Export Tips

**KR**
- 결과는 QGIS 레이어 패널의 `ArchDistribution_결과물` 그룹 아래에 정리됩니다.
- 화면이 비어 보이면 그룹 가시성을 확인하고 `레이어로 확대`를 시도해 주세요.
- Illustrator 작업이 필요하면 지형도, 유적, 버퍼 등을 하나씩만 켜서 각각 PDF로 저장한 뒤 합치는 방식이 편합니다.

**EN**
- Outputs are grouped under `ArchDistribution_결과물` in the QGIS layer panel.
- If nothing is visible, check layer visibility and try `Zoom to Layer`.
- For Illustrator workflows, exporting separate PDFs by layer visibility often makes editing easier.

## 🌐 언어 지원 | Language Support

**KR**
- `자동(QGIS)`, `한국어`, `영어`를 수동으로 전환할 수 있습니다.
- 전환 즉시 현재 대화상자에 반영됩니다.
- 원본 SHP/GPKG 속성값은 번역되지 않으며 그대로 유지됩니다.

**EN**
- Manual switch is available for `Auto (QGIS)`, `Korean`, and `English`.
- Changes apply immediately in the current dialog.
- Source SHP/GPKG attributes are not translated or modified.

## 🧯 문제 해결 | Troubleshooting

**KR**
- 업데이트가 반영되지 않으면 플러그인을 비활성화했다가 다시 활성화하거나 QGIS를 재시작해 주세요.
- ZIP 설치 오류가 나면 ZIP 루트 구조에 `ArchDistribution/metadata.txt`가 있는지 확인해 주세요.
- 실행 중 문제가 생기면 플러그인 폴더의 `latest_log.txt`를 먼저 확인해 주세요.
- 번호 새로고침은 현재 설정된 축척과 범위를 기준으로 동작하므로, 실행 전 축척을 꼭 확인해 주세요.

**EN**
- If updates are not reflected, disable and re-enable the plugin or restart QGIS.
- If ZIP installation fails, verify that the archive contains `ArchDistribution/metadata.txt`.
- Check `latest_log.txt` in the plugin folder when runtime issues occur.
- Refresh numbering uses the current scale and extent, so verify the map scale before running it.

## ⚠️ 면책 | Disclaimer

**KR**  
본 플러그인은 좌표계 변환, 데이터 병합, 스타일링, 번호 부여 같은 실무 작업을 빠르게 돕는 도구입니다.  
최종 제출 전에는 위치, 속성, 번호, 도면 표현을 반드시 직접 검수해 주세요.

**EN**  
This plugin is designed to speed up practical tasks such as CRS handling, layer merging, styling, and numbering.  
Always review final geometry, attributes, numbering, and cartographic output before official use.

## 📚 Citation

```bibtex
@software{ArchDistribution2026,
  author = {lzpxilfe},
  title = {ArchDistribution: Automated QGIS plugin for archaeological distribution maps},
  year = {2026},
  url = {https://github.com/lzpxilfe/ArchDistribution},
  version = {1.0.4}
}
```

## ℹ️ 프로젝트 정보 | Project Info

- Version: `1.0.4`
- Author: `lzpxilfe (balguljang2)`
- Repository: [github.com/lzpxilfe/ArchDistribution](https://github.com/lzpxilfe/ArchDistribution)
- Issues: [github.com/lzpxilfe/ArchDistribution/issues](https://github.com/lzpxilfe/ArchDistribution/issues)
- License: `GPL v2`
