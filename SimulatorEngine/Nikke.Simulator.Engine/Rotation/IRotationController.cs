using System;
using System.Collections.Generic;

namespace Nikke.Simulator.Engine.Rotation
{
    /// <summary>
    /// 로테이션 제어 (DESIGN §1 2모드 / ENGINE_GUIDE §5). 매 결정시점에 sim 상태를 보고
    /// 다음 액션(스킬 사용 / 버스트)을 정한다.
    ///
    /// 임플: K10 <c>AutoController</c>(게이지 full→burst, 쿨다운 만료→스킬) /
    /// <c>ScriptedController</c>(시각별 액션 테이블). 둘 다 같은 <see cref="Clock.ISimClock"/> 소비.
    /// 이 인터페이스 + 아래 placeholder 타입은 K0 동결 계약(필드는 K10 에서 확정).
    /// </summary>
    public interface IRotationController
    {
        /// <summary>현재 sim 상태에서 즉시 실행할 액션 목록(없으면 빈 목록).</summary>
        IReadOnlyList<RotationAction> Decide(in SimState state);
    }

    /// <summary>
    /// 로테이션 결정에 필요한 sim 상태 스냅샷 (placeholder — K10 에서 게이지/쿨다운/탄창 등 확정).
    /// </summary>
    public readonly struct SimState
    {
        /// <summary>현재 시각(초).</summary>
        public double NowSec { get; init; }
    }

    /// <summary>로테이션 액션 종류 (placeholder — K10 에서 확정).</summary>
    public enum RotationActionKind
    {
        UseSkill1,
        UseSkill2,
        UseBurst,
    }

    /// <summary>컨트롤러가 내리는 단일 액션 (placeholder — K10 에서 파라미터 확정).</summary>
    public readonly struct RotationAction
    {
        public RotationActionKind Kind { get; init; }

        /// <summary>액션 주체 Combatant 식별자.</summary>
        public string ActorId { get; init; }
    }
}
