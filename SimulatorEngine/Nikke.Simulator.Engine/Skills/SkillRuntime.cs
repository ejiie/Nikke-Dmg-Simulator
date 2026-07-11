using System;
using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine.Buffs;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Events;

namespace Nikke.Simulator.Engine.Skills
{
    /// <summary>
    /// T01 (구 K7, THE GAP 마지막) — 트리거→효과 적용 루프. einkk `function.dart` 4단계 재구현:
    /// ① TimingTrigger 매치 → ② StatusTrigger ×2 평가 → ③ 효과 적용(버프 스폰/즉시 효과) →
    /// ④ connected_function 연쇄 (+UseCharacterSkillId 로 다른 CharacterSkill 호출).
    ///
    /// 계약:
    ///  - run 1회당 인스턴스 1개 (상태 보유 — 재사용 금지).
    ///  - 미지 enum/트리거/미검증 route = **no-op + 카운터** (throw 금지 — INV-1). <see cref="NoOpCounters"/>.
    ///  - 시간 duration = 1/100초 → 프레임 변환 (FACTS §4). 만료 = <see cref="TickFrame"/> (frame 도메인).
    ///  - 즉시 효과(DealDamage/탄약)는 큐에 쌓고 러너가 drain — 엔진 순수성(대미지 계산은 러너 소관).
    ///  - T01 스코프: 자기/팀 버프 + 스킬 대미지. 버스트 사이클 이벤트 발행 = T02, 생존 = 확장.
    /// </summary>
    public sealed class SkillRuntime
    {
        private const double Fps = WeaponProfile.EngineFrameRate;
        private const int MaxChainDepth = 8;      // connected/UseCharacterSkillId 연쇄 폭주 가드
        private const int MaxCascadePerCall = 256; // FunctionOn/Off 이벤트 연쇄 폭주 가드

        /// <summary>등록된 트리거 함수 1개 (owner 별 카운터 보유).</summary>
        private sealed class Listener
        {
            public Combatant Owner;
            public FunctionDto F;
            public int Counter;          // OnHitNum/OnUseAmmo 등 N-카운트
            public int NextCheckFrame;   // OnCheckTime 주기
        }

        /// <summary>CharacterSkill 슬롯 (버스트/액티브) — CastSkill 로 발동.</summary>
        private sealed class CastableSkill
        {
            public string Slot;
            public int SkillId;
            public List<FunctionDto> Functions;
            public CharacterSkillBodyDto Body;
            public bool ListenersRegistered; // 트리거형 함수는 첫 시전 시 1회만 listener 등록
        }

        /// <summary>즉시 대미지 인스턴스 (DealDamage) — 러너가 drain 해 DamageCalculator 로 계산.</summary>
        public readonly struct PendingDamage
        {
            public Combatant Source { get; init; }
            /// <summary>M 의 스킬 계수 (W 슬롯 = SkillMultiplier 로 주입 — FACTS §1).</summary>
            public double Multiplier { get; init; }
            public int FunctionId { get; init; }
        }

        public enum AmmoOpKind { FullReload, AddCount, AddRatio }

        /// <summary>즉시 탄약 효과 (AmmoRefill 계열) — 러너가 FiringModel 에 반영.</summary>
        public readonly struct PendingAmmo
        {
            public Combatant Owner { get; init; }
            public AmmoOpKind Kind { get; init; }
            public double Amount { get; init; } // AddCount = 발 수, AddRatio = 최대 탄창 분수
        }

        private readonly SkillChainsDto _chains;
        private readonly List<Listener> _listeners = new();
        private readonly List<Combatant> _team = new();
        private readonly Dictionary<Combatant, List<CastableSkill>> _castables = new();
        private readonly Dictionary<string, int> _noop = new();
        private readonly List<PendingDamage> _pendingDamage = new();
        private readonly List<PendingAmmo> _pendingAmmo = new();
        private readonly Queue<BattleEvent> _cascade = new();
        private bool _processing;

        /// <summary>no-op 계수 (진단/T07 승격 후보 목록) — key 예: "route:Unverified", "trigger:OnHpRatioUnder".</summary>
        public IReadOnlyDictionary<string, int> NoOpCounters => _noop;

        public SkillRuntime(SkillChainsDto chains)
            => _chains = chains ?? throw new ArgumentNullException(nameof(chains));

        private static int CsToFrames(int cs) => Math.Max(0, (int)Math.Round(cs * Fps / 100.0));

        private void Count(string key) => _noop[key] = _noop.GetValueOrDefault(key) + 1;

