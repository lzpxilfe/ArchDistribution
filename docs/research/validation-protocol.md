# Validation protocol / 검증 프로토콜

## English summary

Validation has three layers: deterministic tests on openly distributable
synthetic data, a blinded single-reviewer pilot on non-redistributed real
candidate pairs, and installation/usability checks. The pilot and external
test are **pending**. No accuracy, time-saving, or cross-institutional
generalization claim may be made until the preregistered thresholds below are
met and the results are committed as non-sensitive aggregates.

## 공개 합성 검증

완전 합성한 좌표·명칭·속성만 저장소에 커밋한다. Golden case는 다음을 포함한다.

- EPSG:4326, 5179, 5186 및 피트 단위 CRS에서 동일한 실제 도곽·버퍼·거리
- 같은 사업의 서로 다른 유적: 같은 번호, 다른 실체, 같은 조사사건
- 지정+분포, 발굴+분포, 지정+발굴, 지표조사 별도 유지
- 상위 유적과 부속 유산 자동 병합 금지
- 보호구역 무번호, 보존조치별 형상 유지, 도곽 미세조각 제외
- 점·선·면 혼합, 잘못된 geometry, UTF-8·CP949, 중복 ZIP·레이어
- 취소, 부분 실패, 결정 재사용, 재번호, 원본 보존
- 같은 입력·규칙·결정에서 정규화 내용 해시 재현

허용오차는 도곽 치수 0.01 m, 버퍼 거리 0.1 m, CRS 간 버퍼 면적 차이 0.5%
이내다. 합성 사례에서 오병합과 원본 소거는 0건이어야 한다.

## 1인 파일럿: pending

실제 후보 300쌍을 동일 사업이 양쪽에 섞이지 않도록 사업 단위로 분할한다.

- 개발 집합: 200쌍. 규칙과 임계값 조정에 사용.
- 잠금 평가 집합: 100쌍. 개발 종료 뒤 한 번 평가.
- 라벨: `same_entity`, `related_separate`, `unrelated`, `uncertain`.
- 블라인딩: 플러그인 추천과 점수를 숨긴 상태에서 사람이 먼저 판정.

평가 지표는 자동병합 정밀도, 전체 동일실체 후보 재현율, 사람 검토 전환율,
오병합·누락의 오류 유형이다. 자동병합 정밀도 < 0.98 또는 후보 재현율 < 0.95면
`joss-v1.0.5` 연구 릴리스를 보류한다. `uncertain`은 강제로 정답으로 바꾸지 않고
별도로 집계한다. 잠금 평가 뒤 규칙을 변경하면 결과를 폐기하고 새 버전으로 다시
분할·평가한다.

단일 평가자 파일럿은 평가자 간 일치도를 측정하지 못한다. 따라서 결과는
재현성·위험 통제의 초기 증거이며 일반적인 고고학적 정확도의 확증이 아니다.

## 실제 작업 관찰: pending

익명화 가능한 실제 작업 3건에서 입력 규모, 실행시간, 후보 수, 사람 수정 수,
오류, 취소·재실행을 기록한다. 수작업 기준시간이 당시 기록되어 있을 때만 비교하고,
사후 추정시간으로 생산성 향상을 주장하지 않는다. 위치, 기관 내부 식별자, 개인
정보는 공개 결과에서 제거한다.

## 설치·사용성 시험: pending

최소 한 명의 외부 GIS 사용자가 깨끗한 QGIS 프로필에서 ZIP 설치, 합성 예제 실행,
결과 확인을 수행한다. 운영체제·QGIS 버전·실패 지점·도움말 의존·수정사항을
템플릿에 기록한다. 저자가 대신 조작한 시연은 외부 시험으로 간주하지 않는다.

## 성능 검증

100,000건 이상의 합성 피처에서 공간 인덱스 후보화가 전수 조합 비교를 피하는지
검증한다. 데이터 생성 seed, CRS, 형상 분포, 후보 밀도, CPU, 메모리, QGIS 버전,
실행시간을 함께 공개한다. 절대 시간만으로 합격시키지 않고 메모리 오류 없이
완료되고 비교 횟수가 전수 조합보다 충분히 작다는 구조적 조건을 확인한다.

## 승인과 결과 기록

각 검증 결과에는 실행일, Git commit, 규칙셋 버전·해시, 환경, 입력 해시, 실행
명령, 상태, 산출물 해시, 검토자 서명을 남긴다. 실패 결과도 삭제하지 않고
`validation/results/`의 상태표에 남긴다. 실제 후보 원문은 공개 저장소에 올리지
않고 비식별 집계와 검증 가능한 절차만 공개한다.
