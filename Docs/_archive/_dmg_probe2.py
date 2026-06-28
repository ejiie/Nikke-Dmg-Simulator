import math
def rh(x): return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)

def finalatk(base):
    g1 = rh(base * 0.1393 * 1)
    g2 = rh(base * 0.1463 * 3)
    return base + g1 + g2, g1, g2

for base in (569840, 570529):
    fa, g1, g2 = finalatk(base)
    print(f"BASE={base}: FinalAtk={fa}  (groups {g1}, {g2})")

W = 4.995; C = 10
FA = finalatk(570529)[0]
D = FA - 100
P = D * W * C
strong = 0.1 + 0.1909 + 0.2916*3 + 0.2636   # 1.4293
B5 = 1 + strong
M1 = 109_246_670   # 우월only
M2 = 142_020_666   # 우월+거리(x1.3)

print(f"\nleveled rig: FinalAtk={FA}  D={D}  P={P}  B5={B5}")
print(f"  M1 우월only:")
print(f"    charge-in  round(P*B5)       = {rh(P*B5):>12}  meas {M1}  bias {rh(P*B5)-M1:+}")
print(f"    charge-out round(D*W*B5)*C   = {rh(D*W*B5)*C:>12}  meas {M1}  bias {rh(D*W*B5)*C-M1:+}")
print(f"  M2 우월+거리(x1.3):")
print(f"    charge-in  round(P*1.3*B5)     = {rh(P*1.3*B5):>12}  meas {M2}  bias {rh(P*1.3*B5)-M2:+}")
print(f"    charge-out round(D*W*1.3*B5)*C = {rh(D*W*1.3*B5)*C:>12}  meas {M2}  bias {rh(D*W*1.3*B5)*C-M2:+}")
print(f"  implied strong (in)  = {M1/P - 1:.6f}  vs listed {strong:.4f}")
