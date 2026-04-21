"""
Offline integration test for the status-flow (pending/completed) logic
in skill_parser_llm.parse_owned_roster.

No Gemini calls — monkey-patches parse_skill and ApiKeyRotator.

Scenarios:
  T1  mixed roster: A=completed skip, B=pending (1 dirty skill) re-parse,
      C=new (no entry) parse from scratch.
  T2  rerun after T1 → 0 calls (everyone completed).
  T3  --overwrite=True on all-completed → all skills re-parsed.
  T4  user flips A.status back to 'pending' but all skills are clean →
      preservation kicks in, 0 calls, status auto-reverts to 'completed'.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile

# ensure utf-8 stdout on cp949 consoles
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                   line_buffering=True)

# --- import under test ---------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from DataPipeline.schema import skill_parser_llm as parser_mod  # noqa: E402


# --- fakes ---------------------------------------------------------------
class FakeParsed:
    """Mimics SkillParsed just enough that .model_dump() returns a dict."""
    def __init__(self, slot: str, name: str, desc: str) -> None:
        self._payload = {
            "skill_name": name,
            "skill_slot": slot,
            "raw_text":   desc,
            "groups":     [{"_fake": True}],
            "stack_conditions": None,
            "parsing_notes": "",
        }

    def model_dump(self) -> dict:
        return dict(self._payload)


class FakeRotator:
    """Matches the ApiKeyRotator constructor signature used by the parser."""
    def __init__(self, *args, **kwargs) -> None:
        pass

    total = 1
    alive = 1

    def current_label(self) -> str:
        return "fake-key"

    def current_client(self):
        raise AssertionError("fake rotator must never be hit")


CALL_LOG: list[tuple[str, str]] = []  # (slot, name) for each parse_skill call


def fake_parse_skill(desc, slot, name="", *, rotator=None, verbose=False):
    CALL_LOG.append((slot, name))
    return FakeParsed(slot, name, desc)


def fake_load_api_keys() -> tuple[list[str], list[int]]:
    return (["FAKE_KEY"], [])


# --- fixtures ------------------------------------------------------------
def make_merged_db() -> dict:
    """Minimal roster with 3 chars, 2 skills each (s1, burst)."""
    def skills(prefix: str) -> list:
        return [
            {"slot": "Skill 1", "name": f"{prefix} S1", "descriptionLevel10": f"{prefix} s1 text"},
            {"slot": "Burst",   "name": f"{prefix} B",  "descriptionLevel10": f"{prefix} b text"},
        ]

    return {
        "uid": 1,
        "global_state": {"synchro_level": 1, "consoles": {}},
        "roster": {
            "A01": {"slug": "char-a", "name_code": "A01",
                    "static": {"name": "Alpha", "skills": skills("A")},
                    "user": {}},
            "B02": {"slug": "char-b", "name_code": "B02",
                    "static": {"name": "Bravo", "skills": skills("B")},
                    "user": {}},
            "C03": {"slug": "char-c", "name_code": "C03",
                    "static": {"name": "Charlie", "skills": skills("C")},
                    "user": {}},
        },
    }


def make_existing_results() -> dict:
    """A is completed, B has a dirty skill (PARSE_ERROR) + status=pending, C absent."""
    def clean(slot: str, name: str) -> dict:
        return {
            "skill_name": name, "skill_slot": slot, "raw_text": f"{name} text",
            "groups": [{"_old": True}], "stack_conditions": None,
            "parsing_notes": "",
        }

    def dirty(slot: str, name: str) -> dict:
        return {
            "skill_name": name, "skill_slot": slot, "raw_text": f"{name} text",
            "groups": [], "stack_conditions": None,
            "parsing_notes": "[PARSE_ERROR] something broke",
        }

    return {
        "A01": {
            "name_code": "A01", "slug": "char-a", "name": "Alpha",
            "status": "completed",
            "skills": [clean("s1", "A S1"), clean("burst", "A B")],
        },
        "B02": {
            "name_code": "B02", "slug": "char-b", "name": "Bravo",
            "status": "pending",
            "skills": [clean("s1", "B S1"), dirty("burst", "B B")],
        },
        # C03 absent → fresh parse
    }


# --- test driver ---------------------------------------------------------
def _reset_calls() -> None:
    CALL_LOG.clear()


def _run(merged_path: str, out_path: str, *, overwrite: bool = False) -> dict:
    return parser_mod.parse_owned_roster(
        merged_path, out_path, overwrite=overwrite, verbose=False,
    )


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  PASS: {msg}")


def run_tests() -> None:
    # monkeypatch
    parser_mod.parse_skill     = fake_parse_skill
    parser_mod.ApiKeyRotator   = FakeRotator
    parser_mod._load_api_keys  = fake_load_api_keys

    with tempfile.TemporaryDirectory() as tmp:
        merged_path = os.path.join(tmp, "merged.json")
        out_path    = os.path.join(tmp, "skills_parsed.json")

        with open(merged_path, "w", encoding="utf-8") as f:
            json.dump(make_merged_db(), f, ensure_ascii=False, indent=2)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(make_existing_results(), f, ensure_ascii=False, indent=2)

        # ---------- T1 -----------------------------------------------------
        print("\n=== T1: mixed roster (A=completed, B=pending, C=new) ===")
        _reset_calls()
        res = _run(merged_path, out_path)

        # A skipped entirely
        a_skills = res["A01"]["skills"]
        _assert(all("_old" in s.get("groups", [{}])[0] for s in a_skills),
                "A01 skills preserved exactly (no re-parse)")
        _assert(res["A01"]["status"] == "completed", "A01 status stays completed")

        # B: s1 preserved (clean), burst re-parsed (was dirty)
        b_by_slot = {s["skill_slot"]: s for s in res["B02"]["skills"]}
        _assert("_old" in b_by_slot["s1"]["groups"][0],
                "B02/s1 preserved (was clean)")
        _assert(b_by_slot["burst"]["groups"] == [{"_fake": True}],
                "B02/burst re-parsed (was dirty)")
        _assert(res["B02"]["status"] == "completed",
                "B02 status flips to completed after fix")

        # C: both skills fresh-parsed
        c_skills = res["C03"]["skills"]
        _assert(all(s["groups"] == [{"_fake": True}] for s in c_skills),
                "C03 both skills fresh-parsed")
        _assert(res["C03"]["status"] == "completed", "C03 status=completed")

        # call count: B.burst + C.s1 + C.burst = 3
        _assert(len(CALL_LOG) == 3,
                f"T1 made exactly 3 API calls (got {len(CALL_LOG)}: {CALL_LOG})")

        # ---------- T2 -----------------------------------------------------
        print("\n=== T2: rerun with all completed → 0 calls ===")
        _reset_calls()
        res2 = _run(merged_path, out_path)
        _assert(len(CALL_LOG) == 0,
                f"T2 made 0 calls (got {len(CALL_LOG)})")
        _assert(all(e["status"] == "completed" for e in res2.values()),
                "T2 all statuses remain completed")

        # ---------- T3 -----------------------------------------------------
        print("\n=== T3: --overwrite=True → every skill re-parsed ===")
        _reset_calls()
        res3 = _run(merged_path, out_path, overwrite=True)
        # 3 chars × 2 skills = 6 calls
        _assert(len(CALL_LOG) == 6,
                f"T3 overwrite made 6 calls (got {len(CALL_LOG)})")
        # preservation must be bypassed → all groups are _fake, none _old
        for code, entry in res3.items():
            for s in entry["skills"]:
                _assert(s["groups"] == [{"_fake": True}],
                        f"T3 {code}/{s['skill_slot']} is freshly parsed "
                        "(no preserved _old blob)")
            _assert(entry["status"] == "completed",
                    f"T3 {code} status=completed")

        # ---------- T4 -----------------------------------------------------
        print("\n=== T4: manual status flip to pending, all skills clean "
              "→ 0 calls, status auto-reverts ===")
        # flip A01 back to pending (skills are still clean from T3)
        with open(out_path, "r", encoding="utf-8") as f:
            cur = json.load(f)
        cur["A01"]["status"] = "pending"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)

        _reset_calls()
        res4 = _run(merged_path, out_path)
        _assert(len(CALL_LOG) == 0,
                f"T4 made 0 calls despite pending status "
                f"(preservation kicked in) — got {len(CALL_LOG)}")
        _assert(res4["A01"]["status"] == "completed",
                "T4 A01 status auto-reverts pending→completed")
        # A01 skills still look like T3's fake blobs (not mutated)
        for s in res4["A01"]["skills"]:
            _assert(s["groups"] == [{"_fake": True}],
                    f"T4 A01/{s['skill_slot']} preserved unchanged")

    print("\nALL SCENARIOS PASSED.")


if __name__ == "__main__":
    run_tests()
