using System;
using System.Runtime.CompilerServices;
using Nikke.Simulator.Core.Stats;

namespace Nikke.Simulator.Core.Combat
{
    /// <summary>
    /// 명중원(accuracy circle) → **코어힛/명중 확률** 모델.
    ///
    /// 발상(사용자 2026-07-01): 명중률을 기댓값 근사가 아니라 **실제 면적 확률**로 친다.
    ///   - 무기 spread = 반지름 R 의 원. 탄착은 그 원 안에 **면적 균등** 분포로 떨어진다.
    ///   - 타겟 중심에 동심원: core(반지름 rc) ⊂ body(반지름 rb).
    ///   - P(코어힛)  = area(core)/area(circle) = (rc/R)²   (rc ≥ R 이면 1)
    ///   - P(명중)    = (rb/R)²                              (rb ≥ R 이면 1)  ← 나머지는 빗맞음
    ///   예) R=5, rc=4 → 16/25 (사용자 예시).
    ///
    /// 데이터 출처:
    ///   - R(무기 spread): roledata accuracy_circle_scale — 연사할수록 수축(MG 250→10). <see cref="CircleRadius"/>.
    ///   - rc/rb(타겟): roledata 에 없음 → ITarget(Dummy/Boss)의 **설정 가능 상수**(사용자 결정 2026-07-01).
    ///
    /// 소비: rotation 루프가 매 발사 <see cref="RollCoreHit"/>/<see cref="RollHit"/> 로
    ///       <see cref="AttackContext.IsCoreHit"/> 및 명중/빗맞음을 샘플링. (CritSampler 와 동일 패턴.)
    /// </summary>
    public static class AccuracyModel
    {
        /// <summary>
        /// 연사 중 N번째 발사 시점의 명중원 반지름. start→end 로 발당 changePerShot 만큼 **수축**
        /// (clamp [end, start]). changePerShot=0(대부분 무기)이면 start 상수.
        ///   MG: start 250 → end 10, changePerShot 7 → 약 34발 후 핀포인트.
        /// ⚠️ changeSpeed(시간축 수축률)는 미반영 — 발수 기준 선형 근사. in-game 검증 대기.
        /// </summary>
        /// <param name="startCircle">초기 spread 반지름 (WeaponProfile.StartAccuracyCircle).</param>
        /// <param name="endCircle">수축 한계 반지름 (WeaponProfile.EndAccuracyCircle).</param>
        /// <param name="changePerShot">발당 반지름 감소량 (WeaponProfile.AccuracyChangePerShot).</param>
        /// <param name="shotsFiredInStreak">현재 연사 streak 누적 발사 수 (0-기준).</param>
        public static double CircleRadius(double startCircle, double endCircle, double changePerShot, int shotsFiredInStreak)
        {
            if (shotsFiredInStreak < 0) shotsFiredInStreak = 0;
            // 데이터상 start ≥ end (수축). 방어적으로 둘 다 처리.
            double lo = Math.Min(startCircle, endCircle);
            double hi = Math.Max(startCircle, endCircle);
            if (changePerShot <= 0.0) return startCircle;
            double r = startCircle - changePerShot * shotsFiredInStreak;
            if (r < lo) return lo;
            if (r > hi) return hi;
            return r;
        }

        /// <summary>편의 오버로드 — <see cref="WeaponProfile"/> 의 manual aim 명중원 사용.</summary>
        public static double CircleRadius(WeaponProfile weapon, int shotsFiredInStreak)
        {
            if (weapon == null) throw new ArgumentNullException(nameof(weapon));
            return CircleRadius(weapon.StartAccuracyCircle, weapon.EndAccuracyCircle,
                                weapon.AccuracyChangePerShot, shotsFiredInStreak);
        }

        /// <summary>
        /// 코어힛 확률 = (coreRadius / circleRadius)² , clamp [0,1].
        /// circleRadius ≤ 0 (핀포인트 한계) 또는 coreRadius ≥ circleRadius → 1.0 (항상 코어).
        /// </summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static double CoreHitProbability(double circleRadius, double coreRadius)
            => AreaRatio(circleRadius, coreRadius);

        /// <summary>
        /// 명중(빗맞음 아님) 확률 = (bodyRadius / circleRadius)² , clamp [0,1].
        /// circleRadius ≤ bodyRadius → 1.0 (항상 명중).
        /// </summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static double HitProbability(double circleRadius, double bodyRadius)
            => AreaRatio(circleRadius, bodyRadius);

        /// <summary>코어힛 샘플링 — <see cref="CoreHitProbability"/> 확률로 true (CritSampler 패턴).</summary>
        public static bool RollCoreHit(IRandomSource rng, double circleRadius, double coreRadius)
            => Roll(rng, CoreHitProbability(circleRadius, coreRadius));

        /// <summary>명중 샘플링 — <see cref="HitProbability"/> 확률로 true (false = 빗맞음).</summary>
        public static bool RollHit(IRandomSource rng, double circleRadius, double bodyRadius)
            => Roll(rng, HitProbability(circleRadius, bodyRadius));

        /// <summary>(targetRadius / circleRadius)² 면적비, clamp [0,1].</summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static double AreaRatio(double circleRadius, double targetRadius)
        {
            if (targetRadius <= 0.0) return 0.0;
            if (circleRadius <= 0.0 || targetRadius >= circleRadius) return 1.0;
            double ratio = targetRadius / circleRadius;
            return ratio * ratio;
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static bool Roll(IRandomSource rng, double p)
        {
            if (rng == null) throw new ArgumentNullException(nameof(rng));
            if (p <= 0.0) return false;
            if (p >= 1.0) return true;
            return rng.NextDouble() < p;
        }
    }
}
