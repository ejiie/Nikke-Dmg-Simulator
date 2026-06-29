using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace Nikke.Simulator.Core.Data.Constants
{
    /// <summary>
    /// 큐브/소장품 공식 특수효과 표 (cube_effect_table.json / collection_effect_table.json).
    /// tid(큐브) / 무기(소장품) → EffectType → 레벨별 값. Get* 은 특정 레벨의 효과를
    /// **분수(percent/100)** Dictionary 로 반환 (라우팅은 그대로 합산).
    /// </summary>
    public static class EffectTable
    {
        private class EffEntryDto { public string type { get; set; } public List<double> values { get; set; } }
        private class CubeDto { public List<EffEntryDto> effects { get; set; } }
        private class CollDto { public List<EffEntryDto> effects { get; set; } }

        private static Dictionary<int, List<(EffectType type, double[] vals)>> _cube = new();
        private static Dictionary<string, List<(EffectType type, double[] vals)>> _coll = new();

        // C# WeaponType(풀네임) → effect table 키(약어)
        private static readonly Dictionary<string, string> WeaponAbbrev = new()
        {
            ["Assault Rifle"] = "AR",
            ["Sniper Rifle"] = "SR",
            ["Rocket Launcher"] = "RL",
            ["Shotgun"] = "SG",
            ["Minigun"] = "MG",
            ["SMG"] = "SMG",
        };

        private static List<(EffectType, double[])> Parse(List<EffEntryDto> effects)
        {
            var list = new List<(EffectType, double[])>();
            foreach (var e in effects ?? new List<EffEntryDto>())
            {
                if (Enum.TryParse<EffectType>(e.type, out var et) && et != EffectType.Unknown)
                    list.Add((et, (e.values ?? new List<double>()).ToArray()));
            }
            return list;
        }

        public static void InitializeCube(string jsonPath)
        {
            if (string.IsNullOrEmpty(jsonPath) || !File.Exists(jsonPath)) return;
            var raw = JsonSerializer.Deserialize<Dictionary<string, CubeDto>>(File.ReadAllText(jsonPath));
            if (raw == null) return;
            var d = new Dictionary<int, List<(EffectType, double[])>>();
            foreach (var kv in raw)
                if (int.TryParse(kv.Key, out int tid))
                    d[tid] = Parse(kv.Value?.effects);
            _cube = d;
        }

        public static void InitializeCollection(string jsonPath)
        {
            if (string.IsNullOrEmpty(jsonPath) || !File.Exists(jsonPath)) return;
            var raw = JsonSerializer.Deserialize<Dictionary<string, CollDto>>(File.ReadAllText(jsonPath));
            if (raw == null) return;
            _coll = raw.ToDictionary(kv => kv.Key, kv => Parse(kv.Value?.effects));
        }

        private static Dictionary<EffectType, double> Resolve(List<(EffectType type, double[] vals)> effects, int level)
        {
            var r = new Dictionary<EffectType, double>();
            if (effects == null) return r;
            foreach (var (type, vals) in effects)
            {
                if (vals.Length == 0) continue;
                int idx = Math.Clamp(level - 1, 0, vals.Length - 1);
                double frac = vals[idx] / 100.0;   // percent → fraction
                r[type] = (r.TryGetValue(type, out var cur) ? cur : 0.0) + frac;
            }
            return r;
        }

        /// <summary>큐브 tid + 큐브 레벨 → {EffectType: 분수}. 미장착/미발견 시 빈 dict.</summary>
        public static Dictionary<EffectType, double> GetCubeEffects(int tid, int level)
            => _cube.TryGetValue(tid, out var e) ? Resolve(e, level) : new Dictionary<EffectType, double>();

        /// <summary>소장품 무기(풀네임) + 컬렉션 레벨 → {EffectType: 분수}.</summary>
        public static Dictionary<EffectType, double> GetCollectionEffects(string weapon, int level)
        {
            var key = WeaponAbbrev.TryGetValue(weapon ?? "", out var a) ? a : (weapon ?? "");
            return _coll.TryGetValue(key, out var e) ? Resolve(e, level) : new Dictionary<EffectType, double>();
        }
    }
}
