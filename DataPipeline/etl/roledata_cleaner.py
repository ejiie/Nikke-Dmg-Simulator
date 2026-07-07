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

weaponData 블록(2026-07-01 유실분 복구·2026-07-02 재통합) — roledata shot/top-level 의 유의미
무기 데이터를 엔진이 쓰도록 노출. (주의: 기존 `weapon` 키는 롱폼 무기타입 문자열 — 충돌 회피 위해
프로파일은 `weaponData`.)
단위 역공학(blabla_roledata 실값 검증; ETL 정규화 채택):
  fireRate     = shot.rate_of_fire / 60      (raw=RPM → 발/sec. AR 720→12, SMG 1440→24, MG 60→1 spin-up)
  *Sec         = (charge/reload/reset/spot_delay/burst_duration/apply_delay) / 100   (raw=centisec → sec)
  fullChargeDamage = full_charge_damage / 10000   (SR 25000→2.5, RL 35000→3.5, 비차지 10000→1.0)
  coreDamageRate   = core_damage_rate / 10000     (20000→2.0; coreHitBonus = 이값-1)
  reloadBulletRate = reload_bullet / 10000        (10000→1.0=전탄, 3300→0.33=부분장전)
  accuracy.*Circle = *_accuracy_circle_scale (raw spread 반지름; SR/RL 10 핀포인트, MG 250→10 spin-up)
  burst.energyPerShot / targetEnergyPerShot / fullChargeEnergy = raw 게이지 단위
    (총량 상수 확보됨: burst_gauge_table.json burst_energy_max=1,000,000 — 정규화는 K9 버스트 게이지 구현 시)
  shotCount/muzzleCount/penetration/spotRadius/spotExplosionRange/maxAmmo/reloadStartAmmo = raw (이미 사용 단위)
※ accuracy→코어힛 확률, weaponType→적정거리 구간은 C# 모델(AccuracyModel/ProperDistanceTable)에서 소비.
※ spotFirstDelaySec/spotLastDelaySec 단위·semantics 확정(2026-07-08, einkk timeDataToFrame=t×fps/100 검증):
  first=사격 진입 후 첫 발사/차지 전 대기(0.2s 지배적), last=SR/RL 발사 후 엄폐 복귀(0.2s). 구 0.03s 설 폐기.
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


def _num(d, k):
    """None 안전 숫자 getter (raw 0 보존)."""
    return d.get(k) or 0


def _weapon(c, shot):
    """엔진이 소비하는 무기 프로파일(발사속도/탄창/차지/명중원/버스트게이지/멀티펠릿).

    weaponType 는 raw 단축코드(SG/SMG/AR/MG/SR/RL) 그대로 — C# 측은 static.weapon(롱폼)으로
    적정거리 룩업하므로 여기 단축코드는 참조/검증용. accuracy 는 manual + auto(aim) 2세트.
    """
    shot = shot or {}
    return {
        "weaponType": shot.get("weapon_type"),                       # SG/SMG/AR/MG/SR/RL
        "isChargeWeapon": _num(shot, "charge_time") > 0,
        # SR/RL 부류 판별 (2026-07-08 확정, ENGINE_GUIDE §5): UP=릴리즈 발사(maintain=0 이면 발사 후
        # 강제 엄폐 복귀) / DOWN_Charge=only 풀차지(릴리즈 발사 불가) / DOWN=평사(Pascal).
        "inputType": shot.get("input_type"),
        "fireType": shot.get("fire_type"),                           # Instant/Projectile* (발사 이벤트 타이밍)
        # >0 = 발사 후 복귀 없이 자세 유지, 값=자체 후딜레이 (SBS 0.23 / Raven 0.83 / A2 0.84s)
        "maintainFireStanceSec": _num(shot, "maintain_fire_stance") / 100.0,
        "upTypeFireTiming": _num(shot, "uptype_fire_timing") / 10000.0,  # 투사체 발사 이벤트 시점 비율
        "spotProjectileSpeed": shot.get("spot_projectile_speed"),
        # 발사속도 (raw=RPM → 발/sec). MG 는 spin-up: fireRate(시작)→endFireRate, 발당 rampPerShot 증가.
        "fireRate": _num(shot, "rate_of_fire") / 60.0,
        "endFireRate": _num(shot, "end_rate_of_fire") / 60.0,
        "fireRateRampPerShot": _num(shot, "rate_of_fire_change_pershot") / 60.0,
        "fireRateResetTimeSec": _num(shot, "rate_of_fire_reset_time") / 100.0,
        # 발사 개시/종료 모션 딜레이 (대부분 0.2s; 구 실측 0.03s 와 상충 — 캘리브레이션 대기)
        "spotFirstDelaySec": _num(shot, "spot_first_delay") / 100.0,
        "spotLastDelaySec": _num(shot, "spot_last_delay") / 100.0,
        # 탄창/재장전
        "maxAmmo": shot.get("max_ammo"),
        "reloadTimeSec": _num(shot, "reload_time") / 100.0,
        "reloadBulletRate": _num(shot, "reload_bullet") / 10000.0,   # 1.0=전탄, 0.33=부분
        "reloadStartAmmo": shot.get("reload_start_ammo"),
        # 차지 (SR/RL)
        "chargeTimeSec": _num(shot, "charge_time") / 100.0,
        "fullChargeDamage": _num(shot, "full_charge_damage") / 10000.0,
        # 멀티펠릿/투사체
        "shotCount": shot.get("shot_count"),                         # SG 펠릿 5~10
        "muzzleCount": shot.get("muzzle_count"),                     # 총구 1~2
        "penetration": shot.get("penetration"),
        "spotRadius": shot.get("spot_radius"),                       # RL 스플래시
        "spotExplosionRange": shot.get("spot_explosion_range"),
        "coreDamageRate": _num(shot, "core_damage_rate") / 10000.0,  # 2.0 (coreHitBonus=이값-1)
        # 명중원 (spread 반지름; manual + auto). AccuracyModel 이 코어힛/명중 확률로 소비.
        "accuracy": {
            "startCircle": shot.get("start_accuracy_circle_scale"),
            "endCircle": shot.get("end_accuracy_circle_scale"),
            "changePerShot": shot.get("accuracy_change_pershot"),
            "changeSpeed": shot.get("accuracy_change_speed"),
            "autoStartCircle": shot.get("auto_start_accuracy_circle_scale"),
            "autoEndCircle": shot.get("auto_end_accuracy_circle_scale"),
            "autoChangePerShot": shot.get("auto_accuracy_change_pershot"),
            "autoChangeSpeed": shot.get("auto_accuracy_change_speed"),
        },
        # 버스트 게이지 (raw 단위; 게이지 총량 상수 확정 시 정규화)
        "burst": {
            "energyPerShot": shot.get("burst_energy_pershot"),
            "targetEnergyPerShot": shot.get("target_burst_energy_pershot"),
            "fullChargeEnergy": shot.get("full_charge_burst_energy"),
            "durationSec": _num(c, "burst_duration") / 100.0,        # 1000→10s (풀버스트 창)
            "applyDelaySec": _num(c, "burst_apply_delay") / 100.0,
            "useBurstSkill": c.get("use_burst_skill"),               # Step1/2/3/AllStep
            "changeBurstStep": c.get("change_burst_step"),
        },
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
            "weaponData": _weapon(c, shot),         # 무기 프로파일(발사속도/명중원/모션/펠릿/게이지)
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
