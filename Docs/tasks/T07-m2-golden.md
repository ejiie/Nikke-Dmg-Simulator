# T07 — M2 in-game 골든 대조 (사용자 협업, 상시)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: 하네스 ✅ (즉시 가능).

## 목표
실캐릭 sim 총딜/타임라인을 in-game 실측과 대조 — 타이밍·펠릿·가정의 최종 확증. per-hit 공식(Tier 1)은 이미 ≤1.3e-7.

## 절차
1. 사용자: 훈련장/실전에서 **버프 없는(또는 알려진 버프) 단일 캐릭** N초 사격 → 총딜(또는 발사수/DPS) 기록.
2. `nikke-harness run <name_code> --sec N [--manual] [--reload-buff ..] [--def ..]` (merged DB 필요).
3. 대조 → 어긋나면 용의자: SG 펠릿 개별 롤 가정 · W=펠릿당 · 차지속도 감쇠식(÷(1+Σ) 대안) · spot delay 실단위.

## 승격 대상 (대조로 확정 시 FACTS 갱신)
- SG 펠릿 모델 확정 (FACTS §8).
- `EffectRoute.Unverified` 타입 브래킷 배정 (FullBurstDamage·AddDamage 620 등) → 정식 슬롯 (SkillTranslator).
- 차지속도 감쇠식·타겟 반지름·ProperDistance 0.3.
- **spot_last(모션 후딜) 적용 범위** (2026-07-11 미정 강등 — FACTS §8): 전 무기 0.2s vs einkk(UP형만, 외 0).
  판별 실험: 비-UP 무기(AR/SMG/MG)로 사격→엄폐→재조준 사이클 실측 — 후딜 유무가 사이클 길이에 12f 차이.

## 산출
- 대조표(캐릭/조건/실측/sim/오차) → VERIFICATION_LOG. FACTS §8 항목 하나씩 해소.
- WUnitFoundationTests 의 in-game 수치 잠금 TODO 도 여기서.

## 함정
- 실측 조건 통제 (버프·큐브·거리·타겟 DEF 명시) — 안 맞으면 원인 불명. 스킬 패시브 있는 캐릭은 T01 후 대조.
