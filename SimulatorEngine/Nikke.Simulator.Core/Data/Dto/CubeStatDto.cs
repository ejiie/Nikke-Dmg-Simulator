namespace Nikke.Simulator.Core.Data.Dto
{
    public class CubeStatDto
    {
        public int Level { get; set; }
        public double Atk { get; set; }
        public double Def { get; set; }
        public double HP { get; set; }
        public double SuperiorCodeDmg { get; set; } // 우월코드 대미지
        public int SkillLevel { get; set; }        // 스킬 1슬롯 레벨
    }
}