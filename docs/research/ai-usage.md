# AI usage disclosure / 생성형 AI 사용 공개

## English summary

Generative AI has assisted with code suggestions, test drafting,
documentation structure, language revision, and repository maintenance. AI
output is not treated as archaeological evidence and does not make final
identity or representative-number decisions. Jinseo Hwang defines and reviews
the domain policy and retains responsibility for the released software,
validation, and manuscript. Tool or model identifiers are reported only when
they are recoverable from contemporaneous records.

## 공개 원칙

1. AI가 제안한 코드는 사람이 diff와 테스트 결과를 검토한다.
2. AI가 작성한 학술 문장은 출처, 과장, 실제 완료 여부를 사람이 확인한다.
3. 고고학적 동일성·대표성 정책과 최종 판정 책임은 Hwang Jinseo에게 있다.
4. AI 제안을 검증자료의 정답 라벨로 사용하지 않는다.
5. 확인할 수 없는 과거 모델명·버전·프롬프트는 추측해 복원하지 않는다.

## 사용 범위 기록표

| 영역 | 가능한 지원 | 필수 인간 검토 |
| --- | --- | --- |
| 코드 | 리팩터링·예외처리·문서 문자열 제안 | diff, API 호환성, QGIS 실행 |
| 테스트 | 합성 사례·assertion 초안 | 독립 기대값, 누락·순환검증 확인 |
| 문서 | 목차·초안·번역·교정 | 사실, 인용, 상태, 저자 주장 |
| 검증 | 분석 스크립트 구조 제안 | 라벨링, 잠금, 통계 해석 |
| 배포 | CI·release checklist 제안 | 자격증명, artifact, 라이선스 |

## 현재 확인 가능한 기록

이 연구 전환 작업에는 OpenAI Codex가 코드·테스트·문서 작업을 보조했다. 정확한
모델 식별자가 작업 기록에서 제공되는 경우 최종 Release manifest에 기록한다.
그 외 과거 작업에 사용된 AI 도구와 모델은 저장소 이력만으로 확정하지 않는다.

## 검토 절차

- 코드: 정적 검사, 순수 Python 테스트, QGIS 통합 테스트, 합성 golden test를
  통과시킨다. AI가 생성한 테스트만으로 같은 AI 생성 코드를 정당화하지 않고,
  규칙 문서에서 독립적으로 기대 결과를 정한다.
- 원고: DOI·서지·버전·수치를 원 출처 또는 실행 결과와 대조한다. 수행하지 않은
  검증은 `pending`으로 표시한다.
- 고고학 정책: 사용자 인터페이스의 추천과 실제 병합 효과를 도메인 책임자가
  직접 확인한다.

## Release별 갱신 템플릿

각 연구 Release 전에 아래 항목을 추가한다.

```text
Release/tag:
AI tool and verifiable model identifier:
Dates/commit range:
Files or tasks assisted:
Human reviewer:
Verification performed:
Known limitations:
```

현재 `joss-v1.0.5-rc1`과 `joss-v1.0.5` 태그, DOI, 최종 AI manifest는
**pending**이며 이 문서는 완료를 주장하지 않는다.