        private FunctionDto Fn(int fid)
            => fid != 0 && _chains.Functions.TryGetValue(fid.ToString(), out var f) ? f : null;

        // ─────────────────────────── 등록 ───────────────────────────

        /// <summary>
        /// 캐릭 1명 등록: 패시브(StateEffect) 함수 = 트리거 listener / CharacterSkill(버스트 등) = 시전 목록.
        /// 스킬 레벨 = 1..10 (레벨 부재 시 최고 보유 레벨로 폴백 — graceful).
        /// </summary>
        public void Register(Combatant owner, CharacterChainDto chain,
                             int skill1Lv = 10, int skill2Lv = 10, int burstLv = 10)
        {
            if (owner == null) throw new ArgumentNullException(nameof(owner));
            if (chain == null) throw new ArgumentNullException(nameof(chain));
            if (!_team.Contains(owner)) _team.Add(owner);
            var casts = _castables.TryGetValue(owner, out var c) ? c : (_castables[owner] = new());

            foreach (var (slot, lv) in new[] { ("skill1", skill1Lv), ("skill2", skill2Lv), ("burst", burstLv) })
            {
                if (!chain.Skills.TryGetValue(slot, out var slotDto) || slotDto.Levels.Count == 0) continue;
                var lvDto = ResolveLevel(slotDto, lv);
                if (lvDto == null) continue;

                var fns = lvDto.FunctionIds.Select(Fn).Where(f => f != null).ToList();
                if (slotDto.Table == "CharacterSkill")
                {
                    casts.Add(new CastableSkill
                    {
                        Slot = slot, SkillId = lvDto.SkillId, Functions = fns, Body = lvDto.Skill,
                    });
                }
                else // StateEffect 패시브 — 전투 시작부터 상주 listener
                {
                    foreach (var f in fns)
                        _listeners.Add(new Listener { Owner = owner, F = f });
                }
            }
        }

        private static SkillLevelDto ResolveLevel(SkillSlotDto slot, int lv)
        {
            if (slot.Levels.TryGetValue(lv.ToString(), out var d)) return d;
            // 폴백: 보유 최고 레벨 (데이터 결손 graceful)
            return slot.Levels.OrderByDescending(kv => int.Parse(kv.Key)).Select(kv => kv.Value).FirstOrDefault();
        }

        // ─────────────────────────── 이벤트 소비 ───────────────────────────

        /// <summary>이벤트 브로드캐스트 — 등록 listener 트리거 평가. 내부 연쇄(FunctionOn 등) 포함 처리.</summary>
        public void Broadcast(in BattleEvent e)
        {
            _cascade.Enqueue(e);
            FlushCascade();
        }

        private BuffsSnapshot _listenerCache;
        private sealed class BuffsSnapshot { public Listener[] Items; }

        private Listener[] ListenerSnapshot()
        {
            // Apply(시전 시 listener 추가)가 순회를 깨지 않도록 스냅샷 — 변경 시에만 재생성 (per-event 할당 방지)
            if (_listenerCache == null || _listenerCache.Items.Length != _listeners.Count)
                _listenerCache = new BuffsSnapshot { Items = _listeners.ToArray() };
            return _listenerCache.Items;
        }

        private void FlushCascade()
        {
            if (_processing) return; // 연쇄 중 재진입 = 큐에만 적재
            _processing = true;
            int safety = 0;
            try
            {
                while (_cascade.Count > 0 && safety++ < MaxCascadePerCall)
                {
                    var ev = _cascade.Dequeue();
                    // Shots/Hits 지속 감소 = listener 평가 **이전** — 이번 이벤트로 스폰된 버프는 미감소 (off-by-one 방지)
                    if (ev.Kind == BattleEventKind.NikkeFire) DecrementShotDurations(ev.Source, ev.Frame);
                    foreach (var l in ListenerSnapshot())
                    {
                        if (!TimingMatch(l, ev)) continue;
                        if (!StatusPass(l.Owner, l.F.StatusTriggerType, l.F.StatusTriggerValue, ev)) continue;
                        if (!StatusPass(l.Owner, l.F.StatusTrigger2Type, l.F.StatusTrigger2Value, ev)) continue;
                        Apply(l.F, l.Owner, ev.Frame, depth: 0);
                    }
                }
                if (safety >= MaxCascadePerCall) Count("cascade:overflow");
            }
            finally { _processing = false; }
        }

