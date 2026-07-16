import unittest

from DataPipeline.etl.cube_effect_cleaner import (
    build_plain,
    parse_effects,
    semantic_effect,
)


def _skill(description, *value_rows):
    return {
        "description_localkey": description,
        "description_value_list": [
            {"description_value": [str(value) for value in row]}
            for row in value_rows
        ],
    }


class CubeEffectCleanerTests(unittest.TestCase):
    def test_single_placeholder_keeps_legacy_values(self):
        effects = parse_effects(
            _skill("Reload Speed ▲ {description_value_01}%.", [10, 20, 30]),
            [1, 2, 3],
        )

        self.assertEqual(1, len(effects))
        self.assertEqual("ReloadSpeed", effects[0]["type"])
        self.assertEqual("description_value_01", effects[0]["value_placeholder"])
        self.assertEqual([10.0, 20.0, 30.0], effects[0]["values"])
        self.assertEqual({}, effects[0]["description_values"])
        self.assertFalse(effects[0]["conditional"])

    def test_bastion_uses_second_placeholder_and_preserves_trigger(self):
        effects = parse_effects(
            _skill(
                "■ Activates when firing {description_value_01} round(s).\n"
                "<color=#00AEFF>Reload ▲ {description_value_02} round(s).</color>",
                [10, 10, 10],
                [1, 2, 3],
            ),
            [1, 2, 3],
        )

        self.assertEqual(1, len(effects))
        effect = effects[0]
        self.assertEqual("ReloadRounds", effect["type"])
        self.assertEqual("description_value_02", effect["value_placeholder"])
        self.assertEqual([1.0, 2.0, 3.0], effect["values"])
        # description_values 는 value_placeholder(v02) 를 제외한 나머지 인자만.
        self.assertEqual(
            {"description_value_01": [10.0, 10.0, 10.0]},
            effect["description_values"],
        )
        self.assertTrue(effect["conditional"])

    def test_assist_preserves_threshold_effect_and_duration(self):
        effects = parse_effects(
            _skill(
                "■ Activates when HP is lower than {description_value_01}%.\n"
                "<color=#00AEFF>Max HP ▲ {description_value_02}% for "
                "{description_value_03} sec.</color>",
                [20, 20, 20],
                [6.07, 9.1, 12.14],
                [20, 20, 20],
            ),
            [1, 2, 3],
        )

        self.assertEqual(1, len(effects))
        effect = effects[0]
        self.assertEqual("MaxHp", effect["type"])
        self.assertEqual("description_value_02", effect["value_placeholder"])
        self.assertEqual([6.07, 9.1, 12.14], effect["values"])
        self.assertEqual(
            [20.0, 20.0, 20.0],
            effect["description_values"]["description_value_01"],
        )
        self.assertEqual(
            [20.0, 20.0, 20.0],
            effect["description_values"]["description_value_03"],
        )
        self.assertNotIn("description_value_02", effect["description_values"])

    def test_semantic_bastion_gets_shots_fired_trigger(self):
        effects = parse_effects(
            _skill(
                "■ Activates when firing {description_value_01} round(s).\n"
                "<color=#00AEFF>Reload ▲ {description_value_02} round(s).</color>",
                [10, 10, 10],
                [1, 2, 3],
            ),
            [1, 2, 3],
        )
        sem = semantic_effect(effects[0])

        self.assertEqual("ReloadRounds", sem["type"])
        self.assertEqual([1.0, 2.0, 3.0], sem["values"])
        self.assertEqual(
            {"type": "ShotsFired", "values": [10.0, 10.0, 10.0]}, sem["trigger"]
        )
        self.assertIsNone(sem["duration_sec"])
        self.assertNotIn("params", sem)

    def test_semantic_assist_gets_hp_trigger_and_duration(self):
        effects = parse_effects(
            _skill(
                "■ Activates when HP is lower than {description_value_01}%.\n"
                "<color=#00AEFF>Max HP ▲ {description_value_02}% for "
                "{description_value_03} sec.</color>",
                [20, 20, 20],
                [6.07, 9.1, 12.14],
                [20, 20, 20],
            ),
            [1, 2, 3],
        )
        sem = semantic_effect(effects[0])

        self.assertEqual(
            {"type": "HpBelow", "values": [20.0, 20.0, 20.0]}, sem["trigger"]
        )
        self.assertEqual([20.0, 20.0, 20.0], sem["duration_sec"])
        self.assertEqual([6.07, 9.1, 12.14], sem["values"])
        self.assertNotIn("params", sem)

    def test_semantic_unconditional_has_null_trigger(self):
        effects = parse_effects(
            _skill("Reload Speed ▲ {description_value_01}%.", [10, 20, 30]),
            [1, 2, 3],
        )
        sem = semantic_effect(effects[0])

        self.assertIsNone(sem["trigger"])
        self.assertIsNone(sem["duration_sec"])
        self.assertNotIn("params", sem)

    def test_plain_lists_every_skill_with_all_parameters(self):
        cubes = {
            "1000312": {
                "name_localkey": "Assist Cube",
                "item_rare": "SSR",
                "harmonycube_skill_group": [
                    _skill(
                        "■ Activates when HP is lower than {description_value_01}%. "
                        "Max HP ▲ {description_value_02}% for {description_value_03} sec.",
                        [20, 20, 20],
                        [6.07, 9.1, 12.14],
                        [20, 20, 20],
                    ),
                ],
                "level1": [1, 2, 3],
            }
        }
        rows = build_plain(cubes)

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual(1000312, row["cube_id"])
        self.assertEqual("Assist Cube", row["cube_name"])
        self.assertEqual(1, row["skill_index"])
        self.assertEqual(
            {
                "description_value_01": [20.0, 20.0, 20.0],
                "description_value_02": [6.07, 9.1, 12.14],
                "description_value_03": [20.0, 20.0, 20.0],
            },
            row["parameters"],
        )

    def test_missing_placeholder_data_is_graceful_noop(self):
        effects = parse_effects(
            _skill("Reload ▲ {description_value_02} round(s).", [10]),
            [1, 2],
        )

        self.assertEqual("ReloadRounds", effects[0]["type"])
        self.assertEqual([0.0, 0.0], effects[0]["values"])


if __name__ == "__main__":
    unittest.main()
