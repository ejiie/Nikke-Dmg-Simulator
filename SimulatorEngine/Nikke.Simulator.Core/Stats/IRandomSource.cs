using System;
using System.Runtime.CompilerServices;

namespace Nikke.Simulator.Core.Stats
{
    /// <summary>
    /// 시뮬레이션 루프의 RNG 추상화. 크리/확률 효과 샘플링용.
    ///
    /// ⚠️ **고정 시드 절대 금지** (DEVLOG 2026-04-23 결정 로그):
    ///   - 재현성을 위한 "시드 박제" 유혹을 차단하려고 별도 인터페이스로 떼어냄.
    ///   - 회귀 테스트가 필요하면 **샘플링 수를 늘려 기댓값 수렴**으로 검증 (ex. N=10000 크리 시뮬 후 ±1% 이내).
    ///   - 결코 deterministic seed 기반 stub 을 production path 에 주입하지 않는다.
    ///
    /// 구현체:
    ///   - <see cref="SystemRandomSource"/> (production 기본, `Random.Shared.NextDouble()` wrap).
    /// </summary>
    public interface IRandomSource
    {
        /// <summary>[0.0, 1.0) 범위 균등분포 double.</summary>
        double NextDouble();
    }

    /// <summary>
    /// `System.Random.Shared` 기반 기본 구현 (.NET 6+). 스레드 안전.
    /// 시드 없이 시스템 엔트로피 사용 — 매 실행마다 다른 시퀀스.
    /// </summary>
    public sealed class SystemRandomSource : IRandomSource
    {
        /// <summary>프로세스 전역 싱글턴. `Random.Shared` 자체가 thread-safe 이므로 재사용 안전.</summary>
        public static readonly SystemRandomSource Instance = new();

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public double NextDouble() => Random.Shared.NextDouble();
    }

    /// <summary>
    /// 확률 샘플링 헬퍼 — 시뮬 루프가 `AttackContext.IsCrit` 를 세팅하기 전 호출.
    ///
    /// 사용 패턴:
    /// <code>
    /// ctx.IsCrit = CritSampler.RollCrit(rng, ctx.BaseCritRate);
    /// double dmg = StatCalculator.CalculateDamage(in ctx);
    /// </code>
    /// </summary>
    public static class CritSampler
    {
        /// <summary>
        /// `baseCritRate` 확률로 true 반환. clamp [0, 1] 로 방어 — 버프 합산으로 1 초과 시 보정.
        /// 음수는 이론상 불가하지만 (OL 감소 옵션 없음) defensive.
        /// </summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static bool RollCrit(IRandomSource rng, double baseCritRate)
        {
            if (rng == null) throw new ArgumentNullException(nameof(rng));
            if (baseCritRate <= 0.0) return false;
            if (baseCritRate >= 1.0) return true;
            return rng.NextDouble() < baseCritRate;
        }
    }
}
