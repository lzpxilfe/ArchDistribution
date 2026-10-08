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

## 7) UI 변경 기록 (Change Records)

### Unreleased — 작업 순서에 맞춘 섹션 배치

- 변경 이유: 사용자 요청("GUI가 헷갈리지 않는지 고려해서 잘 배치")에 따른
  사전 합의 변경. 중복 판정과 기록 제외 규칙이 늘어나면서 데이터 탭과 스타일
  탭의 섹션이 결정 순서와 어긋나 있었고, 규칙 체크박스(`도곽 미세 조각 제외`,
  `버퍼 밖 숨김`)가 그 규칙이 의존하는 설정과 떨어져 있었다.
- 영향 범위:
  - `.ui` 파일과 입력영역(`gData`) 폭·열 설정은 바꾸지 않았다. 런타임에서
    `_arrange_sections_by_workflow()`가 그룹 상자의 세로 순서만 바꾼다.
  - 데이터 탭: 입력 레이어 → 자료 역할 및 중복 판정 → 지정·보호구역 →
    유적 속성 분류 및 제외 → 도곽(판형·축척, `chkExcludeExtentSlivers` 포함).
  - 스타일 탭: 심볼 → 라벨 → 버퍼(`chkRestrictToBuffer` 포함) → 번호 정렬 →
    기존 결과 후속 작업.
  - `btnRenumber`(현재 레이어 번호 재정렬)는 숨김. 같은 기능은 호환 결과만
    나열하는 `기존 결과 후속 작업` 카드가 담당한다.
  - 입력 레이어 목록은 이름 대신 플러그인 결과 그룹 소속으로 이전 결과를
    거르며, 조사구역은 이름·형태로 추천한다.
  - 위젯 객체·시그널·QSettings 키는 그대로이므로 저장된 설정은 유지된다.
  - 레이어 선택 → 스타일/분석 → 실행의 큰 흐름은 바뀌지 않는다.
- 되돌리기 방법: `ArchDistributionDialog.__init__`에서
  `_arrange_sections_by_workflow()` 호출 한 줄을 지우면 `.ui` 기본 배치로
  돌아가고 `btnRenumber`도 다시 보인다.
- 사용자 안내 문구: "데이터 탭과 스타일 탭은 위에서 아래로 결정 순서대로
  놓였습니다. 규칙 체크박스는 해당 설정 옆으로 옮겼고, 번호 재정렬은 스타일 탭
  맨 아래 `기존 결과 후속 작업`에서 합니다." (README `기본 사용 흐름`과 도움말에
  반영)
