# SKILL_MISMAPPING_GUARD — 스킬 파싱 오매핑 방지 가이드

> LLM 스킬 파서가 **"스키마에 맞는 칸이 없을 때 비슷한 칸에 억지로 우겨넣어"**
> 대미지를 조용히 왜곡하는 현상을 막기 위한 규칙. 이 문서는 LLM 시스템 프롬프트에
> 주입되거나 few-shot 음성 예시로 쓰인다.
>
> 근거: 2026-05-26 `skills_parsed.json` 전수 스캔에서 **오매핑 의심 65건** 검출.
> 그중 `Hit Rate → crit_rate` 28건은 대미지를 직접 부풀린다.

---

## 0. 한 줄 원칙

> **빈칸을 억지로 채우지 마라.** 스키마에 정확히 맞는 stat이 없으면,
> ① 대미지 무관이면 실제 이름 + `formula_bracket=null` + `dps_scope=false`,
> ② 스키마에 stat 자체가 없으면 `@토큰`(핸들러행).
> **절대로 대미지 영향 stat(crit_rate / atk_pct / *_dmg)으로 대체하지 마라.**

---

## 1. 왜 치명적인가

대미지 공식(B2~B5)에 들어가는 stat과 안 들어가는 stat이 있다.
명중률(Hit Rate)은 **대미지 공식에 없다.** 그런데 치명타 확률(crit_rate)은 **B2에 들어간다.**

`Hit Rate ▲ 38.91%` 를 `crit_rate=38.91` 로 매핑하면:
- 명중률 버프(대미지 0 영향)가 → 크리 확률 +38.91%p 로 둔갑.
- 시뮬레이터가 **없는 대미지를 만들어낸다.** 파싱은 "성공"으로 보이지만 의미가 틀림.

이것이 "파싱은 됐는데 의미적으로 구현이 안 됨"의 전형이다.

---

## 2. 검출된 오매핑 패턴 (실데이터)

| 원문 stat | 잘못 매핑된 칸 | 건수 | 위험 | 올바른 처리 |
|---|---|---:|---|---|
| **Hit Rate (명중률)** | `crit_rate` | 28 | 🔴 대미지 부풀림 | `stat=hit_rate`, `formula_bracket=null`, `dps_scope=false` |
| **ATK Speed (공격 속도)** | `attack_dmg`(B3) / `move_speed` | 4 | 🔴 한 발 대미지 부풀림 | `stat=@atk_speed`. 공속=발사 **타이밍**축(시간당 히트수), per-hit 배율 아님. 로테이션 엔진 소관. 예: sugar(66%), soline |
| **Shield Damage (실드 대미지)** | `parts_dmg` / `attack_dmg` | 4 | 🔴 본체 대미지 폭발 | `stat=@shield_damage`. 실드는 별도 HP풀. 예: rei-ayanami(**700.5%!**) — parts_dmg(B3)에 들어가면 본체에 700% 적용됨 |
| **Explosion Range / AoE** | `atk_pct` (value=0) | ~11 | 🔴 (값 0이라 당장은 무해하나 칸이 틀림) | `stat=@ExplosionRange` (미지원, 핸들러행) |
| **Full Burst Time 연장** | `burst_gauge` | 8 | 🟡 의미 다름 | `stat=@FullBurstExtension` 또는 시간축 전용 stat |
| **Sustained Damage** | `dot_dmg` | 5 | 🟢 대체로 정당 (지속=DoT) | 단, `deal_damage`면 계수, `buff`면 B3 — action으로 구분 |
| **각종 면역/무적** | `immunity` | 5 | 🟡 종류 뭉개짐 | `grant_immunity` + `immunity_target=@Stun` 등 |

> 🟢 Sustained Damage→dot_dmg 는 의미상 맞다(지속 대미지 = DoT 계열).
> 나머지 🔴🟡 는 교정 대상.

---

## 3. LLM 파싱 규칙 (DO / DON'T)

### DON'T (금지)
- ❌ "as closest proxy" / "as a placeholder" 로 **대미지 영향 stat**(crit_rate, atk_pct,
  attack_dmg, crit_dmg, *_dmg, strong_elem, charge_dmg*)에 매핑.
- ❌ 모르는 효과를 0 값으로 아무 칸에나 넣기.
- ❌ 명중률(Hit Rate) ↔ 치명타율(Critical Rate) 혼동. **완전히 다른 스탯.**

### DO (권장)
- ✅ **대미지 무관이지만 stat 이름이 스키마에 있으면**: 그 이름 그대로 +
  `formula_bracket=null` + `dps_scope=false`.
  (엔진이 "안다, 그러나 DPS엔 미반영"으로 분류 → 커버리지에 정직하게 잡힘)
- ✅ **스키마에 stat 자체가 없으면**: `stat=@<원문이름>` (@ 접두사).
  핸들러 레지스트리가 처리하거나 "미지원"으로 카운트.
- ✅ 애매하면 `notes`에 원문을 보존하되, **값은 대미지축에 절대 넣지 않는다.**

---

## 4. 스키마 측 안전장치 (구현 시)

1. **`dps_scope` 필드**: `false` 면 어떤 브래킷 합산에도 안 들어감. 명중률/이속/엄폐 등.
2. **`@stat` 규약**: stat 값이 `@` 로 시작하면 generic 엔진은 건드리지 않고 핸들러로.
   미등록 핸들러면 로더가 "unsupported" 로 카운트(커버리지 지표).
3. **로더 검증**: `formula_bracket != null` 인데 stat이 대미지 무관 목록에 있으면 **에러**.
   (Hit Rate가 b2_crit_core에 들어오는 사고를 빌드 타임에 차단.)
4. **재파싱 시 교차검증**: 기존 `skills_parsed.json`의 §2 패턴(특히 Hit Rate→crit_rate
   28건)은 **이미 틀린 값**이므로, 새 스키마 재파싱 때 이 문서를 프롬프트에 넣어 재발 방지.

---

## 5. 대미지 영향 / 무영향 stat 분류표 (판정 기준)

**대미지 영향 (여기에 오매핑하면 🔴)**:
`crit_rate`(B2 확률축), `crit_dmg`(B2), `core_hit_buff`(B2),
`attack_dmg`/`pierce_dmg`/`parts_dmg`/`dot_dmg`/`sequential_dmg`(B3),
`damage_taken`/`distrib_dmg`(B4), `strong_elem`(B5),
`charge_dmg`/`charge_dmg_mult`(계수), `atk_pct`/`atk_flat`(ATK), `true_dmg`.

**대미지 무영향 (`dps_scope=false` 대상)**:
`hit_rate`(명중률), `move_speed`, `reload_speed`(직접 영향 X, 로테이션 간접),
`immunity`, `hp_potency`, `heal`/`lifesteal`/`shield`(생존), `burst_gauge`/`burst_cooldown`(로테이션 간접).

> 로테이션(시간축)으로 **간접** 영향 주는 것(reload/charge_speed/burst_gauge)은
> `dps_scope=false` 로 두되, 로테이션 시뮬 단계에서 별도 소비. 직접 대미지 브래킷엔 금지.