        /// <summary>
        /// 프레임 tick: 시간 만료 버프 제거(FunctionOff 발행) + OnCheckTime 주기 트리거.
        /// SimulationRunner 가 매 프레임 호출 (frame 도메인 — FACTS §4).
        /// </summary>
        public void TickFrame(int frame)
        {
            foreach (var c in _team)
            {
                for (int i = c.ActiveBuffs.Count - 1; i >= 0; i--)
                {
                    var b = c.ActiveBuffs[i];
                    if (b.ExpiryFrame.HasValue && frame >= b.ExpiryFrame.Value)
                    {
                        c.ActiveBuffs.RemoveAt(i);
                        Broadcast(new BattleEvent
                        {
                            Kind = BattleEventKind.FunctionOff, Source = c,
                            IntValue = b.GroupId, Frame = frame,
                        });
                    }
                }
            }

            foreach (var l in _listeners.ToArray())
            {
                if (l.F.TypedTimingTrigger != TimingTriggerType.OnCheckTime) continue;
                int period = Math.Max(1, CsToFrames(l.F.TimingTriggerValue)); // value = 1/100초 주기
                if (l.NextCheckFrame == 0) l.NextCheckFrame = period;         // 첫 발동 = 1주기 후
                if (frame < l.NextCheckFrame) continue;
                l.NextCheckFrame = frame + period;
                var ev = new BattleEvent { Kind = BattleEventKind.BattleStart, Source = l.Owner, Frame = frame };
                if (StatusPass(l.Owner, l.F.StatusTriggerType, l.F.StatusTriggerValue, ev)
                    && StatusPass(l.Owner, l.F.StatusTrigger2Type, l.F.StatusTrigger2Value, ev))
                    Apply(l.F, l.Owner, frame, depth: 0);
            }
            FlushCascade(); // OnCheckTime/만료 경로에서 적재된 연쇄 이벤트 소진
        }

        // ─────────────────────────── 시전 ───────────────────────────

        /// <summary>
        /// CharacterSkill 시전 (버스트/액티브). 반환 = 쿨타임 프레임 (러너가 다음 시전 스케줄; 0 = 슬롯 없음).
        /// 게이지/사이클 판정은 T02 — T01 은 시전 그 자체만.
        /// </summary>
        public int CastSkill(Combatant owner, string slot, int frame)
        {
            if (!_castables.TryGetValue(owner, out var casts)) return 0;
            var sk = casts.FirstOrDefault(x => x.Slot == slot);
            if (sk == null) return 0;

            CastFunctions(sk, owner, frame);
            // CharacterSkill 본체 소비는 T01 = function 체인만. skill_type 7(ChangeWeapon 무기 교체 —
            // FiringModel 재생성 훅)·9(InstantSkill 계수) 등 body 축은 미배선 — 카운터로 가시화 (T02/T07).
            if (sk.Body != null && sk.Body.SkillType != 0)
                Count($"skilltype:{sk.Body.SkillType}");
            Broadcast(new BattleEvent { Kind = BattleEventKind.UseSkill, Source = owner, Frame = frame });
            return sk.Body != null ? CsToFrames(sk.Body.SkillCooltime) : 0;
        }

        private void CastFunctions(CastableSkill sk, Combatant owner, int frame)
        {
            foreach (var f in sk.Functions)
            {
                var t = f.TypedTimingTrigger;
                if (t is TimingTriggerType.None or TimingTriggerType.OnStart)
                {
                    var ev = new BattleEvent { Kind = BattleEventKind.UseSkill, Source = owner, Frame = frame };
                    if (StatusPass(owner, f.StatusTriggerType, f.StatusTriggerValue, ev)
                        && StatusPass(owner, f.StatusTrigger2Type, f.StatusTrigger2Value, ev))
                        Apply(f, owner, frame, depth: 0);
                }
                else if (!sk.ListenersRegistered)
                {
                    _listeners.Add(new Listener { Owner = owner, F = f }); // 트리거형 = 상주 등록 (1회)
                }
            }
            sk.ListenersRegistered = true;
        }

