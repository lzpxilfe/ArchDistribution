# ArchDistribution Update Guardrails

이 문서는 버전 업데이트 시 "절대 흔들리면 안 되는 틀"을 고정하기 위한 기준서입니다.
목표는 기능 개선을 하더라도 사용자 체감 UI/작업 흐름의 일관성을 유지하는 것입니다.

## 1) Non-Negotiable Principles (변경 금지 원칙)

- UI 기본 골격은 `arch_distribution_dialog_base.ui` 기준을 유지한다.
- 언어 전환(KR/EN)은 텍스트/툴팁만 바꾼다. 레이아웃 폭/높이/배치는 바꾸지 않는다.
- 사용자가 익숙한 입력 흐름(레이어 선택 -> 스타일/분석 -> 실행)은 순서를 바꾸지 않는다.
- 기본값(색상/버퍼/축척/라벨) 변경은 "사용자 요청 + 릴리즈 노트 명시"가 있을 때만 한다.
- 릴리즈 직전에는 반드시 1.0.1 기준 동작과 비교 확인한다.

## 2) UI Frame Lock (레이아웃 고정 규칙)

- 입력영역(조사지역/수치지형도/주변유적) 폭은 `.ui` 기본 레이아웃을 사용한다.
- 다음 형태의 런타임 레이아웃 강제 코드는 금지한다.
- `gData.setColumnStretch(...)`
- `gData.setColumnMinimumWidth(...)`
- `comboStudyArea/listTopoLayers/listHeritageLayers`에 `setMinimumWidth(...)` 강제
- `ld1u`에 폭 제한/줄바꿈 강제
- 예외: 선택 버튼 4개(`btnCheckTopo`, `btnUncheckTopo`, `btnCheckHeritage`, `btnUncheckHeritage`)는 과도 확장 방지를 위한 compact 정책 허용

## 3) Versioning Rules (버전 규칙)

- 배포 버전은 `metadata.txt`의 `version=`을 단일 진실원(source of truth)으로 사용한다.
- `README.md`의 제목/버전 표기와 `metadata.txt` 버전을 항상 동기화한다.
- QGIS 배포 전 ZIP 구조를 검증한다.
- ZIP 루트는 반드시 `ArchDistribution/` 폴더 1개여야 한다.
- `ArchDistribution/metadata.txt` 존재를 필수 확인한다.

## 4) Pre-Release Checklist (출시 전 체크리스트)

- `python -m py_compile arch_distribution.py arch_distribution_dialog.py` 통과
- `python test_filtering_logic.py` 통과
- `python verify_guardrails.py` 통과
- QGIS에서 1회 수동 스모크 테스트
- KR/EN 전환 시 UI 깨짐 여부 확인
- 입력 3개 칸 폭(조사지역/수치지형도/주변유적) 시각 확인
- 선택 버튼 4개 과도 확장 여부 확인
- `latest_log.txt` 오류 유무 확인
- 업로드 ZIP 구조 검증

## 5) Regression Reference (회귀 비교 기준)

- 기능/동작 비교 기준: `1.0.1/` 폴더
- UI 틀 비교 기준: `1.0.1/arch_distribution_dialog_base.ui`
- 업데이트 시 "변경 의도 없음" 영역은 기존과 동일해야 한다.

## 6) Change Policy (변경 정책)

- 기존 UI 틀을 건드리는 변경은 "사전 합의" 없이는 금지한다.
- UI 틀 변경이 꼭 필요하면 다음을 필수로 남긴다.
- 변경 이유
- 영향 범위
- 되돌리기 방법
- 사용자 안내 문구
