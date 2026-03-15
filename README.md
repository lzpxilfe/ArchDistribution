# ArchDistribution

## 프로젝트 소개 | Overview

**KR**  
ArchDistribution는 고고학 분포지도 제작을 빠르게 수행하기 위한 QGIS 플러그인입니다.  
레이어 선택, 버퍼 생성, 번호 부여, 존(Zone) 처리, 스타일 적용 등 반복 작업을 줄여 실무 생산성을 높이는 데 초점을 맞췄습니다.

**EN**  
ArchDistribution is a QGIS plugin for fast archaeological distribution map production.  
It reduces repetitive GIS work such as layer selection, buffer generation, numbering, zone handling, and map styling.

## 주요 기능 | Core Features

1. **자동 지도 준비 | Automated map preparation**  
   KR: 조사구역/수치지형도/유적/선택 존 레이어를 입력받아 도면 준비를 자동화합니다.  
   EN: Automates map preparation from study area, topographic, heritage, and optional zone layers.

2. **버퍼/번호 부여 | Buffer and numbering workflow**  
   KR: 다중 버퍼 거리 생성, 라인 스타일 지정, 정렬 기준에 따른 자동 번호 부여를 지원합니다.  
   EN: Supports multi-distance buffers, line styling, and auto numbering by selectable order.

3. **존 기반 처리 | Zone-based processing**  
   KR: 버퍼 기준 클리핑, 버퍼 외 유적 제외(옵션), 구역 분리 스타일링을 지원합니다.  
   EN: Supports buffer-based clipping, optional exclusion outside buffer, and split-zone styling.

4. **속성 분류 보조 | Smart attribute assistance**  
   KR: 레이어 명칭 패턴 기반으로 분류 보조 및 제외 후보 제안을 제공합니다.  
   EN: Provides pattern-based classification aid and suggested exclusion candidates.

5. **실무형 UX | Practical UX**  
   KR: 진행 로그, `latest_log.txt` 저장, 긴 화면용 스크롤 UI를 제공합니다.  
   EN: Includes progress logs, `latest_log.txt`, and a scroll-friendly long-form UI.

## 언어 지원 | Language Support

**KR**
- `자동(QGIS)`, `한국어`, `영어` 수동 전환 지원
- 전환 즉시 현재 대화상자에 반영
- 원본 SHP/GPKG 속성값은 변경하지 않음

**EN**
- Manual switch: `Auto (QGIS)`, `Korean`, `English`
- Applied immediately in the current dialog
- Does not modify your source SHP/GPKG attributes

## 요구 사항 | Requirements

- QGIS 3.28 or newer
- SHP/GPKG/기타 벡터 입력 데이터

## 설치 방법 | Installation

### 1) ZIP 설치 (권장) | Install from ZIP (Recommended)

**KR**
1. 플러그인 ZIP 파일을 준비합니다.
2. QGIS에서 `Plugins -> Manage and Install Plugins -> Install from ZIP` 이동
3. ZIP 선택 후 설치
4. 플러그인 목록에서 `ArchDistribution` 활성화

**EN**
1. Prepare the plugin ZIP package.
2. In QGIS, open `Plugins -> Manage and Install Plugins -> Install from ZIP`.
3. Select the ZIP and install.
4. Enable `ArchDistribution` in plugin list.

### 2) 수동 설치 | Manual Install

**KR / EN**  
`ArchDistribution` 폴더를 아래 경로에 복사 후 QGIS 재시작(또는 Plugin Reloader):

`.../QGIS/QGIS3/profiles/default/python/plugins/ArchDistribution`

## 기본 사용 흐름 | Typical Workflow

**KR**
1. QGIS에 입력 레이어 로드
2. `ArchDistribution` 실행
3. 레이어/축척/스타일/버퍼 옵션 설정
4. 분석 및 지도 생성 실행
5. 결과 그룹과 로그 확인

**EN**
1. Load input layers in QGIS
2. Open `ArchDistribution`
3. Configure layer/scale/style/buffer options
4. Run analysis and map generation
5. Review output groups and logs

## 문제 해결 | Troubleshooting

**KR**
- 업데이트 후 반영이 안 되면 QGIS 재시작 + 플러그인 캐시 정리
- ZIP 설치 오류 시 ZIP 루트 구조 확인  
  (루트에 `ArchDistribution` 폴더가 있고 그 안에 `metadata.txt` 존재)
- 런타임 오류는 플러그인 폴더의 `latest_log.txt` 확인

**EN**
- If update is not reflected, restart QGIS and clear plugin cache
- If ZIP install fails, verify package structure  
  (ZIP root must contain `ArchDistribution/`, and inside it `metadata.txt`)
- Check `latest_log.txt` for runtime errors

## 면책 | Disclaimer

**KR**  
본 플러그인은 업무 보조 도구이며 법적 효력을 보장하지 않습니다.  
공식 제출 전 최종 결과를 반드시 검수하세요.

**EN**  
This plugin is a production aid and does not guarantee legal validity.  
Always review outputs before official submission.

## Citation

```bibtex
@software{ArchDistribution2026,
  author = {lzpxilfe},
  title = {ArchDistribution: Automated QGIS plugin for archaeological distribution maps},
  year = {2026},
  url = {https://github.com/lzpxilfe/ArchDistribution},
  version = {1.0.4}
}
```

## 프로젝트 정보 | Project Info

- Version: `1.0.4`
- Author: `lzpxilfe (balguljang2)`
- Repository: `https://github.com/lzpxilfe/ArchDistribution`
- License: `GPL v2`
