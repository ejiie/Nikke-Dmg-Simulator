using System;
using System.Collections.Generic;
using System.IO;
using Nikke.Simulator.Core.Data;

namespace Nikke.Simulator.Engine.Skills
{
    /// <summary>
    /// K4 — skill_chains.json 로더. 공식 스킬 데이터원 (DESIGN §6 결정 2026-07-08).
    ///
    /// 파일 = `Database/raw/staticdata/assembled/skill_chains.json` — **gitignore**(게임데이터
    /// 재배포 금지). 부재 = 정상 상황(fresh clone) → <see cref="TryLoad"/> false, throw 금지 (INV).
    /// 재생성 = `memorypack_decode.py` → `staticdata_skill_chains.py` (StaticData.zip 로컬 필요).
    /// </summary>
    public static class SkillChainLoader
    {
        /// <summary>Database 루트 기준 상대 경로 (processed 아님 — 복호물은 raw/staticdata).</summary>
        private static readonly string[] RelPath = { "raw", "staticdata", "assembled", "skill_chains.json" };

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

        /// <summary>로드 + 참조 무결성 검증. 파일 부재 = false (데이터 없는 환경 정상 skip).</summary>
        public static bool TryLoad(out SkillChainsDto chains, string explicitPath = null)
        {
            chains = null;
            string path = explicitPath ?? FindDataPath();
            if (path == null || !File.Exists(path)) return false;
            chains = JsonProvider.LoadJson<SkillChainsDto>(path);
            Validate(chains);
            return true;
        }

        /// <summary>
        /// 참조 무결성: 모든 체인의 function id 가 Functions 사전에 존재해야 한다
        /// (조립기의 connected BFS 가 보장 — 깨지면 조립 재실행 필요 신호).
        /// </summary>
        private static void Validate(SkillChainsDto c)
        {
            var missing = new List<int>();

            void Check(IEnumerable<int> ids)
            {
                if (ids == null) return;
                foreach (int fid in ids)
                    if (fid != 0 && !c.Functions.ContainsKey(fid.ToString()))
                        missing.Add(fid);
            }

            foreach (var ch in c.Characters.Values)
                foreach (var slot in ch.Skills.Values)
                    foreach (var lv in slot.Levels.Values)
                        Check(lv.FunctionIds);
            foreach (var b in c.Bosses.Values)
            {
                Check(b.PassiveFunctionIds);
                foreach (var s in b.Skills)
                {
                    Check(s.UseFunctionIds);
                    Check(s.HurtFunctionIds);
                }
            }

            if (missing.Count > 0)
                throw new InvalidDataException(
                    $"skill_chains.json 참조 무결성 위반 — Functions 사전에 없는 id {missing.Count}개 " +
                    $"(예: {missing[0]}). 조립기(staticdata_skill_chains.py) 재실행 필요.");
        }
    }
}
