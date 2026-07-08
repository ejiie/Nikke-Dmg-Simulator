# _archive — 대체 완료된 레거시 스택 (역사 보존용, 현행 참조 금지)

2026-07-08 전수 감사(VERIFICATION_LOG 12차)에서 이동. 현행 스택이 완전히 대체함.

| 디렉토리 | 내용 | 대체한 것 |
|---|---|---|
| `llm_skill_parser/` | Gemini LLM 스킬 텍스트 파서 v3 (skill_schema/parser + 테스트). 산출물 skills_parsed.json 은 유실·가치 0 | 공식 FunctionTable 디코드 (`crawler/memorypack_decode.py` → `staticdata_skill_chains.py`) |
| `il2cpp_route/` | il2cpp metadata 스키마 덤프 경유 .mpk 디코드 루트 (타입 추론·순열 RE) | SharpnelXu 공개 [MemoryPackOrder] 스키마 (동일 디코더) |
| `task_docs/` | 완료/무의미화된 태스크 기준 문서 (ENGINE_WAVE0=K0/K1 완료, ROLEDATA_SKILL_AUDIT=결정이 공식 FunctionTable 채택으로 대체) | `Docs/` 현행 문서 |

용도: 사용자 학습 참고(스킬 구성 공부 등). 신규 작업은 절대 이쪽을 권위로 삼지 말 것.
