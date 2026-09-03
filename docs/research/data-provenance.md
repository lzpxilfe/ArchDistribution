# Data provenance and redistribution / 데이터 계보와 재배포

## English summary

ArchDistribution processes user-supplied heritage data but the research
repository does not redistribute national source layers or real-site
coordinates. Reproducibility metadata records source, acquisition date,
declared CRS, feature counts, bundle hashes, encodings, and terms of use.
Public validation uses synthetic fixtures only. A hash identifies the bytes
used in a run; it does not grant permission to redistribute them.

## 자료 등급

| 등급 | 예 | 저장소 정책 |
| --- | --- | --- |
| 코드·설정 | Python, UI, 규칙셋 | 명시된 오픈 라이선스로 공개 |
| 완전 합성 검증자료 | 인공 명칭·좌표·속성 | CC0-1.0으로 공개 가능 |
| 공개 집계 | 후보 유형별 건수, 비식별 성능값 | 민감성 검토 뒤 공개 |
| 사용자 공급 원자료 | 전국 `sites`, 기관별 SHP/DBF | 커밋·Release 첨부 금지 |
| 파생 민감자료 | 실제 후보쌍, 실제 좌표가 있는 스크린샷 | 비공개; 공개본은 비식별화 |

## 입력 자료 기록

실행 manifest schema v2는 입력 레이어마다 다음을 기록한다.

- 자료 역할과 표시용 출처명
- 취득일 또는 사용자가 확인한 기준일
- 공급자가 선언한 CRS와 분석에 사용한 CRS
- 형상 유형, 수집 건수, 제외 건수
- 파일 묶음 단위 SHA-256과 묶음 구성 확장자
- `.cpg` 또는 공급자에서 확인한 인코딩과 사용자 재지정 여부
- geometry 복구 건수와 제외 사유
- 알려진 이용조건 또는 `unknown-needs-review`

공개 manifest에는 절대경로, 사용자명, 내부 서버명, 개인 식별값을 넣지 않는다.
로컬 원본 식별이 필요하면 별도의 비공개 manifest를 사용하고 공개본과 해시로
연결한다.

## 파일 묶음 해시

Shapefile은 `.shp`만이 아니라 `.shx`, `.dbf`, `.prj`, `.cpg` 등 같은 basename의
구성 파일을 정렬한 뒤 각 파일 해시와 전체 묶음 해시를 기록한다. ZIP은 원본 ZIP
해시와 안전하게 해제한 구성 파일 해시를 구분한다. 경로와 수정시간은 내용 해시에
포함하지 않는다.

## 인코딩

주 처리 경로는 DBF 문자 레코드의 고신뢰도 판정과 `.cpg`·데이터 공급자 설정을
사용하며 모든 레이어에 CP949를 일괄 강제하지 않는다. 자료 역할 표와 매장유산 작업 흐름에서 레이어별로 공급자
설정을 유지하거나 UTF-8/CP949를 명시적으로 선택할 수 있다. 깨진 필드명이
감지되면 DBF의 문자형 레코드만 검사해 UTF-8과 CP949를 판별하고, CP949가
고신뢰도로 확인된 Shapefile은 속성 검사 전에 공급자를 다시 읽는다. 원본 파일은
수정하지 않는다. 명시적인 레이어별 선택값은 자동 판정보다 우선하며 선택값과
판독 근거는 실행 설정·manifest에 남기고 정규화 문자열뿐 아니라 원문도 보존한다.

## 기준자료와 분류 사전

`reference_data.json`, 명칭 정규화 사전, 역할 분류표에는 생성 출처, 생성일,
버전, 라이선스, 내용 해시가 필요하다. 현재 확인된 파일 해시와 미확인 항목은
`reference-data-register.json`에 기록한다. 재배포 근거가 확인되지 않은 항목은
연구 Release에서 제외하고 사용자 공급 선택 자료로 전환한다. 출처가 불명확한
데이터가 코드 저장소에 존재한다는 사실만으로 공개 허가를 추정하지 않는다.
`create_zip.py`는 등록부의 `joss_release_approved`가 명시적으로 `true`인 루트
자산만 설치 ZIP에 넣으며, 등록부 누락·파싱 실패·미승인은 모두 제외로 처리한다.
다만 기존 사용자의 QGIS 플러그인 백업에 등록부 해시와 정확히 일치하는 파일이
남아 있으면 런타임에서 그 로컬 파일을 직접 다시 연결할 수 있다. 이 경로는 파일을
복사하거나 Release에 포함하지 않으며, 해시가 다른 백업은 자동으로 읽지 않는다.

## 삭제와 보존

플러그인은 원본 파일을 수정하거나 삭제하지 않는다. 대표에서 제외된 기록도
보존 레이어, 검토 표, source JSON을 통해 추적 가능해야 한다. 연구자료 보존기간과
실제 원자료의 접근권한은 자료 제공기관 규정에 따르며, Zenodo에는 재배포 가능한
코드·문서·합성자료·집계만 보존한다.

## Pending register

- 전국 자료별 정확한 공급기관·취득일·이용조건 확인: **pending**
- `reference_data.json` 각 항목의 재배포 근거 감사: **pending**
- 공개 가능한 비식별 파일럿 집계의 disclosure review: **pending**
