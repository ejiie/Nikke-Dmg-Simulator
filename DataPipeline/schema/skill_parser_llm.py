"""
DataPipeline/schema/skill_parser_llm.py

Claude tool_use API를 이용한 NIKKE 스킬 텍스트 구조화 파서.

사용 전 환경변수 설정:
    export ANTHROPIC_API_KEY="sk-ant-..."

기본 사용법:
    from DataPipeline.schema.skill_parser_llm import parse_skill, parse_all_skills
    result = parse_skill("Passive: Increases ATK of all allies by 5.28% for 5 sec.", "s1", "Power Surge")
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import anthropic

from .skill_schema import SkillParsed, build_system_prompt

# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────

MODEL           = "claude-opus-4-6"
MAX_TOKENS      = 4096
RETRY_LIMIT     = 3
RETRY_BASE_SEC  = 2.0   # 지수 백오프 기본값 (초)

_TOOL_NAME      = "extract_skill_data"
_TOOL_DEF       = {
    "name": _TOOL_NAME,
    "description": (
        "NIKKE 스킬 텍스트를 파싱해 구조화된 SkillParsed JSON을 출력한다. "
        "입력 스키마를 엄격히 준수할 것."
    ),
    "input_schema": SkillParsed.model_json_schema(),
}


# ─────────────────────────────────────────────────────────────
# 핵심 파서
# ─────────────────────────────────────────────────────────────

def parse_skill(
    skill_text: str,
    skill_slot: str,
    skill_name: str = "",
    *,
    client: Optional[anthropic.Anthropic] = None,
    verbose: bool = False,
) -> SkillParsed:
    """
    스킬 텍스트 하나를 파싱해 SkillParsed 모델로 반환.

    Args:
        skill_text:  prydwen_clean.json의 descriptionLevel10 텍스트
        skill_slot:  's1', 's2', 'burst' 중 하나
        skill_name:  스킬 이름 (없으면 빈 문자열)
        client:      anthropic.Anthropic 인스턴스 (없으면 자동 생성)
        verbose:     True면 raw LLM 응답 출력

    Returns:
        SkillParsed (pydantic 모델)

    Raises:
        ValueError:  LLM이 tool_use를 반환하지 않거나 스키마 검증 실패 시
        anthropic.APIError: API 통신 오류
    """
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system_prompt = build_system_prompt()
    user_message  = (
        f"skill_name: {skill_name!r}\n"
        f"skill_slot: {skill_slot!r}\n"
        f"skill_text:\n{skill_text}"
    )

    last_error: Exception | None = None
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                tools=[_TOOL_DEF],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": user_message}],
            )

            if verbose:
                print(f"[LLM] stop_reason={response.stop_reason}, "
                      f"usage={response.usage}")

            # tool_use 블록 추출
            tool_block = next(
                (b for b in response.content if b.type == "tool_use"),
                None,
            )
            if tool_block is None:
                raise ValueError(
                    f"tool_use 블록 없음. stop_reason={response.stop_reason}"
                )

            raw_dict = tool_block.input
            if verbose:
                print("[LLM] raw tool input:")
                print(json.dumps(raw_dict, ensure_ascii=False, indent=2))

            # Pydantic 검증
            return SkillParsed.model_validate(raw_dict)

        except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
            last_error = e
            wait = RETRY_BASE_SEC * (2 ** (attempt - 1))
            print(f"⚠️  API 오류 (시도 {attempt}/{RETRY_LIMIT}), {wait}초 후 재시도: {e}")
            time.sleep(wait)

        except Exception as e:
            # 재시도 불필요한 오류는 바로 raise
            raise

    raise last_error  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────
# 배치 파서
# ─────────────────────────────────────────────────────────────

def parse_all_skills(
    prydwen_clean_path: str,
    output_path: str,
    *,
    overwrite: bool = False,
    verbose: bool = False,
) -> dict[str, list[dict]]:
    """
    prydwen_clean.json 전체 캐릭터의 스킬을 파싱해 JSON으로 저장.

    Args:
        prydwen_clean_path: Database/processed/prydwen_clean.json 경로
        output_path:        출력 파일 경로 (예: Database/processed/skills_parsed.json)
        overwrite:          False면 이미 파싱된 캐릭터는 건너뜀 (재실행 안전)
        verbose:            True면 각 스킬 raw 응답 출력

    Returns:
        {slug: [SkillParsed.model_dump(), ...]} 딕셔너리
    """
    with open(prydwen_clean_path, "r", encoding="utf-8") as f:
        prydwen_data: dict = json.load(f)

    # 기존 결과 로드 (overwrite=False면 이어쓰기)
    results: dict[str, list[dict]] = {}
    if not overwrite and os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            results = json.load(f)
        print(f"💾 기존 파싱 결과 로드: {len(results)}명")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    total   = len(prydwen_data)
    skipped = 0
    success = 0
    failed: list[str] = []

    for idx, (slug, char) in enumerate(prydwen_data.items(), 1):
        if not overwrite and slug in results:
            skipped += 1
            continue

        char_name  = char.get("name", slug)
        skills     = char.get("skills", [])
        parsed_skills: list[dict] = []

        print(f"[{idx:3}/{total}] {char_name} ({slug}) — {len(skills)}개 스킬")

        skill_failed = False
        for skill in skills:
            desc = skill.get("descriptionLevel10", "")
            if not desc:
                continue

            slot_raw = skill.get("slot", "")
            # slot 정규화: "Skill 1" → "s1", "Skill 2" → "s2", "Burst" → "burst"
            slot = _normalize_slot(slot_raw)
            name = skill.get("name", "")

            try:
                parsed = parse_skill(desc, slot, name, client=client, verbose=verbose)
                parsed_skills.append(parsed.model_dump())
                success += 1
            except Exception as e:
                print(f"  ❌ [{slug}] {name} ({slot}) 파싱 실패: {e}")
                # 실패해도 raw_text만이라도 보존
                parsed_skills.append({
                    "skill_name": name,
                    "skill_slot": slot,
                    "raw_text": desc,
                    "effects": [],
                    "stack_conditions": None,
                    "parsing_notes": f"[PARSE_ERROR] {e}",
                })
                skill_failed = True

        results[slug] = parsed_skills
        if skill_failed:
            failed.append(slug)

        # 중간 저장 (10명마다)
        if idx % 10 == 0:
            _save(results, output_path)
            print(f"  💾 중간 저장 ({idx}/{total})")

    # 최종 저장
    _save(results, output_path)

    print(f"\n✅ 완료: 성공 {success}개, 건너뜀 {skipped}명")
    if failed:
        print(f"⚠️  파싱 실패 포함 캐릭터 ({len(failed)}명): {', '.join(failed[:10])}")

    return results


def _normalize_slot(raw: str) -> str:
    """'Skill 1' → 's1', 'Skill 2' → 's2', 'Burst' → 'burst'"""
    r = raw.strip().lower()
    if "1" in r:
        return "s1"
    if "2" in r:
        return "s2"
    if "burst" in r:
        return "burst"
    return r


def _save(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    DEFAULT_IN  = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "prydwen_clean.json")
    DEFAULT_OUT = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "skills_parsed.json")

    parser = argparse.ArgumentParser(description="NIKKE 스킬 LLM 파서")
    parser.add_argument("--input",     default=DEFAULT_IN,  help="prydwen_clean.json 경로")
    parser.add_argument("--output",    default=DEFAULT_OUT, help="출력 JSON 경로")
    parser.add_argument("--overwrite", action="store_true", help="기존 결과 무시하고 전체 재파싱")
    parser.add_argument("--verbose",   action="store_true", help="raw LLM 응답 출력")
    parser.add_argument("--single",    metavar="TEXT",      help="단일 스킬 텍스트 테스트")
    parser.add_argument("--slot",      default="s1",        help="--single 사용 시 슬롯 (s1/s2/burst)")
    args = parser.parse_args()

    if args.single:
        result = parse_skill(args.single, args.slot, verbose=args.verbose)
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    else:
        parse_all_skills(
            args.input,
            args.output,
            overwrite=args.overwrite,
            verbose=args.verbose,
        )