        /// <summary>UseCharacterSkillId(72) — 조립본 character_skills 전개분 시전. 부재 = no-op 카운터.</summary>
        private void CastById(long skillId, Combatant owner, int frame, int depth)
        {
            if (_chains.CharacterSkills == null
                || !_chains.CharacterSkills.TryGetValue(skillId.ToString(), out var sk))
            {
                Count("usecharskill:missing"); // 구 조립본 (character_skills 없음) — 재조립 필요 신호
                return;
            }
            foreach (var fid in sk.FunctionIds)
            {
                var f = Fn(fid);
                if (f == null) continue;
                var t = f.TypedTimingTrigger;
                var ev = new BattleEvent { Kind = BattleEventKind.UseSkill, Source = owner, Frame = frame };
                if (t is TimingTriggerType.None or TimingTriggerType.OnStart)
                {
                    if (StatusPass(owner, f.StatusTriggerType, f.StatusTriggerValue, ev)
                        && StatusPass(owner, f.StatusTrigger2Type, f.StatusTrigger2Value, ev))
                        Apply(f, owner, frame, depth); // depth 유지 — 연쇄 폭주 가드
                }
                else
                {
                    Count($"usecharskill:trigger:{t}"); // 호출형 스킬의 트리거 함수 = MVP 미등록 (희귀)
                }
            }
        }

        // ─────────────────────────── 트리거 매치 ───────────────────────────

        private bool TimingMatch(Listener l, in BattleEvent e)
        {
            var f = l.F;
            bool own = e.Source == null || ReferenceEquals(e.Source, l.Owner);
            int value = f.TimingTriggerValue;

            switch (f.TypedTimingTrigger)
            {
                case TimingTriggerType.None:
                case TimingTriggerType.OnStart:
                    return e.Kind == BattleEventKind.BattleStart && own;

                case TimingTriggerType.OnUseAmmo:
                    return e.Kind == BattleEventKind.NikkeFire && own && Nth(l, value);
                case TimingTriggerType.OnHitNum:
                    return e.Kind == BattleEventKind.NikkeHit && own && Nth(l, value);
                case TimingTriggerType.OnFullChargeShot:
                case TimingTriggerType.OnFullCharge:
                    return e.Kind == BattleEventKind.NikkeFire && own && e.IsFullCharge && Nth(l, value);
                case TimingTriggerType.OnFullChargeShotNum:
                    return e.Kind == BattleEventKind.NikkeFire && own && e.IsFullCharge && Nth(l, value);
                case TimingTriggerType.OnFullChargeHit:
                    return e.Kind == BattleEventKind.NikkeHit && own && e.IsFullCharge && Nth(l, value);
                case TimingTriggerType.OnFullChargeHitNum:
                    return e.Kind == BattleEventKind.NikkeHit && own && e.IsFullCharge && Nth(l, value);
                case TimingTriggerType.OnLastShotHit:
                    return e.Kind == BattleEventKind.NikkeHit && own && e.IntValue == 0;
                case TimingTriggerType.OnLastAmmoUse:
                    return e.Kind == BattleEventKind.NikkeFire && own && e.IntValue == 0;
                case TimingTriggerType.OnEndReload:
                    return e.Kind == BattleEventKind.ReloadEnd && own;
                case TimingTriggerType.OnSkillUse:
                    return e.Kind == BattleEventKind.UseSkill && own && Nth(l, value);
                case TimingTriggerType.OnCriticalHitNum:
                    return e.Kind == BattleEventKind.NikkeHit && own && e.IsCrit && Nth(l, value);
                case TimingTriggerType.OnCoreHitNum:
                    return e.Kind == BattleEventKind.NikkeHit && own && e.IsCoreHit && Nth(l, value);

                // 버스트 사이클 (발행 = T02 — 계약만 선반영)
                case TimingTriggerType.OnEnterBurstStep:
                    return e.Kind == BattleEventKind.EnterBurstStep && own
                        && (value == 0 || value == e.IntValue);
                case TimingTriggerType.OnEndFullBurst:
                    return e.Kind == BattleEventKind.EndFullBurst && own;

                // 버프 연쇄
                case TimingTriggerType.OnFunctionOn:
                    return e.Kind == BattleEventKind.FunctionOn && (value == 0 || value == e.IntValue);
                case TimingTriggerType.OnFunctionOff:
                    return e.Kind == BattleEventKind.FunctionOff && (value == 0 || value == e.IntValue);
                case TimingTriggerType.OnFullCount:
                    return e.Kind == BattleEventKind.FunctionFull && (value == 0 || value == e.IntValue);

                case TimingTriggerType.OnCheckTime:
                    return false; // TickFrame 주기 경로 전담

                default:
                    if (e.Kind == BattleEventKind.BattleStart) // 미지원 트리거 = 1회만 계수 (스팸 방지)
                        Count($"trigger:{f.TypedTimingTrigger}");
                    return false;
            }
        }

