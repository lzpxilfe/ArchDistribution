# AI usage disclosure / 생성형 AI 사용 공개

## English summary

OpenAI Codex has assisted with code suggestions and refactoring, test
scaffolding, documentation organization, repository maintenance, and language
editing. The `gpt-5.6-sol` model identifier was recoverable from the Codex
desktop session metadata for the 13 August 2026 research-software and
manuscript revision. Historical Codex sessions did not retain every underlying
model identifier; unavailable identifiers have not been reconstructed or
guessed.

Jinseo Hwang defined the archaeological problem and domain policy, made the
principal design decisions, reviewed and modified AI-assisted outputs, and
verified them through code inspection, expected cases derived from the written
rules, static analysis, and QGIS execution. AI output is not archaeological
evidence and was not used as a reference label. Jinseo Hwang remains
responsible for the software, validation, manuscript, licensing, and ethical
compliance.

## 공개 원칙

1. AI가 제안한 코드는 사람이 diff와 테스트 결과를 검토한다.
2. AI가 작성하거나 교정한 문장은 출처, 수치, 과장, 실제 완료 여부를 사람이 확인한다.
3. 고고학적 동일성·대표성 정책과 최종 판정 책임은 Jinseo Hwang에게 있다.
4. AI 제안을 검증자료의 정답 라벨이나 고고학적 근거로 사용하지 않는다.
5. 확인할 수 없는 과거 모델명·버전·프롬프트는 추측해 복원하지 않는다.

## 사용 범위와 인간 검토

| 영역 | AI 보조 범위 | 인간 검토 |
| --- | --- | --- |
| 코드 | 리팩터링, 예외 처리, 문서 문자열 제안 | diff, API 호환성, QGIS 실행 |
| 테스트 | 합성 사례와 assertion 초안 | 명문화된 규칙에서 기대값 도출, 누락·순환검증 확인 |
| 문서 | 구조, 초안, 번역, 교정 | 사실, 인용, 상태, 저자 주장 |
| 검증 | 분석 스크립트 구조 제안 | 라벨링, 잠금, 통계 해석 |
| 배포 | CI와 release 점검 제안 | 자격증명, artifact, 라이선스, 공개 범위 |

## 확인 가능한 2026년 8월 기록

| 항목 | 기록 |
| --- | --- |
| 도구 | OpenAI Codex desktop |
| 확인 가능한 모델 | `gpt-5.6-sol` |
| 확인 근거 | 2026-08-13 Codex desktop session metadata |
| 적용 범위 | 연구 소프트웨어 점검, 테스트·CI 보강, JOSS 문서와 `paper/paper.md` 교정 |
| 인간 검토자 | Jinseo Hwang |
| 검증 | diff 검토, 정적 검사, 순수 Python 테스트, QGIS 통합 테스트, 합성 정책 사례, JOSS PDF 빌드 |

과거 Codex 사용도 같은 범주에 포함되지만, 당시 session metadata에 남지 않은
세부 모델 식별자는 공개 기록으로 확정할 수 없다.

## 영문 편집 체크리스트

2026년 8월 13일 원고 교정에는 다음 공개 저장소의 편집 원칙을 참고했다.
코드나 지침 문구를 저장소에 복사하지 않았으며, 아래 도구로 원고를 자동 생성하거나
탐지기 회피를 시도하지 않았다.

- `blader/humanizer` v2.9.1, commit
  `523374dee72d67c7b2b5f858ea0094ffda49c3ac`: 사실과 인용 보존,
  과장·상투어 제거, 직접적인 기술 문체 점검에 사용했다.
- `harshaneel/humanize`, commit
  `4ec797314537ec9c2105f276d4561d240a0390ba`: 명료성과 반복 점검에
  한정해 참고했다. 탐지기 회피, 인위적인 문장 결함, 검증되지 않은 구체성 삽입은
  적용하지 않았다.
- `federicodeponte/opendraft` v1.7.4, repository state
  `a182f88ea54bd98d675490e577c588e328477211`: 프로그램을 실행하지 않았다.
  심사자 검토, 반론 검토, 인용 확인, 문장 교정을 분리하는 절차만 수동 점검표로
  참고했다.

## 검토 절차

- 코드는 정적 검사, 순수 Python 테스트, QGIS 통합 테스트, 합성 정책 사례로
  확인한다. 테스트가 같은 AI의 제안만 되풀이하지 않도록 문서화된 규칙에서
  기대 결과를 도출한다.
- 원고의 DOI, 서지정보, 버전, 수치, 실제 활용 주장은 원 출처 또는 실행 기록과
  대조한다. 수행하지 않은 검증을 완료한 것으로 쓰지 않는다.
- 사용자 인터페이스의 추천과 실제 병합 효과, 고고학적 의미는 도메인 책임자가
  직접 판단한다.

JOSS 심사 중 편집자 및 심사자와의 실질적 대화에는 생성형 AI를 사용하지 않는다.
필요한 경우 번역 보조만 사용하고, 판단과 답변은 저자가 직접 작성한다.
