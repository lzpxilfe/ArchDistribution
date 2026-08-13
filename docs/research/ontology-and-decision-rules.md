# Ontology and decision rules / 개체론 및 판정 규칙

> Status: research specification for ArchDistribution 1.0.5. Where this
> document and the current executable differ, the run manifest and the tested
> implementation are authoritative. Differences must be logged before a JOSS
> release candidate is created.

## English summary

ArchDistribution separates four concepts that are commonly conflated in a
distribution map: an archaeological site entity, an investigation event, a
geometry group, and a displayed map number. Spatial overlap is evidence for a
typed relationship, never sufficient proof of identity. Only a confirmed
`same_entity` relationship may create an equivalence cluster. Legal,
parent–component, and investigation relationships remain links between
distinct records. Human review can preserve separate records, link records, or
choose a representative number without deleting source evidence.

## 목적

여러 기관의 공간자료에서 같은 장소가 겹쳐 보인다는 사실만으로 같은 유적이라고
단정하지 않는다. 지정유산, 보호구역, 분포지도 기록, 지표조사, 발굴조사는 서로
다른 행정·연구 행위를 표현할 수 있다. 이 문서는 플러그인이 **무엇을 묶고 무엇을
분리하는지**를 재현 가능하게 정의한다.

## 핵심 식별자

| 필드 | 의미 | 결합 규칙 |
| --- | --- | --- |
| `INVESTIGATION_KEY` | 사업명 또는 조사사건 | 같은 발굴 사업은 공유할 수 있다. |
| `SITE_ENTITY_KEY` | 확인된 유적 실체 | 동일 실체 결정만 공유한다. |
| `ENTITY_KEY` | 하위 호환 별칭 | 새 결과에서는 `SITE_ENTITY_KEY`와 같다. |
| `GEOMETRY_GROUP_KEY` | dissolve 또는 보존조치별 형상 묶음 | 지도 형상 제작에만 사용한다. |
| `NUMBER_KEY` | 표시 번호 단위 | 같은 사업의 분할 구역이 공유할 수 있다. |
| `RELATION_KEY` | 번호와 무관한 관련 기록 연결 | 지정유산–발굴처럼 둘 다 번호를 유지할 때 사용한다. |

`NUMBER_KEY`가 같다는 사실은 `SITE_ENTITY_KEY`가 같다는 뜻이 아니다. 예를 들어
하나의 발굴 사업에서 서로 다른 유적명이 확인되면 조사·번호 단위는 공유할 수
있지만 유적 실체는 기본적으로 분리한다.

초기 `SITE_ENTITY_KEY`와 `GEOMETRY_GROUP_KEY`는 명칭이 아니라 각 원본 레코드의
안정적인 `SRC_UID`에서 만든다. 사업명이 없으면 초기 `NUMBER_KEY`도 원본별로
분리한다. 따라서 멀리 떨어진 동명 유적이나 명칭 끝의 I·II 지역 표기만으로
실체·형상·번호가 선제 병합되지 않는다. 매장유산 유존지역 전용 흐름의 보존조치별
도형이 한 번호를 공유해야 할 때는 공급자 코드 또는 자료셋·명칭·주소로 범위를
제한한 별도 번호 scope를 사용하며, 이것 역시 동일 실체 주장이 아니다.

## 자료 역할

연구 규칙셋은 최소한 다음 역할을 구분한다.

- 국가지정, 시도지정, 국가등록, 시도등록 유산
- 지정·등록유산 보호구역
- 문화유적분포지도
- 지표조사
- 발굴조사
- 기타

보호구역은 법적 경계이며 독립 번호를 받지 않는다. 지표조사는 어떤 프리셋에서도
자동 소거하지 않는다. 등록유산은 지정유산과 같은 대표 우선순위를 사용할 수
있지만 출처 역할은 보존한다.

## 관계 유형

`RELATION_TYPE`의 공개 값은 다음으로 제한한다.

- `same_entity`: 동일 유적 실체로 확정. 등가 군집화 가능.
- `parent_child`: 상위 유적과 부속 유산. 별도 실체 유지.
- `investigation_site`: 조사사건과 유적의 관계. 별도 번호 가능.
- `legal_boundary_site`: 보호구역과 본체 유산. 보호구역은 무번호.
- `related_separate`: 관련은 있으나 대표 번호를 공유하지 않음.
- `uncertain`: 근거 부족. 사람 검토 전에는 병합하지 않음.

## 기본 판정 정책

1. 공간 중첩만으로 자동 병합하지 않는다.
2. 지정·등록유산과 분포지도는 정규화 명칭이 같고 실제 면적 중첩이 있을 때
   지정·등록유산을 대표로 추천할 수 있다.
3. 발굴 유적명과 분포지도 명칭이 같고 중첩되면 발굴조사를 대표로 추천할 수 있다.
   사업명 유사성만으로는 자동 처리하지 않는다.
4. 지정·등록유산과 발굴조사는 장소를 연결하되 법적 실체와 조사사건의 번호를
   각각 유지한다.
5. 같은 발굴 사업의 I·II-1·II-2 같은 구역은 `NUMBER_KEY`와
   `INVESTIGATION_KEY`를 공유한다. 각 `SITE_ENTITY_KEY`는 처음에는 분리하며,
   공간적으로 가까운 동일 명칭 계열일 때만 자동 적용 없는 `same_entity` 검토
   후보로 제시한다.
6. 상위 유적과 부속 유산은 명칭·공간이 유사해도 자동 병합하지 않는다.
7. `유산코드`는 같은 자료 계열 내부 확인에만 쓰며 자료 종류를 넘는 결합 키로
   쓰지 않는다.

## 비교 증거

현재 구현은 폴리곤 후보에 작은 도형 기준 중첩률, A→B·B→A 양방향 포함률,
IoU, 면적비, 중심점 거리, 경계 간 거리를 기록한다. 검수표에서는 양방향 포함률을
`COVER_A`, `COVER_B`로 보존한다. 명칭·주소는 원문과 정규화 결과를 모두 보존한다.
숫자 토큰 경계를 무시한 주소 부분문자열이나 “유적”, “문화재” 같은 일반명칭은
검토 신호일 수 있지만 자동 병합 근거가 될 수 없다.

## 사람 검토와 불변조건

검토자는 `별도 유지`, `연결만`, `대표 번호로 묶기` 중 하나를 선택한다. 자동 추천도
취소할 수 있어야 한다. 어떤 결정도 원본 레이어를 수정·삭제하지 않는다. 대표에서
제외된 기록은 보존 레이어와 검수 테이블에 남고, manifest에는 판정 규칙 버전과
결정 캐시가 기록된다.

## 규칙 변경 관리

임계값과 가중치는 버전 관리되는 JSON 규칙셋에서 읽으며 파일 SHA-256을
manifest에 기록한다. 잠금 평가자료를 확인한 뒤 임계값을 바꾸면 새로운 규칙셋
버전과 새로운 평가가 필요하다. 코드의 숨은 상수로 규칙을 우회해서는 안 된다.
