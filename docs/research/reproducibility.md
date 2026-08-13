# Reproducibility guide / 재현성 안내

## English summary

A reproducible ArchDistribution run binds a Git commit, plugin version,
rule-set hash, QGIS/GDAL/GEOS/PROJ environment, input bundle hashes, explicit
review decisions, and normalized output hashes. Public reproduction uses
synthetic fixtures; restricted source data are verified locally by hash and
are not redistributed. Time stamps and absolute paths are excluded from the
deterministic content digest.

## 재현 단위

재현의 최소 단위는 ZIP 파일 하나가 아니라 다음 항목의 묶음이다.

- Git commit과 플러그인 버전 `1.0.5`
- 규칙셋 버전과 SHA-256
- QGIS, Qt, Python, GDAL, GEOS, PROJ, 운영체제 버전
- 입력 파일 묶음 해시와 레이어 역할·인코딩
- 분석 CRS 선택과 좌표 변환 과정
- 사용자 검토 결정 또는 결정 캐시 해시
- 실행 상태와 제외 사유
- 시간·절대경로를 제외한 정규화 결과 내용 해시

## 공개 합성 실행

1. 저장소를 특정 commit으로 checkout한다.
2. 해당 commit의 설치 ZIP을 만들고 깨끗한 QGIS 프로필에 설치한다.
3. `validation/fixtures/`의 합성자료와 고정 규칙셋을 선택한다.
4. 템플릿에 지정된 CRS·도곽·버퍼·프리셋을 그대로 사용한다.
5. 검토 결정 fixture를 불러오거나 문서화된 선택을 수행한다.
6. 결과 manifest와 `validation/expected/`의 구조·해시·허용오차를 비교한다.
7. 같은 입력으로 다시 실행해 정규화 내용 해시가 같은지 확인한다.

fixture별 실행 명령은 각 README에 고정한다. 현재 비어 있는 fixture는 통과
사례로 간주하지 않는다. 공간 인덱스 성능만 별도로 재현하려면 QGIS Python에서
`python validation/benchmark_spatial_index.py --features 100000`을 실행한다.
초기 13개 정책 fixture는 일반 Python에서
`python validation/run_synthetic_policy.py`로 재현한다.

## 결정론적 해시

정규화 digest에는 의미 있는 geometry, 정렬된 속성, 판정 관계, 규칙셋 해시를
포함한다. 다음은 제외한다.

- 실행 시작·종료 시각
- 임시·절대 파일경로와 사용자명
- 레이어 내부의 비결정적 feature ID
- UI 표시 순서처럼 결과 의미에 영향을 주지 않는 값

부동소수점 좌표는 분석 정확도를 훼손하지 않는 문서화된 정밀도로 정규화한다.
정밀도 또는 정렬 규칙이 바뀌면 manifest schema 또는 규칙셋 버전을 올린다.

## CI와 로컬 QGIS

GitHub Actions는 Python 3.9/3.12 정적·순수 정책 검사를 수행하고, 별도 QGIS
워크플로는 검증된 QGIS 3.44 LTR 컨테이너에서 통합시험과 headless 설치를 수행하는
것을 목표로 한다. QGIS 3.28 Windows 시험은 하위호환을 다시 주장할 때 수동
템플릿으로 기록한다. 현재 PC의 3.28 설치는 실행 런타임이 불완전해 시험할 수
없었으므로 `qgisMinimumVersion`을 로컬 검증이 끝난 3.40으로 올렸다. CI가 아직
활성화되지 않았거나 컨테이너 이미지가 고정되지 않은 항목은 연구 Release의
통과로 계산하지 않는다.

2026-08-13 현재 working tree의 로컬 QGIS 3.40.5/Python 3.12.9 재실행에서는
`test_metric_context.py`와 모든 `test_qgis_*.py`가 84/84 통과했다. 추가 회귀
테스트가 생겨 이전 68개 통과 기록보다 총수가 늘었다. 이 로컬 결과는 호환성
근거이지만 QGIS 3.44 CI와 ZIP 설치 시험을 대신하지 않는다.

## 비공개 자료 재현

재배포할 수 없는 입력은 승인된 환경에서만 보관한다. 독립 검토자는 공급기관에서
동일 자료를 합법적으로 취득하고 bundle hash를 비교한다. 해시 불일치는 새 데이터
버전으로 처리한다. 공개 저장소에는 위치가 드러나지 않는 집계, 소프트웨어 환경,
규칙, 결과표만 남긴다.

## 현재 상태

- 초기 합성 정책 fixture: **13/13 통과**
- 합성 golden fixture 전체: **부분 완료; metric·encoding·geometry repair·취소·결정론적 출력 확대 pending**
- 100,000건 공간 인덱스 로컬 결과: **QGIS 3.40.5 Windows 통과, 3.44 CI pending**
- QGIS 3.40.5 로컬 통합검증: **84/84 통과, QGIS 3.44 CI pending**
- 점·선·면 family-separated 출력과 연속 번호: **implemented, local regression pass, CI pending**
- 양방향 폴리곤 포함률 `COVER_A`/`COVER_B`: **implemented, unit/local suite pass, broader golden coverage pending**
- 레이어별 인코딩 선택·manifest 기록: **implemented, local tests pass, QGIS 3.44 CI pending**
- Windows QGIS 3.28 수동 기록: **현재 지원 범위 밖; 하위호환 복원 시 pending**
- 외부 사용자 재현: **pending**
- Zenodo archive 및 DOI: **pending**

`validation/results/status.md`가 연구 Release 판단을 위한 단일 상태표다.
