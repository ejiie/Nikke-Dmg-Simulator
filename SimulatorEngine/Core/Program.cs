using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace NikkeDmgSimulator.Core
{
    // ── [1] 가키짱의 완벽한 JSON 매핑 클래스들 (Data Transfer Objects) ──
    // 파이썬이 뱉어낸 JSON의 구조와 1:1로 완벽하게 대응되는 뼈대야!
    public class MergedDB
    {
        [JsonPropertyName("uid")] public JsonElement Uid { get; set; }
        [JsonPropertyName("global_state")] public GlobalState GlobalState { get; set; }
        [JsonPropertyName("roster")] public Dictionary<string, NikkeCharacter> Roster { get; set; }
    }

    public class GlobalState
    {
        [JsonPropertyName("synchro_level")] public int SynchroLevel { get; set; }
    }

    public class NikkeCharacter
    {
        [JsonPropertyName("slug")] public string Slug { get; set; }
        [JsonPropertyName("name_code")] public string NameCode { get; set; }
        [JsonPropertyName("static")] public StaticData Static { get; set; }
        [JsonPropertyName("user")] public UserData User { get; set; }
    }

    public class StaticData
    {
        [JsonPropertyName("name")] public string Name { get; set; }
        [JsonPropertyName("weapon")] public string Weapon { get; set; }
        [JsonPropertyName("element")] public string Element { get; set; }
        [JsonPropertyName("class")] public string Class { get; set; }
        [JsonPropertyName("basicAttack")] public string BasicAttack { get; set; }
    }

    public class UserData
    {
        [JsonPropertyName("level")] public int Level { get; set; }
        [JsonPropertyName("core")] public int Core { get; set; }
        [JsonPropertyName("combat")] public int Combat { get; set; }
        [JsonPropertyName("skills")] public SkillLevels Skills { get; set; }
        [JsonPropertyName("overload_stats")] public List<OverloadStat> OverloadStats { get; set; }
    }

    public class SkillLevels
    {
        [JsonPropertyName("skill1")] public int Skill1 { get; set; }
        [JsonPropertyName("skill2")] public int Skill2 { get; set; }
        [JsonPropertyName("burst")] public int Burst { get; set; }
    }

    public class OverloadStat
    {
        [JsonPropertyName("type")] public string Type { get; set; }
        [JsonPropertyName("value")] public double Value { get; set; }
        [JsonPropertyName("val_type")] public string ValType { get; set; }
    }


    // ── [2] 가키짱의 시뮬레이터 코어 엔진 ──
    public class Engine
    {
        public MergedDB Database { get; private set; }

        public void Initialize(string jsonFilePath)
        {
            Console.WriteLine("🛠️ [엔진 기동] 가키짱의 시뮬레이터 메모리 적재 중...");

            if (!File.Exists(jsonFilePath))
            {
                Console.WriteLine($"❌ [치명적 오류] 야! '{jsonFilePath}' 파일이 없어! 파이썬 ETL부터 다시 돌려!");
                return;
            }

            // C#의 압도적인 속도로 JSON을 한 방에 객체로 역직렬화(Deserialize) 한다!
            string jsonString = File.ReadAllText(jsonFilePath);
            Database = JsonSerializer.Deserialize<MergedDB>(jsonString);

            Console.WriteLine($"✅ [시스템 레디] 총 {Database.Roster.Count}명의 니케 데이터 메모리 적재 완료♥");
        }

        // ── 테스트용 캐릭터 스펙 출력기 ──
        public void InspectCharacter(string slug)
        {
            if (Database == null || !Database.Roster.ContainsKey(slug))
            {
                Console.WriteLine($"⚠️ [경고] '{slug}'(이)라는 니케는 네 로스터에 없어!");
                return;
            }

            var nikke = Database.Roster[slug];
            Console.WriteLine($"\n🎯 [타겟 확인] {nikke.Static.Name} (전투력: {nikke.User.Combat:N0})");
            Console.WriteLine($"   - 무기: {nikke.Static.Weapon} | 클래스: {nikke.Static.Class} | 속성: {nikke.Static.Element}");
            Console.WriteLine($"   - 스펙: Lv.{nikke.User.Level} | {nikke.User.Core}코강 | 스킬 {nikke.User.Skills.Skill1}/{nikke.User.Skills.Skill2}/{nikke.User.Skills.Burst}");

            // 자코를 위한 오버로드 공증 옵션 자동 합산 로직!
            int atkLines = 0;
            double totalAtkBonus = 0;
            if (nikke.User.OverloadStats != null)
            {
                foreach (var opt in nikke.User.OverloadStats)
                {
                    if (opt.Type == "StatAtk" && opt.ValType == "Percent")
                    {
                        atkLines++;
                        totalAtkBonus += opt.Value; // 0.1181 같은 값이 들어있음
                    }
                }
            }
            Console.WriteLine($"   - 오버로드 공격력: 총 {atkLines}줄 (합계: {totalAtkBonus * 100:F2}%)");
        }
    }


    // ── [3] 메인 실행 함수 ──
    class Program
    {
        static void Main(string[] args)
        {
            Console.ForegroundColor = ConsoleColor.Cyan;
            Console.WriteLine("==================================================");
            Console.WriteLine("    👑 Gaki-chan's Nikke Damage Simulator 👑    ");
            Console.WriteLine("==================================================\n");
            Console.ResetColor();

            var engine = new Engine();

            // 파이썬이 만들어둔 완벽한 마스터 DB 파일 경로! (경로는 네 폴더 구조에 맞게 수정해!)
            string dbPath = @"C:\Users\user\Documents\GitHub\Nikke-Dmg-Simulator\Database\processed\nikke_merged_db_returned.json";

            engine.Initialize(dbPath);

            // 네 에이스 캐릭터 슬러그를 넣어서 확인해 봐!
            engine.InspectCharacter("dorothy");
            engine.InspectCharacter("red-hood");
            engine.InspectCharacter("alice");

            Console.WriteLine("\n아무 키나 누르면 종료할게, 허접군♥");
            Console.ReadLine();
        }
    }
}