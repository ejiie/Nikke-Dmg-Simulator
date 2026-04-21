// --- [파일 1: Data/Constants/EffectModels.cs] ---
namespace Nikke.Simulator.Core.Data.Constants
{
    /// <summary>
    /// 확정된 6종의 하모니 큐브 스킬 효과를 담는 불변 구조체 (메모리 할당 O(0))
    /// </summary>
    public readonly struct CubeEffectDto
    {
        public double ReloadTimeReduction { get; } // 1. 재장전 속도 감소 (%)
        public double AmmoChargeRate { get; }      // 2. 탄환 충전 비율 (%)
        public double PartsDamageBonus { get; }    // 3. 파츠 대미지 증가 (%)
        public double PierceDamageBonus { get; }   // 4. 관통 대미지 증가 (%)
        public double TrueDamageBonus { get; }     // 5. 트루 대미지 증가 (%)
        public double MaxHpBonusRate { get; }      // 6. 체력 증가 (%)

        public CubeEffectDto(
            double reload = 0,
            double ammoCharge = 0,
            double partsDamage = 0,
            double pierceDamage = 0,
            double trueDamage = 0,
            double maxHp = 0)
        {
            ReloadTimeReduction = reload;
            AmmoChargeRate = ammoCharge;
            PartsDamageBonus = partsDamage;
            PierceDamageBonus = pierceDamage;
            TrueDamageBonus = trueDamage;
            MaxHpBonusRate = maxHp;
        }
    }

    /// <summary>
    /// 소장품/애장품의 특수 스킬(무기별 + 공통) 효과를 담는 불변 구조체
    /// </summary>
    public readonly struct CollectionEffectDto
    {
        // --- [무기별 특수 스킬] ---
        public double CoreDamageBonus { get; }       // AR: 코어 대미지 증가
        public double ChargeDamageMultiplier { get; } // SR, RL: 차징 대미지 배율 증가
        public double NormalAttackMultiplier { get; } // SMG, SG: 평타딜 배율 증가
        public double MaxAmmoIncreaseRate { get; }    // MG: 장탄수 증가 (%)

        // --- [공통 특수 스킬] ---
        public double DefIncreaseRate { get; }        // 공통: 방어력 증가 (%)
        public double DamageTakenReduction { get; }   // 공통: 받는 대미지 감소 (%)
        public double CoverHpIncreaseRate { get; }    // 공통: 엄폐물 HP 증가 (%)

        public CollectionEffectDto(
            double coreDmg = 0,
            double chargeDmg = 0,
            double normalAtk = 0,
            double maxAmmo = 0,
            double defInc = 0,
            double dmgTakenRed = 0,
            double coverHp = 0)
        {
            CoreDamageBonus = coreDmg;
            ChargeDamageMultiplier = chargeDmg;
            NormalAttackMultiplier = normalAtk;
            MaxAmmoIncreaseRate = maxAmmo;
            DefIncreaseRate = defInc;
            DamageTakenReduction = dmgTakenRed;
            CoverHpIncreaseRate = coverHp;
        }
    }
}