        /// <summary>N-카운트 트리거 (value = N; 0/1 = 매회).</summary>
        private static bool Nth(Listener l, int value)
        {
            int n = Math.Max(1, value);
            l.Counter += 1;
            if (l.Counter < n) return false;
            l.Counter = 0;
            return true;
        }

        private bool StatusPass(Combatant owner, int rawType, long value, in BattleEvent e)
        {
            switch ((StatusTriggerType)rawType)
            {
                case StatusTriggerType.None:
                case StatusTriggerType.IsAlive: // 생존 시뮬 밖 — 항상 생존
                    return true;
                case StatusTriggerType.IsFunctionOn:
                    return HasBuff(owner, value);
                case StatusTriggerType.IsFunctionOff:
                    return !HasBuff(owner, value);
                case StatusTriggerType.IsFullCount:
                    return owner.ActiveBuffs.Any(b => (b.GroupId == value || b.FunctionId == value) && b.AtFullCount);
                case StatusTriggerType.IsFullCharge:
                    return e.IsFullCharge;
                default:
                    Count($"status:{(StatusTriggerType)rawType}"); // 미지원 조건 = 발동 억제 (보수적 no-op)
                    return false;
            }
        }

        private static bool HasBuff(Combatant c, long groupOrFnId)
            => c.ActiveBuffs.Any(b => b.GroupId == groupOrFnId || b.FunctionId == groupOrFnId);

        // ─────────────────────────── 효과 적용 ───────────────────────────

        private void Apply(FunctionDto f, Combatant owner, int frame, int depth)
        {
            if (depth > MaxChainDepth) { Count("chain:depth-overflow"); return; }

            // UseCharacterSkillId = route 이전 특례 (다른 CharacterSkill 호출 — T01 필수)
            if (f.TypedFunctionType == FunctionType.UseCharacterSkillId)
            {
                CastById(f.FunctionValue, owner, frame, depth + 1);
            }
            else
            {
                switch (SkillTranslator.Route(f))
                {
                    // 스탯/컨텍스트 버프 — BuffInstance 스폰
                    case EffectRoute.AtkRate:
                    case EffectRoute.DefRate:
                    case EffectRoute.HpRate:
                    case EffectRoute.MaxAmmoRate:
                    case EffectRoute.CritRateAdd:
                    case EffectRoute.CritDmgAdd:
                    case EffectRoute.ChargeDmgAdd:
                    case EffectRoute.StrongElemAdd:
                    case EffectRoute.CoreHitBuffAdd:
                    case EffectRoute.PartsDmgAdd:
                    case EffectRoute.PierceDmgAdd:
                        SpawnBuff(f, owner, frame);
                        break;

                    case EffectRoute.DealDamage:
                        _pendingDamage.Add(new PendingDamage
                        {
                            Source = owner, Multiplier = f.ValueAsFraction, FunctionId = f.Id,
                        });
                        break;

                    case EffectRoute.AmmoRefill:
                        _pendingAmmo.Add(MakeAmmoOp(f, owner));
                        break;

                    // 미배선/미검증/스코프 밖 = no-op + 카운터 (T07/T02 승격 대기)
                    default:
                        Count($"route:{SkillTranslator.Route(f)}:{f.TypedFunctionType}");
                        break;
                }
            }

            foreach (int cid in f.ConnectedFunction ?? (IReadOnlyList<int>)Array.Empty<int>())
            {
                var cf = Fn(cid);
                if (cf != null) Apply(cf, owner, frame, depth + 1);
            }
        }

        private static PendingAmmo MakeAmmoOp(FunctionDto f, Combatant owner)
        {
            // ForcedReload/AllAmmo = 즉시 풀장전. GainAmmo = Integer → +N발 / Percent → +비율.
            if (f.TypedFunctionType is FunctionType.ForcedReload or FunctionType.AllAmmo)
                return new PendingAmmo { Owner = owner, Kind = AmmoOpKind.FullReload };
            return f.TypedValueType == ValueType.Percent
                ? new PendingAmmo { Owner = owner, Kind = AmmoOpKind.AddRatio, Amount = f.ValueAsFraction }
                : new PendingAmmo { Owner = owner, Kind = AmmoOpKind.AddCount, Amount = f.FunctionValue };
        }

