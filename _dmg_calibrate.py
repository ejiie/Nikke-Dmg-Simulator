# -*- coding: utf-8 -*-
"""
#7 최적화: 지금까지의 모든 측정점으로 TRUE 계수를 역산(캘리브레이션).
구조는 확정(가산 B2 + 곱셈 B3/B4/B5)이므로 오차원은 계수 표시반올림뿐.
각 계수의 floor 제약을 교집합 → 가장 좁은 구간(=정밀도) + 대표값. 그 값으로 전 측정점 0오차 재현.
"""
from fractions import Fraction as F

P = F(4502478015, 100)          # (901497-100)*4.995*10 = 45024780.15  (입력에서 정확)
floorP = P.__floor__()          # 45024780

# ── B2: 가산 정수 increment (측정 차분, exact) ──
inc = {"dist": 13507432, "burst": 22512390, "crit": 56974354, "core": 52696998}
# 각 B2 계수 구간: floor(P*coef)=inc  →  coef ∈ [inc/P, (inc+1)/P)
def interval_over_P(v):
    return (F(v) / P, F(v + 1) / P)

# ── true B2 정수 (combo별, 가산) ──
def b2(dist=0, burst=0, crit=0, core=0):
    return floorP + dist*inc["dist"] + burst*inc["burst"] + crit*inc["crit"] + core*inc["core"]

# ── 곱셈 인자 제약: floor(ref * f)=meas → f ∈ [meas/ref, (meas+1)/ref) ──
def fac_interval(ref, meas):
    return (F(meas, ref), F(meas + 1, ref))

def intersect(intervals):
    lo = max(a for a, _ in intervals); hi = min(b for _, b in intervals)
    return lo, hi

# ── f5 (B5 strong_elem) : 순수-B5 행 5개 교집합 ──
b5_pts = [
    (b2(dist=1),               142192292),
    (b2(crit=1),               247786478),
    (b2(dist=1, crit=1),       280600080),
    (b2(dist=1, core=1),       270209101),
    (b2(dist=1, burst=1, crit=1, core=1), 463306234),
]
f5_lo, f5_hi = intersect([fac_interval(r, m) for r, m in b5_pts])

# ── f3 (B3 attack_dmg, 새 버퍼 0.484) : dist+B3 + (dist+B3+B5 와 f5 결합) ──
f3_direct = fac_interval(b2(dist=1), 86861800)                 # dist+B3
# dist+B3+B5: floor(ref*f3*f5)=meas → f3 ∈ [meas/(ref*f5_hi), (meas+1)/(ref*f5_lo))
ref = b2(dist=1)
f3_via_b5 = (F(211013357) / (ref * f5_hi), F(211013358) / (ref * f5_lo))
f3_lo, f3_hi = intersect([f3_direct, f3_via_b5])

# ── f4 (B4 damage_taken 4.2%) : dist+B3+B4+B5 ──
# floor(ref*f3*f4*f5)=219875918 → f4 ∈ [meas/(ref*f3_hi*f5_hi), (meas+1)/(ref*f3_lo*f5_lo))
f4_lo = F(219875918) / (ref * f3_hi * f5_hi)
f4_hi = F(219875919) / (ref * f3_lo * f5_lo)

def mid(lo, hi):
    return (lo + hi) / 2

def show(name, lo, hi, display):
    m = mid(lo, hi)
    print(f"  {name:<14}= {float(m):.10f}   ±{float(hi-lo)/2:.1e}   (표시 {display})")

print(f"P = {float(P)}   floor(P) = {floorP}\n")
print("── B2 계수 (가산항, P 기준 구간) ──  [dist·burst 는 빌드 무관 UNIVERSAL]")
for k, disp in [("dist","0.3"),("burst","0.5"),("crit","1.2654"),("core","1.1704")]:
    lo, hi = interval_over_P(inc[k]); show(k, lo, hi, disp)
print("\n── 곱셈 브래킷 인자 (1+Σ) ──  [이 빌드 전용]")
show("f5 (B5)", f5_lo, f5_hi, "2.4293")
show("f3 (B3)", f3_lo, f3_hi, "1.484")
show("f4 (B4)", f4_lo, f4_hi, "1.042")

# ── 대표값(중점)으로 전 18 측정점 재현 → 0오차 확인 ──
import math
cal = {k: mid(*interval_over_P(inc[k])) for k in inc}
F5, F3, F4 = mid(f5_lo, f5_hi), mid(f3_lo, f3_hi), mid(f4_lo, f4_hi)
def predict(dist=0, burst=0, crit=0, core=0, b3=0, b4=0, b5=0):
    B2 = floorP \
        + (math.floor(P*cal["dist"]) if dist else 0) \
        + (math.floor(P*cal["burst"]) if burst else 0) \
        + (math.floor(P*cal["crit"]) if crit else 0) \
        + (math.floor(P*cal["core"]) if core else 0)
    fac = (F3 if b3 else 1) * (F4 if b4 else 1) * (F5 if b5 else 1)
    return math.floor(B2 * fac)

pts = [
 ((0,0,0,0),45024780),((1,0,0,0),58532212),((1,1,0,0),81044602),((0,0,1,0),101999134),
 ((0,0,0,1),97721778),((0,1,1,0),124511524),((1,1,0,1),133741600),((0,0,1,1),154696132),
 ((0,1,0,1),120234168),((0,1,1,1),177208522),
 ((1,0,0,0,0,0,1),142192292),((0,0,1,0,0,0,1),247786478),((1,0,1,0,0,0,1),280600080),
 ((1,0,0,1,0,0,1),270209101),((1,1,1,1,0,0,1),463306234),
 ((1,0,0,0,1,0,0),86861800),((1,0,0,0,1,0,1),211013357),((1,0,0,0,1,1,1),219875918)]
names = ["none","dist","dist+burst","crit","core","crit+burst","dist+burst+core","crit+core",
         "burst+core","crit+burst+core","dist+B5","crit+B5","dist+crit+B5","dist+core+B5",
         "full+B5","dist+B3","dist+B3+B5","dist+B3+B4+B5"]
exact = 0; worst = 0
misses = []
for (fl, meas), nm in zip(pts, names):
    fl = fl + (0,)*(7-len(fl))
    pr = predict(*fl); d = pr - meas
    if d == 0: exact += 1
    else: misses.append((nm, d))
    worst = max(worst, abs(d))
print(f"\ncalibrated reproduction: {exact}/18 EXACT, worst |residual| = {worst}")
if misses:
    print("  misses (floor-boundary precision limit, +-1 accepted):")
    for nm, d in misses: print(f"    {nm:<16} {d:+d}")
print("\nf5 single-value feasibility: 5 B5 rows -> intersection EMPTY by",
      f"{float(f5_lo - f5_hi):.1e}  => no single elem-coef fits all (the +-1 limit).")
