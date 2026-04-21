"""
DataPipeline/schema/skill_parser_llm.py

Google Gemini 3 Flash의 구조화 출력(response_schema=Pydantic)을 이용한
NIKKE 스킬 텍스트 파서.

진실원(source of truth):
    Database/processed/nikke_merged_db_returned.json
    (C# Nikke.Simulator.Core 의 RootDto 가 매핑하는 동일 파일)

기본 동작:
    parse_owned_roster()    — merged DB 의 roster (사용자 보유 캐릭터)만 파싱
    parse_character_on_demand() — 단일 캐릭 lazy 파싱 (이론상 빌드용)
    parse_skill()           — 단일 스킬 텍스트 파싱 (저수준 API)

출력 (skills_parsed.json) 키 정책:
    name_code (예: "1010") 가 최상위 key. slug 는 entry 안에 같이 보관.

사용 전 환경변수 설정:
    export GEMINI_API_KEY="..."          # 또는 GOOGLE_API_KEY

기본 사용법:
    from DataPipeline.schema.skill_parser_llm import parse_skill, parse_owned_roster
    result = parse_skill("■ Affects all allies.ATK ▲ 5.28% for 5 sec.", "s1", "Power Surge")
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from .skill_schema import SkillParsed, build_system_prompt

# python-dotenv 는 선택적 의존성. 없으면 OS 환경변수만 사용.
try:
    from dotenv import find_dotenv, load_dotenv
    _ENV_PATH = find_dotenv(usecwd=True)
    if _ENV_PATH:
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────

MODEL           = "gemini-3-flash-preview"
MAX_TOKENS      = 8192      # thinking_budget=0 이어도 여유 있게 확보
RETRY_LIMIT     = 3
RETRY_BASE_SEC  = 2.0   # 지수 백오프 기본값 (초)
THINKING_BUDGET = 0         # 0 = thinking 비활성화. 추출 작업은 few-shot이 결정적이라 불필요.
                            # 파싱 품질이 떨어지면 512~1024 정도로 올려볼 것.

# Gemini는 시스템 프롬프트를 implicit 캐시로 자동 처리한다.
# Flash 모델은 반복 prefix가 충분히 길면 cachedContentTokenCount가 붙으며
# 입력 토큰 단가가 할인된다. 별도 cache_control 설정 불필요.


def _load_api_keys() -> tuple[list[str], list[int]]:
    """
    .env 또는 OS 환경변수에서 Gemini API 키 목록 + '유료 키' 인덱스를 수집한다.

    지원 포맷:
      1) GEMINI_API_KEYS=key1,key2,key3         (콤마 구분, 우선순위 1)
      2) GEMINI_API_KEY_1=..., _2=..., _3=...   (넘버링, 우선순위 2)
      3) GEMINI_API_KEY=...  또는  GOOGLE_API_KEY=...  (단일 키, 후방 호환)

    유료 키 지정 (optional):
      GEMINI_PAID_KEY_INDICES="5"        # 1-based index, 콤마 구분 가능 ("5,6")
      또는 개별 키의 1-based index 여러 개 쉼표로.
      지정된 index 는 '모든 무료 키가 cooldown/소진 상태일 때만' 쓰인다.

    반환:
      (keys, paid_indices_0based)
      - keys: 중복 제거된 순서 보존 API 키 리스트
      - paid_indices_0based: 유료 키의 0-based 인덱스 리스트

    하나도 없으면 RuntimeError.
    """
    seen: set[str] = set()
    keys: list[str] = []
    # 순서 보존을 위해 (slot_number_1based → key) 맵핑을 같이 기록.
    # slot_number 는 "_5" 같은 넘버링 env 의 번호. 유료 키 인덱스 계산에 사용.
    slot_of: dict[int, int] = {}   # env slot 1-based → keys list 0-based

    def _add(raw: Optional[str], env_slot: Optional[int] = None) -> None:
        if not raw:
            return
        k = raw.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
            if env_slot is not None:
                slot_of[env_slot] = len(keys) - 1

    # 1) 콤마 구분 묶음 (이쪽은 slot 번호 없음)
    bulk = os.getenv("GEMINI_API_KEYS") or os.getenv("GOOGLE_API_KEYS") or ""
    for part in bulk.split(","):
        _add(part)

    # 2) 넘버링 (_1, _2, ...) — slot_of 로 번호 추적
    for i in range(1, 33):
        raw = os.getenv(f"GEMINI_API_KEY_{i}") or os.getenv(f"GOOGLE_API_KEY_{i}")
        _add(raw, env_slot=i)

    # 3) 단일 키 폴백
    _add(os.getenv("GEMINI_API_KEY"))
    _add(os.getenv("GOOGLE_API_KEY"))

    if not keys:
        raise RuntimeError(
            "API 키를 찾을 수 없습니다. .env 에 다음 중 하나를 설정하세요:\n"
            "  GEMINI_API_KEYS=key1,key2,key3\n"
            "  GEMINI_API_KEY_1=...\n  GEMINI_API_KEY_2=...\n"
            "  GEMINI_API_KEY=...   (단일)"
        )

    # 유료 키 인덱스 파싱. 1-based 번호를 받아서 keys 리스트의 0-based 인덱스로 매핑.
    # 잘못된 값(비숫자/범위 밖/해당 slot 비어있음)은 경고하고 무시.
    paid_spec = os.getenv("GEMINI_PAID_KEY_INDICES", "").strip()
    paid_indices: list[int] = []
    if paid_spec:
        for part in paid_spec.split(","):
            part = part.strip()
            if not part.isdigit():
                continue
            one_based = int(part)
            # 우선 GEMINI_API_KEY_<N> 번호로 해석. 없으면 keys 리스트의 단순 N번째.
            if one_based in slot_of:
                paid_indices.append(slot_of[one_based])
            elif 1 <= one_based <= len(keys):
                paid_indices.append(one_based - 1)
        paid_indices = sorted(set(paid_indices))

    return keys, paid_indices


class ApiKeyRotator:
    """
    Tier-aware Gemini API 키 로테이터.

    정책:
      - 무료 키(is_paid=False) 를 우선 소비한다.
      - 모든 무료 키가 (a) 일일 소진 또는 (b) 분당 쿨다운 이어서 당장 못 쓸 때만
        유료 키로 넘어간다. 유료 키가 독점되지 않도록 무료 키의 cooldown 이
        풀리면 즉시 무료 쪽으로 복귀.

    상태:
      - _exhausted[i]           : 영구 폐기 (일일 quota 소진). 세션 동안 복귀 불가.
      - _cooldown_until[i]      : 이 시각(unix ts) 이후 복귀 가능. 분당 rate-limit 처리.

    주요 메서드:
      - pick_next()             : 선호 순으로 다음 가용 키 선택. 활성 키가 모두
                                  cooling 중이면 가장 가까운 만료까지 sleep 후 선택.
                                  모두 exhausted 면 False.
      - cool_down_current(secs) : 현재 키를 'secs' 초 동안 cooldown 상태로.
      - exhaust_current()       : 현재 키 영구 폐기.
      - rotate()                : 폐기 + pick_next (후방 호환 alias).
    """
    def __init__(self, keys: list[str], paid_indices: Optional[list[int]] = None):
        if not keys:
            raise RuntimeError("ApiKeyRotator: 키가 비어있음.")
        self._keys: list[str] = list(keys)
        self._is_paid: list[bool] = [False] * len(self._keys)
        for i in (paid_indices or []):
            if 0 <= i < len(self._keys):
                self._is_paid[i] = True
        self._exhausted: set[int] = set()
        self._cooldown_until: list[float] = [0.0] * len(self._keys)
        self._clients: dict[int, genai.Client] = {}

        picked = self._pick_preferred_idx(now=time.time())
        if picked is None:
            # 초기 상태라 exhausted 가 비어있어야 정상. 방어용.
            raise RuntimeError("ApiKeyRotator: 가용 키가 없습니다.")
        self._idx: int = picked

    # ── helpers ─────────────────────────────────────────────
    def _pick_preferred_idx(self, now: float) -> Optional[int]:
        """무료 → 유료 순으로 '지금 당장' 쓸 수 있는 첫 인덱스. 없으면 None."""
        for i in range(len(self._keys)):
            if (not self._is_paid[i]
                    and i not in self._exhausted
                    and self._cooldown_until[i] <= now):
                return i
        for i in range(len(self._keys)):
            if (self._is_paid[i]
                    and i not in self._exhausted
                    and self._cooldown_until[i] <= now):
                return i
        return None

    def _tag(self, i: int) -> str:
        return "paid" if self._is_paid[i] else "free"

    # ── properties ──────────────────────────────────────────
    @property
    def total(self) -> int:
        return len(self._keys)

    @property
    def alive(self) -> int:
        return self.total - len(self._exhausted)

    # ── core API ────────────────────────────────────────────
    def current_client(self) -> genai.Client:
        if self._idx not in self._clients:
            self._clients[self._idx] = genai.Client(api_key=self._keys[self._idx])
        return self._clients[self._idx]

    def current_label(self) -> str:
        head = self._keys[self._idx][:6]
        return (f"key#{self._idx + 1}/{self.total}"
                f"[{self._tag(self._idx)}]({head}…)")

    def cool_down_current(self, seconds: float) -> None:
        """현재 키를 seconds 초 동안 cooldown. 분당 rate-limit 시 호출."""
        if seconds > 0:
            self._cooldown_until[self._idx] = time.time() + seconds

    def exhaust_current(self) -> None:
        """현재 키를 영구 폐기 (일일 quota 소진 시 호출)."""
        self._exhausted.add(self._idx)

    def pick_next(self) -> bool:
        """
        선호 순(무료 우선) 으로 다음 가용 키 선택.
        - 지금 바로 쓸 수 있는 키가 있으면 그걸로 전환.
        - 활성(=not exhausted) 이지만 모두 cooling 이면, 가장 가까운 만료까지 sleep 후 선택.
        - 모두 exhausted 면 False.
        """
        now = time.time()
        alive_indices = [i for i in range(self.total) if i not in self._exhausted]
        if not alive_indices:
            return False

        idx = self._pick_preferred_idx(now)
        if idx is not None:
            self._idx = idx
            return True

        # 모두 cooling — 가장 가까운 만료까지 대기. 여유 0.5s.
        soonest = min(self._cooldown_until[i] for i in alive_indices)
        wait = max(0.0, soonest - now) + 0.5
        print(f"🕐 모든 활성 키 cooling. 가까운 만료까지 {wait:.1f}s 대기…")
        time.sleep(wait)
        idx = self._pick_preferred_idx(time.time())
        if idx is None:
            # 드물게, sleep 중 다른 스레드가 exhaust 했거나 하면 None 일 수 있음.
            # 방어적으로 False 반환 (호출자가 재시도 여부 결정).
            return False
        self._idx = idx
        return True

    def rotate(self) -> bool:
        """폐기 + 다음 키 선택 (후방 호환용). exhaust_current + pick_next 와 동일."""
        self.exhaust_current()
        return self.pick_next()


def _is_quota_error(e: Exception) -> bool:
    """
    429 중에서 '일일 quota 소진' 류인지 판별.
    - 분당 rate-limit (RPM, 'per minute', retryDelay 가 수십초) → backoff 대상, 키 유지
    - 일일/프로젝트 quota → 키 교체 필요
    판별 모호하면 backoff (False) 로 간주. 키를 섣불리 버리면 회복 가능한 한도를
    퉁쳐서 소진시키는 사고(gemini-3-flash 무료 티어 5 RPM + retry in 48s 같은 케이스)가 난다.

    Gemini 무료 티어 / preview 모델은 흔히 아래 형태를 보낸다:
        "Quota exceeded for metric: ...GenerateRequestsPerMinute...
         Please retry in 48s"
    여기엔 'quota' 단어도 들어있지만 'per minute' 신호 + 짧은 retryDelay 가 붙는 건
    실질적으로 분당 버스트 제한이므로 키 교체가 아닌 대기로 해결해야 한다.
    """
    status = getattr(e, "code", None) or getattr(e, "status_code", None)
    if status != 429:
        return False
    msg = (str(e) or "").lower()

    # 1) 분당 rate-limit 의 흔적들 먼저 검사 → backoff (키 유지)
    per_minute_signals = (
        "per minute", "per-minute", "perminute",
        "requestspermin", "rpm",
        "too many requests",
    )
    if any(s in msg for s in per_minute_signals):
        return False

    # 2) retryDelay 가 짧으면 (<= 5분) per-minute 로 간주. 짧은 대기로 해결 가능하면
    #    키를 버릴 이유가 없다. 긴 retry_delay 는 일일 quota 신호.
    import re
    m = re.search(r"retry(?:delay|in)['\"]?\s*[:=]\s*['\"]?(\d+)\s*s", msg)
    if m:
        sec = int(m.group(1))
        if sec <= 300:
            return False

    # 3) 명시적 일일/프로젝트 quota 신호
    if "per day" in msg or "per-day" in msg or "perday" in msg:
        return True
    if "requestsperday" in msg or "daily" in msg:
        return True

    # 4) 불명확한 RESOURCE_EXHAUSTED — 보수적으로 backoff 로 간주 (키 유지).
    #    이전 정책과 반대: 키를 섣불리 버리면 복구 가능한 한도를 다 태우는 사고가 난다.
    return False


def _extract_retry_delay(e: Exception) -> float | None:
    """Gemini 에러 페이로드에서 retryDelay (초) 를 뽑는다. 없으면 None."""
    import re
    msg = str(e) or ""
    m = re.search(r"retry(?:Delay|In)['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s",
                  msg, flags=re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


# ─────────────────────────────────────────────────────────────
# 핵심 파서
# ─────────────────────────────────────────────────────────────

def parse_skill(
    skill_text: str,
    skill_slot: str,
    skill_name: str = "",
    *,
    rotator: Optional[ApiKeyRotator] = None,
    verbose: bool = False,
) -> SkillParsed:
    """
    스킬 텍스트 하나를 파싱해 SkillParsed 모델로 반환.

    Args:
        skill_text:  prydwen_clean.json의 descriptionLevel10 텍스트
        skill_slot:  's1', 's2', 'burst' 중 하나
        skill_name:  스킬 이름 (없으면 빈 문자열)
        rotator:     ApiKeyRotator 인스턴스. 없으면 .env 에서 자동 로드.
        verbose:     True면 토큰 사용량 / 캐시 히트 정보 출력

    Returns:
        SkillParsed (pydantic 모델)

    Raises:
        ValueError:             스키마/도메인 불변식 위반
        RuntimeError:           모든 API 키 소진 또는 재시도 한도 초과
        genai_errors.APIError:  기타 API 통신 오류
    """
    if rotator is None:
        keys, paid_indices = _load_api_keys()
        rotator = ApiKeyRotator(keys, paid_indices=paid_indices)

    system_prompt = build_system_prompt()
    user_message = (
        f"skill_name: {skill_name!r}\n"
        f"skill_slot: {skill_slot!r}\n"
        f"skill_text:\n{skill_text}"
    )

    # Gemini의 구조화 출력 — Pydantic 모델 직접 전달.
    # SDK가 Pydantic → Gemini Schema 변환을 처리하고 response.parsed 로 돌려준다.
    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=SkillParsed,
        max_output_tokens=MAX_TOKENS,
        # 추출 작업이므로 온도 0
        temperature=0.0,
        # Gemini 3은 기본적으로 thinking을 쓰며 출력 예산을 공유한다.
        # thinking이 대부분을 먹으면 JSON이 중간에 잘리는 현상이 발생 → 0으로 고정.
        thinking_config=genai_types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
    )

    last_error: Exception | None = None
    backoff_attempts = 0           # 일반 rate-limit / 5xx 재시도 카운터 (키 교체는 제외)
    max_total_calls  = RETRY_LIMIT * max(1, rotator.total)  # 키 수 × RETRY_LIMIT 까지 허용

    for call_no in range(1, max_total_calls + 1):
        try:
            response = rotator.current_client().models.generate_content(
                model=MODEL,
                contents=user_message,
                config=config,
            )

            if verbose:
                meta = getattr(response, "usage_metadata", None)
                if meta is not None:
                    # finish_reason: STOP 정상. MAX_TOKENS면 출력 잘린 것.
                    finish = None
                    cands = getattr(response, "candidates", None)
                    if cands:
                        finish = getattr(cands[0], "finish_reason", None)
                    print(
                        f"[LLM] {rotator.current_label()} "
                        f"in={getattr(meta,'prompt_token_count',0)} "
                        f"out={getattr(meta,'candidates_token_count',0)} "
                        f"think={getattr(meta,'thoughts_token_count',0)} "
                        f"cache_hit={getattr(meta,'cached_content_token_count',0)} "
                        f"finish={finish}"
                    )

            # 1순위: SDK 자동 파싱 (response_schema=Pydantic이면 채워짐)
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, SkillParsed):
                # 안전장치: SDK 가 model_construct 로 만든 경우 @model_validator
                # (도메인 불변식) 가 건너뛰어진다. 재검증해서 반드시 통과시킨다.
                parsed = SkillParsed.model_validate(parsed.model_dump())
                if verbose:
                    print("[LLM] parsed via response.parsed (re-validated)")
                return parsed

            # 2순위: 원문 JSON을 Pydantic으로 검증
            raw_text = response.text or ""
            if verbose:
                print("[LLM] raw text:")
                print(raw_text[:500])
            if not raw_text.strip():
                raise ValueError("Gemini 응답이 비어 있음 (text/parsed 모두 None)")

            raw_dict = json.loads(raw_text)
            return SkillParsed.model_validate(raw_dict)

        except (genai_errors.ServerError, genai_errors.ClientError) as e:
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            last_error = e

            # [A] 일일 quota 소진 — 현재 키 영구 폐기, 다음 키로.
            if _is_quota_error(e):
                prev = rotator.current_label()
                rotator.exhaust_current()
                if not rotator.pick_next():
                    raise RuntimeError(
                        f"모든 API 키 소진 ({rotator.total}개). 마지막 오류: {e}"
                    ) from e
                print(f"🔑 일일 quota 소진 {prev} → 전환 {rotator.current_label()} "
                      f"(남은 활성 키 {rotator.alive}/{rotator.total})")
                continue  # 키 교체는 backoff_attempts 증가 안 함

            # [B] 429 per-minute rate-limit — 현재 키 cooldown 후 다른 키로 스위치.
            #     유료 키는 무료가 전부 cooling/exhausted 일 때만 pick 된다 (tier 정책).
            if status == 429:
                retry_delay = _extract_retry_delay(e) or 60.0
                prev = rotator.current_label()
                rotator.cool_down_current(retry_delay + 2.0)
                if not rotator.pick_next():
                    raise RuntimeError(
                        f"모든 API 키 소진/cooling, 429 처리 실패. 마지막 오류: {e}"
                    ) from e
                if rotator.current_label() != prev:
                    print(f"⏳ 429 on {prev} (retry_delay={retry_delay:.1f}s) "
                          f"→ 전환 {rotator.current_label()}")
                else:
                    # pick_next 가 sleep 후 같은 키를 돌려준 경우
                    print(f"⏳ 429 on {prev} (retry_delay={retry_delay:.1f}s) "
                          f"→ 대기 후 동일 키 재사용")
                continue  # retry with (possibly) different key, no backoff_attempts bump

            # [C] 5xx 서버 에러 — 현재 키에서 지수 backoff.
            if status in (500, 502, 503, 504):
                backoff_attempts += 1
                if backoff_attempts > RETRY_LIMIT:
                    raise RuntimeError(
                        f"Backoff 재시도 {RETRY_LIMIT}회 초과. 마지막 오류: {e}"
                    ) from e
                wait = RETRY_BASE_SEC * (2 ** (backoff_attempts - 1))
                print(f"⚠️  {status} on {rotator.current_label()} "
                      f"(backoff {backoff_attempts}/{RETRY_LIMIT}), {wait:.1f}초 대기")
                time.sleep(wait)
                continue

            # 그 외 4xx (스키마 문제 등) 는 즉시 raise
            raise

        except (json.JSONDecodeError, ValueError):
            # 스키마/도메인 불변식 위반은 재시도/키 교체로 해결 안 됨
            raise

    raise RuntimeError(
        f"호출 상한 {max_total_calls}회 초과. 마지막 오류: {last_error}"
    ) from last_error


# ─────────────────────────────────────────────────────────────
# 배치 파서
# ─────────────────────────────────────────────────────────────

def _parse_character_skills(
    name_code: str,
    char_entry: dict,
    rotator: ApiKeyRotator,
    *,
    verbose: bool = False,
    existing_entry: Optional[dict] = None,
) -> tuple[dict, bool]:
    """
    단일 캐릭터(merged DB 의 roster[name_code] 항목)의 모든 스킬을 파싱한다.

    existing_entry 가 주어지면 **PARSE_ERROR 가 없는 기존 스킬은 그대로 보존**하고
    (= API 호출 스킵), PARSE_ERROR 가 있거나 기존에 없던 스킬만 재파싱한다.
    사용자가 특정 스킬을 수동 수정한 경우에도 덮어쓰기 되지 않는 것이 목적.

    반환값:
        (entry_dict, had_failure)
        entry_dict 는 skills_parsed.json 의 한 캐릭터 슬롯에 들어갈 형태:
          {
            "name_code": "1010",
            "slug": "laplace-treasure",
            "name": "Laplace (Treasure)",
            "skills": [SkillParsed.model_dump(), ...]
          }

    예외:
        RuntimeError("모든 API 키 소진 ...") 만 propagate.
        그 외 단일 스킬 실패는 entry 안에 PARSE_ERROR 플레이스홀더로 보존.
    """
    static_info = char_entry.get("static", {}) or {}
    slug        = char_entry.get("slug", name_code)
    char_name   = static_info.get("name", slug)
    skills      = static_info.get("skills", []) or []

    # 기존 스킬을 slot 기준으로 인덱싱 (각 캐릭당 s1/s2/burst 단 하나씩).
    # slot 충돌이 있다면(비정상) 마지막 항목이 우승.
    preserved: dict[str, dict] = {}
    if existing_entry is not None:
        for s in existing_entry.get("skills", []) or []:
            slot_key = s.get("skill_slot", "")
            if slot_key:
                preserved[slot_key] = s

    parsed_skills: list[dict] = []
    had_failure = False

    for skill in skills:
        desc = skill.get("descriptionLevel10", "")
        if not desc:
            continue

        slot = _normalize_slot(skill.get("slot", ""))
        name = skill.get("name", "")

        # 기존 항목이 깨끗(PARSE_ERROR 없음)하면 그대로 유지하고 API 호출 스킵.
        prev = preserved.get(slot)
        if prev is not None:
            prev_note = prev.get("parsing_notes") or ""
            if "[PARSE_ERROR]" not in prev_note:
                print(f"  [OK] [{name_code}/{slug}] {name} ({slot}) - 기존 파싱 보존")
                parsed_skills.append(prev)
                continue

        try:
            parsed = parse_skill(desc, slot, name, rotator=rotator, verbose=verbose)
            parsed_skills.append(parsed.model_dump())
        except RuntimeError as e:
            # 모든 키 소진은 호출자가 처리해야 함 (전체 batch 중단 대상)
            if "모든 API 키 소진" in str(e):
                raise
            print(f"  ❌ [{name_code}/{slug}] {name} ({slot}) 파싱 실패: {e}")
            parsed_skills.append({
                "skill_name": name,
                "skill_slot": slot,
                "raw_text": desc,
                "groups": [],
                "stack_conditions": None,
                "parsing_notes": f"[PARSE_ERROR] {e}",
            })
            had_failure = True
        except Exception as e:
            print(f"  ❌ [{name_code}/{slug}] {name} ({slot}) 파싱 실패: {e}")
            parsed_skills.append({
                "skill_name": name,
                "skill_slot": slot,
                "raw_text": desc,
                "groups": [],
                "stack_conditions": None,
                "parsing_notes": f"[PARSE_ERROR] {e}",
            })
            had_failure = True

    # status: 'completed' (모든 스킬 깨끗) / 'pending' (PARSE_ERROR 남아있음).
    # 사용자가 이 필드를 수동으로 'pending' 으로 바꾸면 다음 batch 실행에서 재파싱 대상이 됨
    # (단, 깨끗한 스킬은 per-skill preservation 으로 보존됨 — 토큰 낭비 없음).
    status = "pending" if had_failure else "completed"

    entry = {
        "name_code": name_code,
        "slug":      slug,
        "name":      char_name,
        "status":    status,
        "skills":    parsed_skills,
    }
    return entry, had_failure


def parse_owned_roster(
    merged_db_path: str,
    output_path: str,
    *,
    overwrite: bool = False,
    verbose: bool = False,
) -> dict[str, dict]:
    """
    nikke_merged_db_returned.json 의 roster (사용자 보유 캐릭터)에 한해
    모든 스킬을 파싱해 JSON으로 저장.

    출력 형식 (name_code 가 최상위 key):
        {
          "1010": {
            "name_code": "1010",
            "slug": "laplace-treasure",
            "name": "Laplace (Treasure)",
            "status": "completed",           # 'completed' | 'pending'
            "skills": [ ... SkillParsed.model_dump() ... ]
          },
          ...
        }

    스킵 규칙 (overwrite=False 기본):
      - entry.status == "completed"   → skip (API 호출 0)
      - entry.status == "pending"
        또는 status 필드 없음           → 파싱. 이 때 개별 스킬 레벨에서
                                          per-skill preservation 이 적용되어,
                                          PARSE_ERROR 없는 스킬은 그대로 유지됨.
      - 파싱 종료 후 모든 스킬이 깨끗하면 status → "completed" 자동 기록.

    overwrite=True 면 status 무시하고 모두 재파싱 (preservation 도 무시).

    Args:
        merged_db_path: Database/processed/nikke_merged_db_returned.json 경로
        output_path:    출력 파일 경로 (예: Database/processed/skills_parsed.json)
        overwrite:      True 이면 전체 강제 재파싱. False 면 status 기반 스킵.
        verbose:        True면 각 스킬 응답 토큰 정보 출력

    참고:
      - 사용자가 새로 캐릭터를 획득하면 merged DB 가 갱신되므로,
        overwrite=False 로 다시 실행하면 신규 캐릭(= status 없음)만 파싱됨.
      - 특정 캐릭을 수동으로 재검토하고 싶다면, skills_parsed.json 에서
        해당 캐릭 entry 의 status 를 "pending" 으로 바꾼 뒤 실행.
    """
    with open(merged_db_path, "r", encoding="utf-8") as f:
        merged_data: dict = json.load(f)

    roster: dict = merged_data.get("roster") or {}
    if not roster:
        raise RuntimeError(
            f"roster 가 비어 있음: {merged_db_path} 의 'roster' 필드를 확인하세요."
        )

    # 기존 결과 로드 (overwrite=False면 이어쓰기)
    results: dict[str, dict] = {}
    if not overwrite and os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            results = json.load(f)
        print(f"💾 기존 파싱 결과 로드: {len(results)}명")

    keys, paid_indices = _load_api_keys()
    rotator = ApiKeyRotator(keys, paid_indices=paid_indices)
    if paid_indices:
        free_n = rotator.total - len(paid_indices)
        print(f"🔑 API 키 {rotator.total}개 로드 완료 "
              f"(free {free_n} + paid {len(paid_indices)}; 유료는 fallback)")
    else:
        print(f"🔑 API 키 {rotator.total}개 로드 완료")

    total   = len(roster)
    skipped = 0
    success_chars = 0
    failed: list[str] = []

    for idx, (name_code, char) in enumerate(roster.items(), 1):
        slug = char.get("slug", name_code)
        existing = results.get(name_code)

        # status 기반 스킵: 'completed' 면 전체 캐릭 skip.
        # status 필드가 없거나 'pending' 이면 파싱 대상.
        # 레거시 entry (status 없음) 는 보수적으로 pending 간주 → 재파싱 후보.
        status_now = (existing or {}).get("status")

        if not overwrite and status_now == "completed":
            skipped += 1
            continue
        if not overwrite and existing and status_now != "completed":
            print(f"  ↻ {name_code}/{slug}: status={status_now!r} → 재파싱 "
                  f"(깨끗한 스킬은 보존)")

        static_info = char.get("static", {}) or {}
        char_name   = static_info.get("name", slug)
        skill_count = len(static_info.get("skills", []) or [])

        print(f"[{idx:3}/{total}] {char_name} ({name_code}/{slug}) — {skill_count}개 스킬")

        # overwrite=False 일 때는 기존 깨끗한 스킬을 보존. overwrite=True 여도 안전장치로
        # 전체 덮어쓰기를 원하면 기존 entry 를 None 으로 넘긴다.
        prior_entry = existing if not overwrite else None

        try:
            entry, had_failure = _parse_character_skills(
                name_code, char, rotator, verbose=verbose,
                existing_entry=prior_entry,
            )
        except RuntimeError as e:
            # 모든 키 소진: 여기서 중단. 이어서 쓰기 안전.
            print(f"  🛑 [{name_code}/{slug}] {e}")
            _save(results, output_path)
            print("중단: .env 에 키를 추가하거나 quota 회복 후 재실행하세요.")
            raise

        results[name_code] = entry
        success_chars += 1
        if had_failure:
            failed.append(f"{name_code}/{slug}")

        # 캐릭터 1명 처리할 때마다 저장. Ctrl+C 중단돼도 직전 캐릭터까지 보존.
        _save(results, output_path)

    # 최종 저장
    _save(results, output_path)

    print(f"\n✅ 완료: 처리 {success_chars}명, 건너뜀 {skipped}명")
    if failed:
        print(f"⚠️  파싱 실패 포함 캐릭터 ({len(failed)}명): {', '.join(failed[:10])}")

    return results


def parse_character_on_demand(
    name_code: str,
    merged_db_path: str,
    output_path: str,
    *,
    verbose: bool = False,
) -> dict:
    """
    지정한 단일 캐릭터(name_code) 의 스킬만 파싱해 skills_parsed.json 에 업서트.

    용도:
        - 미보유 캐릭터로 이론상 빌드를 짜는 시나리오.
        - 시뮬레이터가 lookup 실패 시 호출하는 lazy fallback.

    parse_owned_roster 와 달리 roster 가 아니라 merged DB 전체에서 name_code 를 찾으므로,
    사용자가 보유하지 않은 캐릭터도 처리 가능하다 (단, merged DB 에 entry 가 있어야 함).
    """
    with open(merged_db_path, "r", encoding="utf-8") as f:
        merged_data: dict = json.load(f)

    # 1) roster 안 보유분에서 우선 조회
    char = (merged_data.get("roster") or {}).get(name_code)

    # 2) roster 에 없으면 merged DB 의 다른 색인(있다면)도 시도.
    #    현재 스키마는 roster 만 갖고 있어서 미보유 캐릭은 별도 카탈로그가 필요함.
    #    카탈로그가 추가되기 전까지는 roster 한정으로만 동작.
    if char is None:
        raise RuntimeError(
            f"name_code={name_code!r} 가 roster 에 없습니다. "
            f"미보유 캐릭터의 lazy 파싱을 위해서는 merged DB 에 전체 카탈로그가 필요합니다."
        )

    keys, paid_indices = _load_api_keys()
    rotator = ApiKeyRotator(keys, paid_indices=paid_indices)

    results: dict[str, dict] = {}
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            results = json.load(f)

    entry, had_failure = _parse_character_skills(
        name_code, char, rotator, verbose=verbose,
        existing_entry=results.get(name_code),
    )
    results[name_code] = entry
    _save(results, output_path)

    if had_failure:
        print(f"⚠️  {name_code} 일부 스킬 파싱 실패 (PARSE_ERROR 표식 보존됨)")
    else:
        print(f"✅ {name_code} 파싱 완료")
    return entry


# 후방 호환 alias — 이전 코드에서 parse_all_skills 를 import 하던 경우 대비
parse_all_skills = parse_owned_roster


def _has_parse_error(entries: list[dict]) -> bool:
    """entries 중 하나라도 PARSE_ERROR 흔적을 가지면 True."""
    for e in entries:
        note = e.get("parsing_notes") or ""
        if "[PARSE_ERROR]" in note:
            return True
    return False


def _normalize_slot(raw: str) -> str:
    """
    'Skill 1' → 's1', 'Skill 2' → 's2', 'Burst' → 'burst'.
    Burst를 먼저 검사해서 'Burst Skill 1' 류의 오분류를 막는다.
    """
    r = raw.strip().lower()
    if "burst" in r:
        return "burst"
    if "1" in r:
        return "s1"
    if "2" in r:
        return "s2"
    return r


def _save(data: dict, path: str) -> None:
    # dirname이 빈 문자열이면 makedirs("")가 FileNotFoundError를 던지므로 가드.
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    DEFAULT_IN  = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "nikke_merged_db_returned.json")
    DEFAULT_OUT = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "skills_parsed.json")

    parser = argparse.ArgumentParser(description="NIKKE 스킬 LLM 파서 (Gemini 3 Flash)")
    parser.add_argument("--input",     default=DEFAULT_IN,
                        help="nikke_merged_db_returned.json 경로 (roster 기반)")
    parser.add_argument("--output",    default=DEFAULT_OUT, help="출력 JSON 경로")
    parser.add_argument("--overwrite", action="store_true", help="기존 결과 무시하고 전체 재파싱")
    parser.add_argument("--verbose",   action="store_true", help="토큰 사용량 출력")
    parser.add_argument("--single",    metavar="TEXT",
                        help="단일 스킬 텍스트 테스트 (DB 미접근, 결과를 stdout 으로만 출력)")
    parser.add_argument("--slot",      default="s1",        help="--single 사용 시 슬롯 (s1/s2/burst)")
    parser.add_argument("--character", metavar="NAME_CODE",
                        help="단일 캐릭터(name_code) 만 파싱하여 출력 JSON 에 업서트 "
                             "(이론상 빌드 / lazy fallback 용)")
    args = parser.parse_args()

    if args.single:
        result = parse_skill(args.single, args.slot, verbose=args.verbose)
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    elif args.character:
        parse_character_on_demand(
            args.character,
            args.input,
            args.output,
            verbose=args.verbose,
        )
    else:
        parse_owned_roster(
            args.input,
            args.output,
            overwrite=args.overwrite,
            verbose=args.verbose,
        )
