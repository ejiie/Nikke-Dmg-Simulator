namespace Nikke.Simulator.Core.Data.Dto
{
    /// <summary>
    /// JSON 파일에서 읽어올 오버로드 장비 개별 옵션 데이터
    /// </summary>
    public class OverloadOptionDto
    {
        public string type { get; set; }     // 예: "StatAtk", "StatAmmoLoad", "StatCriticalDamage"
        public double value { get; set; }    // 예: 0.1181, 1644
        public string val_type { get; set; } // 예: "Percent", "Integer"
    }
}