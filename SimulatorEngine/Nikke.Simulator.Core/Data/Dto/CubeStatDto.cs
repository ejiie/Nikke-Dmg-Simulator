namespace Nikke.Simulator.Core.Data.Dto
{
    public class CubeStatDto
    {
        public int Level { get; set; }
        public double Atk { get; set; }
        public double Def { get; set; }
        public double HP { get; set; }
        // 우월코드 대미지(ElementAdvantage)·스킬은 cube_effect_table 로 이전됨 — 여기는 base 만.
    }
}