# -*- coding: utf-8 -*-
"""
NIKKE per-hit damage — FRESH derivation from measured data (2026-06-27).
No prior model assumed. Structure discovered: ADDITIVE per-bracket, each term
floored independently, summed.

    Damage = floor(P) + Σ_active floor(P × bracket_i)        P = (FinalAtk - DEF)·W·C

Discovery path: every bracket's increment (measured_with - measured_without) is
CONSTANT across contexts => fully additive, no cross terms, per-term floor.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from collections import Counter

# ───────────────────────── fixed char inputs ─────────────────────────
BASE_ATK = 571218
DEF      = 100
OL_ATK   = [13.93, 14.63, 14.63, 14.63]   # percent
W = Decimal("4.995")   # weapon coef  (499.5%)
C = Decimal("10")      # charge coef  (1000%)

OL_CRIT  = [20.36, 19.38, 19.38, 17.42]   # percent -> sum 0.7654
CRIT = Decimal("0.5") + sum(Decimal(str(p)) for p in OL_CRIT) / 100   # 1.2654 display
CORE = Decimal("1.0") + Decimal("0.1704")                              # 1.1704 display
DIST  = Decimal("0.3")
BURST = Decimal("0.5")

# ───────────────────────── niké式 FinalAtk ─────────────────────────
def rhu(x, dp=0):
    return Decimal(x).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)

def final_atk(base, ol):
    bonus = Decimal(0)
    for pct, cnt in Counter(ol).items():
        bonus += rhu(Decimal(base) * (Decimal(str(pct)) / 100 * cnt), 0)
    return Decimal(base) + bonus

FinalAtk = final_atk(BASE_ATK, OL_ATK)
D = FinalAtk - Decimal(DEF)
P = D * W * C
def flr(x): return int(Decimal(x).to_integral_value(rounding=ROUND_FLOOR))

# ───────────────────────── measured ─────────────────────────
# (label, dist, burst, crit, core, MEASURED)
COMBOS = [
    ("none",            0,0,0,0, 45024780),
    ("dist",            1,0,0,0, 58532212),
    ("dist+burst",      1,1,0,0, 81044602),
    ("crit",            0,0,1,0, 101999134),
    ("core",            0,0,0,1, 97721778),
    ("crit+burst",      0,1,1,0, 124511524),
    ("dist+burst+core", 1,1,0,1, 133741600),
    ("crit+core",       0,0,1,1, 154696132),
    ("burst+core",      0,1,0,1, 120234168),
    ("crit+burst+core", 0,1,1,1, 177208522),
]
M = {lbl: m for lbl, *_ , m in COMBOS}

# ───── back-calc empirical increments (measured-with minus measured-without) ─────
BASEv = M["none"]
inc = {
    "burst": M["dist+burst"] - M["dist"],          # cross-checked x4
    "dist" : M["dist"] - M["none"],
    "crit" : M["crit"] - M["none"],
    "core" : M["core"] - M["none"],
}

# ───── predict two ways ─────
def pred_display(d,b,cr,co):
    """additive per-term floor using DISPLAY coefficients"""
    t = flr(P)
    if d:  t += flr(P*DIST)
    if b:  t += flr(P*BURST)
    if cr: t += flr(P*CRIT)
    if co: t += flr(P*CORE)
    return t

def pred_empirical(d,b,cr,co):
    """additive using back-calculated true increments (calibrated)"""
    t = BASEv
    if d:  t += inc["dist"]
    if b:  t += inc["burst"]
    if cr: t += inc["crit"]
    if co: t += inc["core"]
    return t

if __name__ == "__main__":
    print(f"FinalAtk={FinalAtk}  D={D}  P={P}  floor(P)={flr(P)}")
    print(f"empirical increments  base={BASEv}  dist={inc['dist']}  "
          f"burst={inc['burst']}  crit={inc['crit']}  core={inc['core']}")
    print(f"back-calc true brackets (inc/floorP):")
    fp = Decimal(flr(P))
    for k,v in inc.items():
        print(f"   {k:6}= {Decimal(v)/fp:.10f}   (display "
              f"{ {'dist':DIST,'burst':BURST,'crit':CRIT,'core':CORE}[k] })")
    print("-"*78)
    print(f"{'combo':<18}{'measured':>14}{'pred(disp)':>14}{'dΔ':>5}"
          f"{'pred(calib)':>14}{'cΔ':>5}")
    for lbl,d,b,cr,co,m in COMBOS:
        pd = pred_display(d,b,cr,co); pe = pred_empirical(d,b,cr,co)
        print(f"{lbl:<18}{m:>14,}{pd:>14,}{pd-m:>5}{pe:>14,}{pe-m:>5}")
