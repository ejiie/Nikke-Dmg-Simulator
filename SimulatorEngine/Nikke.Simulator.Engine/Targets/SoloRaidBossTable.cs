using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json.Serialization;
using Nikke.Simulator.Core.Data;

namespace Nikke.Simulator.Engine.Targets
{
    // ─────────────────────────────────────────────────────────────────────────
    // solo_raid_boss.json (D 파이프라인 `staticdata_solo_raid.py`) → C# 역직렬화 (T04).
    // 파일 = gitignore(게임데이터 재배포 금지) — 부재 = graceful false (fresh clone 정상).
    // 재생성 = `python DataPipeline/run_pipeline.py --stage staticdata`.
    // 39 solo raid 변종: element·레벨 사다리 스탯·파츠·코어 판정.
    // ─────────────────────────────────────────────────────────────────────────

    /// <summary>solo raid 보스 1변종 (배열 원소). 시뮬 소비 필드만 매핑 — 나머지 무시.</summary>
    public sealed class SoloRaidBossDto
    {
        [JsonPropertyName("season")] public int Season { get; set; }
        [JsonPropertyName("code")] public string Code { get; set; } = "";
        /// <summary>일부 변종 null (데이터 실측) — nullable.</summary>
        [JsonPropertyName("model_id")] public int? ModelId { get; set; }
        /// <summary>MonsterTable 미링크 변종(xba001_psid) = null.</summary>
        [JsonPropertyName("monster_id")] public long? MonsterId { get; set; }
        /// <summary>속성 이름 (예 ["Electric"]) — ElementTable 해석 완료본.</summary>
        [JsonPropertyName("elements")] public List<string> Elements { get; set; } = new();
        [JsonPropertyName("element_ids")] public List<int> ElementIds { get; set; } = new();
        /// <summary>유효 레벨 사다리 (예 [55,95,125,145,175,185,200,390]).</summary>
        [JsonPropertyName("levels")] public List<int> Levels { get; set; } = new();
        [JsonPropertyName("stat_group")] public int StatGroup { get; set; }
        /// <summary>key = 레벨 문자열.</summary>
        [JsonPropertyName("stats")] public Dictionary<string, BossLevelStatDto> Stats { get; set; } = new();
        [JsonPropertyName("n_parts")] public int PartsCount { get; set; }
        [JsonPropertyName("core_type")] public string CoreType { get; set; } = "";
    }

    public sealed class BossLevelStatDto
    {
        [JsonPropertyName("level_hp")] public double Hp { get; set; }
        [JsonPropertyName("level_attack")] public double Attack { get; set; }
        [JsonPropertyName("level_defence")] public double Defence { get; set; }
        [JsonPropertyName("level_broken_hp")] public double BrokenHp { get; set; }
        [JsonPropertyName("level_projectile_hp")] public double ProjectileHp { get; set; }
    }

    /// <summary>solo_raid_boss.json 로더 — <c>SkillChainLoader</c> 와 동일한 graceful 패턴.</summary>
    public static class SoloRaidBossTable
    {
        private static readonly string[] RelPath = { "raw", "staticdata", "raid", "solo_raid_boss.json" };

        /// <summary>bin 위치에서 상위로 'Database' 디렉토리를 탐색해 절대 경로 산출. 미발견 = null.</summary>
        public static string FindDataPath()
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null && !Directory.Exists(Path.Combine(dir.FullName, "Database")))
                dir = dir.Parent;
            if (dir == null) return null;
            string path = Path.Combine(dir.FullName, "Database", Path.Combine(RelPath));
            return File.Exists(path) ? path : null;
        }

        /// <summary>로드. 파일 부재 = false (데이터 없는 환경 정상 skip — throw 금지, INV).</summary>
        public static bool TryLoad(out IReadOnlyList<SoloRaidBossDto> bosses, string explicitPath = null)
        {
            bosses = null;
            string path = explicitPath ?? FindDataPath();
            if (path == null || !File.Exists(path)) return false;
            bosses = JsonProvider.LoadJson<List<SoloRaidBossDto>>(path);
            return true;
        }

        /// <summary>code(예 "ebg001_island_zeus") 또는 monster_id 문자열로 변종 검색. 미발견 = null.</summary>
        public static SoloRaidBossDto Find(IReadOnlyList<SoloRaidBossDto> bosses, string codeOrMonsterId)
        {
            if (bosses == null || string.IsNullOrEmpty(codeOrMonsterId)) return null;
            foreach (var b in bosses)
            {
                if (string.Equals(b.Code, codeOrMonsterId, StringComparison.OrdinalIgnoreCase)) return b;
                if (b.MonsterId.HasValue && b.MonsterId.Value.ToString() == codeOrMonsterId) return b;
            }
            return null;
        }
    }
}