        private void SpawnBuff(FunctionDto f, Combatant owner, int frame)
        {
            foreach (var target in ResolveTargets(f, owner))
            {
                var existing = target.ActiveBuffs.FirstOrDefault(b => b.GroupId == f.GroupId);
                if (existing != null)
                {
                    bool wasFull = existing.AtFullCount;
                    existing.Stacks = Math.Min(existing.Stacks + 1, existing.MaxStacks);
                    SetDuration(existing, f, frame); // 재발동 = 지속 갱신
                    if (!wasFull && existing.AtFullCount)
                        _cascade.Enqueue(new BattleEvent
                        {
                            Kind = BattleEventKind.FunctionFull, Source = target,
                            IntValue = f.GroupId, Frame = frame,
                        });
                }
                else
                {
                    var buff = new BuffInstance
                    {
                        FunctionId = f.Id, GroupId = f.GroupId, FunctionTypeRaw = f.FunctionType,
                        Route = SkillTranslator.Route(f), Value = f.ValueAsFraction,
                        LimitValue = f.LimitValue, FullCount = f.FullCount, SourceId = owner.Id,
                    };
                    SetDuration(buff, f, frame);
                    target.ActiveBuffs.Add(buff);
                    _cascade.Enqueue(new BattleEvent
                    {
                        Kind = BattleEventKind.FunctionOn, Source = target,
                        IntValue = f.GroupId, Frame = frame,
                    });
                    if (buff.AtFullCount)
                        _cascade.Enqueue(new BattleEvent
                        {
                            Kind = BattleEventKind.FunctionFull, Source = target,
                            IntValue = f.GroupId, Frame = frame,
                        });
                }
            }
        }

        private IEnumerable<Combatant> ResolveTargets(FunctionDto f, Combatant owner)
        {
            switch (f.TypedTarget)
            {
                case FunctionTargetType.Self:
                case FunctionTargetType.None:
                    yield return owner;
                    break;
                case FunctionTargetType.AllCharacter:
                    foreach (var c in _team) yield return c;
                    break;
                default:
                    // Target/AllMonster(적 디버프)/커버 계열 = T01 스코프 밖 — no-op 카운터
                    Count($"target:{f.TypedTarget}");
                    break;
            }
        }

        private void SetDuration(BuffInstance b, FunctionDto f, int frame)
        {
            switch (f.TypedDurationType)
            {
                case DurationType.TimeSec:
                case DurationType.TimeSec_Ver2:
                case DurationType.TimeSec_Ver3:
                case DurationType.TimeSecBattles:
                    b.ExpiryFrame = frame + Math.Max(1, CsToFrames(f.DurationValue)); // 1/100초 → 프레임
                    b.RemainingShots = null;
                    break;
                case DurationType.Shots:
                case DurationType.SkillShots:
                case DurationType.Hits:
                case DurationType.Hits_Ver2:
                    b.RemainingShots = Math.Max(1, f.DurationValue);
                    b.ExpiryFrame = null;
                    break;
                case DurationType.None:
                case DurationType.Battles:
                    b.ExpiryFrame = null; // 전투 내내 지속
                    b.RemainingShots = null;
                    break;
                default:
                    Count($"duration:{f.TypedDurationType}"); // 미지 = 영구 취급 (graceful)
                    b.ExpiryFrame = null;
                    break;
            }
        }

        /// <summary>Shots/Hits 지속 버프 감소 (발사 시) — 0 도달 = 제거 + FunctionOff.</summary>
        private void DecrementShotDurations(Combatant c, int frame)
        {
            if (c == null) return;
            for (int i = c.ActiveBuffs.Count - 1; i >= 0; i--)
            {
                var b = c.ActiveBuffs[i];
                if (!b.RemainingShots.HasValue) continue;
                b.RemainingShots -= 1;
                if (b.RemainingShots > 0) continue;
                c.ActiveBuffs.RemoveAt(i);
                _cascade.Enqueue(new BattleEvent
                {
                    Kind = BattleEventKind.FunctionOff, Source = c, IntValue = b.GroupId, Frame = frame,
                });
            }
        }

        // ─────────────────────────── 러너 drain ───────────────────────────

        /// <summary>대기 중인 스킬 대미지 인스턴스 회수 (호출 후 큐 비움).</summary>
        public List<PendingDamage> DrainDamage()
        {
            if (_pendingDamage.Count == 0) return null;
            var list = new List<PendingDamage>(_pendingDamage);
            _pendingDamage.Clear();
            return list;
        }

        /// <summary>대기 중인 탄약 효과 회수 (호출 후 큐 비움).</summary>
        public List<PendingAmmo> DrainAmmo()
        {
            if (_pendingAmmo.Count == 0) return null;
            var list = new List<PendingAmmo>(_pendingAmmo);
            _pendingAmmo.Clear();
            return list;
        }
    }
}
