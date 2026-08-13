# Limitations and ethics / 한계와 윤리

## English summary

ArchDistribution supports, but does not replace, archaeological and legal
judgement. Its recommendations depend on incomplete and historically variable
source data. False merges can erase distinctions; missed links can duplicate
sites. The software therefore preserves source records, exposes uncertain
relationships, and requires human review for ambiguous cases. Exact site
coordinates and restricted administrative data must not be published merely
for reproducibility.

## 알려진 한계

- 명칭 유사도는 동일성의 증명이 아니다. 개칭, 동명이소, 상위·부속 관계가 있다.
- 중첩률은 경계 제작 관행과 조사범위 차이에 민감하다.
- 주소 부분문자열은 필지번호·숫자 토큰을 잘못 연결할 수 있다.
- 입력 누락과 기관별 분류 차이를 알고리즘이 복구할 수 없다.
- 점·선·면은 형상 계열별 결과로 분리된다. 서로 다른 형상 계열 사이의 동일성은
  자동 병합하지 않으므로 필요한 관계는 사람이 검토해야 한다.
- 레이어별 UTF-8/CP949 선택은 잘못된 사용자 선택 자체를 판별하지 못한다. 깨진
  글자가 의심되면 원자료의 `.cpg`와 공급기관 설명을 함께 확인해야 한다.
- 단일 평가자 파일럿은 평가자 간 신뢰도와 기관 간 일반화를 검증하지 못한다.
- 지도 번호는 표현 정책이며 유적의 학술적 중요도나 법적 서열이 아니다.
- 현재 연구 범위는 회전 도곽, 완전한 주소 파서, 국제 온톨로지 일반화,
  QGIS 4/Qt6, 다중 전문가 통계검증을 포함하지 않는다.

## 오류의 비대칭성

오병합은 서로 다른 유적·조사·법적 실체를 하나로 보이게 할 수 있어 특히 위험하다.
따라서 애매한 경우의 기본값은 별도 유지 또는 검토다. 반대로 연결 누락은 중복
번호와 검토 부담을 만들 수 있다. 자동화율보다 오병합 방지가 우선이며, 합성 검증은
오병합 0건을 요구한다.

## 법적·전문적 판단

플러그인의 역할 분류와 대표 추천은 지정 효력, 발굴 허가, 보존조치, 개발행위
가능성을 판단하지 않는다. 최신 법령과 행정문서, 담당 전문기관의 판단을 사용자가
별도로 확인해야 한다. 출력물은 조사보고서·허가문서의 대체물이 아니다.

## 민감한 위치정보

유적 좌표는 훼손, 도굴, 사유지 침해 위험을 높일 수 있다. 공개 저장소·논문·CI
artifact에는 실제 원자료, 실제 후보쌍, 원본 파일경로, 고해상도 좌표 스크린샷을
올리지 않는다. 사례도 좌표 이동만으로 충분한 익명화가 되지 않을 수 있으므로
필요하면 완전 합성 사례로 대체한다.

## 편향과 대표성

행정자료는 조사·지정·디지털화가 많이 이루어진 지역을 더 잘 표현한다. 지도에서
빈 곳이 유적 부재를 의미하지 않으며, 자동 판정 성능이 높은 자료 유형이 더 중요한
유산을 뜻하지 않는다. 성능은 역할·지역·명칭 길이·형상 규모별로 나누어 확인하고,
표본이 작은 하위집단은 수치 일반화를 하지 않는다.

## 사람의 책임과 이의제기

모든 대표 결정은 규칙·근거·사용자 선택으로 추적 가능해야 한다. 검토자는 자동
추천을 취소할 수 있고 원본으로 돌아갈 수 있어야 한다. 버그나 잘못된 규칙은
GitHub issue로 재현 가능한 합성 예제와 함께 제보하되 민감한 실제 자료를 공개
issue에 첨부하지 않는다.

## 주장 제한

300쌍 파일럿, 외부 설치 시험, 실제 작업 3건 관찰은 현재 **pending**이다. 완료 전
“고고학적 정확도 검증”, “무검수 자동화”, “시간 절감 입증”이라는 표현을 사용하지
않는다. 기준을 통과하더라도 결과는 표본·버전·규칙셋 범위로 한정한다.
