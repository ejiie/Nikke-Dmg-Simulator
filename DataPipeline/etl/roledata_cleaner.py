"""roledata(blabla_roledata.json) → roledata_clean.json (name_code 키).

prydwen_cleaner 를 대체. blablalink 공식 roledata 를 db_merger 가 쓰던 static 블록과
**동일한 키 형태**로 정제한다(name/element/weapon/class/burstType/manufacturer/ammoCapacity/
reloadTime/iconUrl/basicAttack/skills). 단 키는 slug 가 아니라 **name_code** — db_merger 가
유저데이터(name_code)와 직접 조인하므로 name_code↔slug 매핑(auto_mapper)이 더 이상 불필요.

basicAttack 단위 변환(45캐릭 prydwen 교차검증 일치):
  multiplier   = shot.damage / 100
  coreHitBonus = shot.core_damage_rate / 10000 - 1
  chargeTime   = shot.charge_time / 100
  chargeDamage = shot.full_charge_damage / 10000     (비차지 = 10000 → 1.0)

weaponData 블록(발사 ramp/명중원/모션/펠릿/버스트게이지)은 **raw 보존** — 단위 변환 없음,
정규화는 소비측(C#) 단일 지점 (W 단위 정규화 위치 결정과 동일 원칙, DESIGN §6).
  단위: rate* = 발/분 (/60 = 발/초; AR 720→12/s, SMG 1440→24/s 캘리브레이션 확정)
        *Delay / rateOfFireResetTime = 1/100 초
        accuracy*Scale = 명중원 스케일 (작을수록 조밀; MG 250→10 연사 수축)
  ※ 키는 'weaponData' — 기존 'weapon'(무기타입 문자열)과 충돌 금지.
"""
import json
import os
from collections import Counter

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_roledata.json")
PROCESSED_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed")
PROCESSED_FILE = os.path.join(PROCESSED_DIR, "roledata_clean.json")
PROPER_DIST_FILE = os.path.join(PROCESSED_DIR, "proper_distance_table.json")

# roledata → 기존 contract 정규화 (prydwen_cleaner 와 동일 타깃 포맷)
WEAPON_MAP = {
    "AR": "Assault Rifle", "RL": "Rocket Launcher", "SR": "Sniper Rifle",
    "SG": "Shotgun", "MG": "Minigun", "LMG": "Minigun", "SMG": "SMG",
}
ELEMENT_MAP = {"Electronic": "Electric"}  # 나머지(Fire/Water/Wind/Iron)는 동일


def _burst_type(use_burst_skill):
    s = use_burst_skill or ""
    return s[4:] if s.startswith("Step") else s   # "Step3" → "3", "StepAll" → "All"


def _basic_attack(shot):
    shot = shot or {}
    return {
        "multiplier": (shot.get("damage") or 0) / 100.0,
        "coreHitBonus": (shot.get("core_damage_rate") or 0) / 10000.0 - 1.0,
        "chargeTime": (shot.get("charge_time") or 0) / 100.0,
        "chargeDamage": (shot.get("full_charge_damage") or 0) / 10000.0,
    }


def _weapon_data(shot):
    """shot 블록 → weaponData (raw 보존; 단위는 모듈 docstring 참조)."""
    shot = shot or {}
    return {
        # 발사 속도 ramp (발/분). MG 만 start≠end (60→4200, 발당 +100, 사격중단 reset 후 원복)
        "rateOfFire": shot.get("rate_of_fire"),
        "endRateOfFire": shot.get("end_rate_of_fire"),
        "rateOfFireChangePerShot": shot.get("rate_of_fire_change_pershot"),
        "rateOfFireResetTime": shot.get("rate_of_fire_reset_time"),
        # 발사 전/후 모션 딜레이 (1/100초; 대부분 20)
        "spotFirstDelay": shot.get("spot_first_delay"),
        "spotLastDelay": shot.get("spot_last_delay"),
        # 명중원 (연사 streak 수축; 작을수록 조밀)
        "startAccuracyCircleScale": shot.get("start_accuracy_circle_scale"),
        "endAccuracyCircleScale": shot.get("end_accuracy_circle_scale"),
        "accuracyChangePerShot": shot.get("accuracy_change_pershot"),
        "accuracyChangeSpeed": shot.get("accuracy_change_speed"),
        # 멀티펠릿 (SG shotCount=10 — 1클릭당 펠릿 수)
        "shotCount": shot.get("shot_count"),
        "muzzleCount": shot.get("muzzle_count"),
        # 버스트 게이지 충전 (raw; 게이지 총량 상수 미확정)
        "burstEnergyPerShot": shot.get("burst_energy_pershot"),
        "targetBurstEnergyPerShot": shot.get("target_burst_energy_pershot"),
    }


def clean_roledata():
    print("🧼 roledata 정제 시작 (blablalink 공식 → prydwen_clean 호환, name_code 키)...")
    if not os.path.exists(RAW_FILE):
        print(f"❌ 원본 파일이 없음: {RAW_FILE}")
        raise SystemExit(1)

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        roster = json.load(f).get("roster", {})

    clean = {}
    for nc, c in roster.items():
        shot = c.get("shot") or {}
        clean[nc] = {
            "name_code": c.get("name_code"),
            "name": c.get("name"),
            "element": ELEMENT_MAP.get(c.get("element"), c.get("element")),
            "weapon": WEAPON_MAP.get((shot.get("weapon_type")), shot.get("weapon_type")),
            "class": c.get("class"),
            "burstType": _burst_type(c.get("use_burst_skill")),
            "manufacturer": (c.get("corporation") or "").capitalize() or None,
            "ammoCapacity": shot.get("max_ammo"),
            "reloadTime": (shot.get("reload_time") or 0) / 100.0,
            "iconUrl": f"portraits/si/{nc}.webp",   # 로컬 초상화(getFromBlaLinkPortraits), name_code 키
            "basicAttack": _basic_attack(shot),
            "weaponData": _weapon_data(shot),       # 발사 ramp/명중원/모션/펠릿/게이지 (raw)
            "squad": c.get("squad"),                # 동일 스쿼드 아군 조건 버프용
            # 적정거리 보너스 범위(per-char; 무기별 결정, SR 1명 예외 보존)
            "properRange": {"min": c.get("bonusrange_min"), "max": c.get("bonusrange_max")},
            "skills": c.get("skills"),              # 공식 구조화 스킬(skill1/skill2/burst)
        }

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    print(f"✅ 총 {len(clean)}명 정제 완료 → '{PROCESSED_FILE}'")

    # 적정거리(proper distance) 보너스 범위 — 무기별 1개 (최빈값). 엔진 ProperDistanceTable 소스.
    per_weapon = {}
    counts = {}
    for ch in clean.values():
        w = ch.get("weapon")
        pr = ch.get("properRange") or {}
        if w is None or pr.get("min") is None:
            continue
        counts.setdefault(w, Counter())[(pr["min"], pr["max"])] += 1
    for w, cnt in counts.items():
        (mn, mx), _ = cnt.most_common(1)[0]
        per_weapon[w] = {"min": mn, "max": mx}
    with open(PROPER_DIST_FILE, "w", encoding="utf-8") as f:
        json.dump(per_weapon, f, ensure_ascii=False, indent=2)
    outliers = {w: dict(cnt) for w, cnt in counts.items() if len(cnt) > 1}
    print(f"🎯 적정거리 무기별표 → '{PROPER_DIST_FILE}' ({per_weapon})")
    if outliers:
        print(f"   ⚠️ 무기 내 범위 불일치(최빈값 채택): {outliers}")


if __name__ == "__main__":
    clean_roledata()
