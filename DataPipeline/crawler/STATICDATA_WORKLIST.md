# StaticData 실패 표 워크리스트 (sim-핵심)

> 실패 원인 = 필드 타입 미확정(int64/float/List<int>vs<struct>). 정답=`nikke_types.txt`(맥 arm64 frida).
> 그 전엔 **필드별 타입 수동 추론**으로 도전. 힌트: `i64?`=큰HP류(8B?), `flt?`=비율, `str`=문자열마커, `LIST`=재귀[count]+중첩, `int`=4B.
> 이미 해결(int64 지정): CharacterStat/MonsterStatEnhance = `staticdata_decode.py` INT64 딕셔너리. Attractive/Element/Cover/RecycleResearch/SkillInfo = clean.

## Function (19111행, 55필드) — unpack_from requires a buffer of at least 6553357 bytes for unpacking 4 bytes at offset 6553353 (actual buffer size is 6553356), 13407/19111 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group_id | int |
| 2 | Level | int |
| 3 | Function_battlepower | i64? |
| 4 | Name_localkey | str |
| 5 | Description_localkey | str |
| 6 | Buff | int |
| 7 | Buff_remove | int |
| 8 | Function_type | int |
| 9 | Function_standard | int |
| 10 | Function_value_type | int |
| 11 | Function_value | int |
| 12 | Full_count | int |
| 13 | Is_cancel | int |
| 14 | Delay_type | int |
| 15 | Delay_value | int |
| 16 | Duration_type | flt? |
| 17 | Duration_value | flt? |
| 18 | Limit_value | int |
| 19 | Function_target | int |
| 20 | Timing_trigger_type | int |
| 21 | Timing_trigger_standard | int |
| 22 | Timing_trigger_value | int |
| 23 | Status_trigger_type | int |
| 24 | Status_trigger_standard | int |
| 25 | Status_trigger_value | int |
| 26 | Status_trigger2_type | int |
| 27 | Status_trigger2_standard | int |
| 28 | Status_trigger2_value | int |
| 29 | Keeping_type | int |
| 30 | Buff_icon | str |
| 31 | Element_reaction_icon | str |
| 32 | Shot_fx_list_type | int |
| 33 | Fx_prefab_01 | str |
| 34 | Fx_target_01 | int |
| 35 | Fx_socket_point_01 | str |
| 36 | Fx_prefab_02 | str |
| 37 | Fx_target_02 | int |
| 38 | Fx_socket_point_02 | str |
| 39 | Fx_prefab_03 | str |
| 40 | Fx_target_03 | int |
| 41 | Fx_socket_point_03 | str |
| 42 | Fx_prefab_full | str |
| 43 | Fx_target_full | int |
| 44 | Fx_socket_point_full | str |
| 45 | Fx_prefab_01_arena | str |
| 46 | Fx_target_01_arena | int |
| 47 | Fx_socket_point_01_arena | str |
| 48 | Fx_prefab_02_arena | str |
| 49 | Fx_target_02_arena | int |
| 50 | Fx_socket_point_02_arena | str |
| 51 | Fx_prefab_03_arena | str |
| 52 | Fx_target_03_arena | int |
| 53 | Fx_socket_point_03_arena | str |
| 54 | Connected_function | int |

## Monster (2035행, 32필드) — listcnt 268435495@Skill_data, 0/2035 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Element_id | int |
| 2 | Monster_model_id | int |
| 3 | Ui_grade | int |
| 4 | Name_localkey | str |
| 5 | Appearance_localkey | str |
| 6 | Description_localkey | str |
| 7 | Is_irregular | int |
| 8 | Hp_ratio | flt? |
| 9 | Defence_ratio | flt? |
| 10 | Attack_ratio | flt? |
| 11 | Energy_resist_ratio | flt? |
| 12 | Metal_resist_ratio | flt? |
| 13 | Bio_resist_ratio | flt? |
| 14 | Detector_center | int |
| 15 | Detector_radius | int |
| 16 | Nonetarget | int |
| 17 | Functionnonetarget | int |
| 18 | Spot_ai | int |
| 19 | Spot_ai_defense | int |
| 20 | Spot_ai_basedefense | int |
| 21 | Spot_move_speed | int |
| 22 | Spot_acceleration_time | flt? |
| 23 | Fixed_spawn_type | int |
| 24 | Spot_rand_ratio_normal | flt? |
| 25 | Spot_rand_ratio_jump | flt? |
| 26 | Spot_rand_ratio_drop | flt? |
| 27 | Spot_rand_ratio_dash | flt? |
| 28 | Spot_rand_ratio_teleport | flt? |
| 29 | Passive_skill_id | int |
| 30 | Skill_data | LIST |
| 31 | Statenhance_id | int |

## MonsterParts (668행, 23필드) — index out of range, 458/668 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Monster_model_id | int |
| 2 | Parts_name_localkey | str |
| 3 | Damage_hp_ratio | flt? |
| 4 | Hp_ratio | flt? |
| 5 | Defence_ratio | flt? |
| 6 | Destroy_after_anim | str |
| 7 | Destroy_after_movable | int |
| 8 | Passive_skill_id | int |
| 9 | Visible_hp | i64? |
| 10 | Linked_parts_id | int |
| 11 | Weapon_object | str |
| 12 | Weapon_object_enum | int |
| 13 | Parts_type | int |
| 14 | Parts_object | str |
| 15 | Energy_resist_ratio | flt? |
| 16 | Metal_resist_ratio | flt? |
| 17 | Bio_resist_ratio | flt? |
| 18 | Attack_ratio | flt? |
| 19 | Parts_skin | str |
| 20 | Monster_destroy_anim_trigger | str |
| 21 | Is_main_part | int |
| 22 | Is_parts_damage_able | int |

## MonsterSkill (4632행, 46필드) — MIS 76578/1281084, 4632/4632 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Name_localkey | str |
| 2 | Description_localkey | str |
| 3 | Skill_icon | str |
| 4 | Skill_ani_number | int |
| 5 | Weapon_type | int |
| 6 | Attack_type | int |
| 7 | Fire_type | int |
| 8 | Shot_count | int |
| 9 | Shot_timing | int |
| 10 | Penetration | flt? |
| 11 | Projectile_speed | int |
| 12 | Projectile_hp_ratio | flt? |
| 13 | Projectile_def_ratio | flt? |
| 14 | Projectile_radius_object | str |
| 15 | Projectile_radius | int |
| 16 | Spot_explosion_range | i64? |
| 17 | Is_destroyable_projectile | int |
| 18 | Relate_anim | str |
| 19 | Deceleration_rate | flt? |
| 20 | Casting_time | int |
| 21 | Break_object | str |
| 22 | Break_object_hp_raito | i64? |
| 23 | Move_object | str |
| 24 | Delay_time | int |
| 25 | Skill_value_type_01 | int |
| 26 | Skill_value_01 | int |
| 27 | Skill_value_type_02 | int |
| 28 | Skill_value_02 | int |
| 29 | Target_character_ratio | flt? |
| 30 | Target_cover_ratio | flt? |
| 31 | Target_nothing_ratio | flt? |
| 32 | Weapon_object_enum | int |
| 33 | Calling_group_id | int |
| 34 | Prefer_target | int |
| 35 | Show_lock_on | int |
| 36 | Target_count | int |
| 37 | Object_resource | str |
| 38 | Object_position_type | int |
| 39 | Object_position | int |
| 40 | Is_using_timeline | int |
| 41 | Control_gauge | int |
| 42 | Show_breakable_time | int |
| 43 | Control_parts | int |
| 44 | Cancel_type | int |
| 45 | Linked_parts | int |

## MonsterStatEnhance (30671행, 12필드) — index out of range, 19101/30671 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group_id | int |
| 2 | Lv | int |
| 3 | Level_hp | i64? |
| 4 | Level_attack | int |
| 5 | Level_defence | int |
| 6 | Level_statdamageratio | flt? |
| 7 | Level_energy_resist | int |
| 8 | Level_metal_resist | int |
| 9 | Level_bio_resist | int |
| 10 | Level_projectile_hp | i64? |
| 11 | Level_broken_hp | i64? |

## MonsterStageLvChange (402행, 10필드) — index out of range, 92/402 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group | int |
| 2 | Step | int |
| 3 | Condition_type | int |
| 4 | Condition_value_min | int |
| 5 | Condition_value_max | int |
| 6 | Monster_stage_lv | int |
| 7 | Passive_skill_id | int |
| 8 | Target_passive_skill_id | int |
| 9 | Gimmickobject_lv_control | int |

## MonsterCallingList (1765행, 9필드) — MIS 14477/72369, 1765/1765 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group_id | int |
| 2 | Monster_id | int |
| 3 | Spawn_type | int |
| 4 | Start_point | i64? |
| 5 | ActionPoint | i64? |
| 6 | Dir_point | i64? |
| 7 | Spawn_time | int |
| 8 | Attack_time | int |

## Character (1883행, 40필드) — MIS 348223/471489, 1883/1883 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Name_localkey | str |
| 2 | Description_localkey | str |
| 3 | Resource_id | int |
| 4 | Additional_skins | str |
| 5 | Name_code | int |
| 6 | Order | int |
| 7 | Original_rare | int |
| 8 | Grade_core_id | int |
| 9 | Grow_grade | int |
| 10 | Stat_enhance_id | int |
| 11 | Corporation | flt? |
| 12 | Corporation_sub_type | flt? |
| 13 | Class | int |
| 14 | Element_id | int |
| 15 | Critical_ratio | flt? |
| 16 | Critical_damage | int |
| 17 | Shot_id | int |
| 18 | Bonusrange_min | int |
| 19 | Bonusrange_max | int |
| 20 | Use_burst_skill | int |
| 21 | Change_burst_step | int |
| 22 | Burst_apply_delay | int |
| 23 | Burst_duration | flt? |
| 24 | Ulti_skill_id | int |
| 25 | Skill1_id | int |
| 26 | Skill1_table | int |
| 27 | Skill2_id | int |
| 28 | Skill2_table | int |
| 29 | Eff_category_type | int |
| 30 | Eff_category_value | int |
| 31 | Category_type_1 | int |
| 32 | Category_type_2 | int |
| 33 | Category_type_3 | int |
| 34 | Cv_localkey | str |
| 35 | Squad | int |
| 36 | Piece_id | int |
| 37 | Is_visible | int |
| 38 | Prism_is_active | int |
| 39 | Is_detail_close | int |

## CharacterShot (256행, 58필드) — listcnt 1702126433@Hurt_function_id_list, 12/256 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Name_localkey | str |
| 2 | Description_localkey | str |
| 3 | Camera_work | int |
| 4 | Weapon_type | int |
| 5 | Fire_type | int |
| 6 | Attack_type | int |
| 7 | Counter_enermy | int |
| 8 | Input_type | int |
| 9 | Is_targeting | int |
| 10 | Prefer_target | int |
| 11 | Prefer_target_condition | int |
| 12 | Damage | int |
| 13 | Shot_count | int |
| 14 | Muzzle_count | int |
| 15 | Multi_target_count | int |
| 16 | Center_shot_count | int |
| 17 | Shot_timing | int |
| 18 | Max_ammo | int |
| 19 | Maintain_fire_stance | int |
| 20 | Uptype_fire_timing | int |
| 21 | Reload_time | int |
| 22 | Reload_bullet | int |
| 23 | Reload_start_ammo | int |
| 24 | Rate_of_fire_reset_time | int |
| 25 | Rate_of_fire | int |
| 26 | End_rate_of_fire | int |
| 27 | Rate_of_fire_change_pershot | int |
| 28 | Burst_energy_pershot | int |
| 29 | Target_burst_energy_pershot | int |
| 30 | Penetration | flt? |
| 31 | Spot_first_delay | int |
| 32 | Spot_last_delay | int |
| 33 | Start_accuracy_circle_scale | int |
| 34 | End_accuracy_circle_scale | int |
| 35 | Accuracy_change_pershot | int |
| 36 | Accuracy_change_speed | int |
| 37 | Auto_start_accuracy_circle_scale | int |
| 38 | Auto_end_accuracy_circle_scale | int |
| 39 | Auto_accuracy_change_pershot | int |
| 40 | Auto_accuracy_change_speed | int |
| 41 | Zoom_rate | flt? |
| 42 | Multi_aim_range | int |
| 43 | Spot_projectile_speed | int |
| 44 | Charge_time | int |
| 45 | Full_charge_damage | int |
| 46 | Full_charge_burst_energy | int |
| 47 | Spot_radius_object | str |
| 48 | Spot_radius | int |
| 49 | Spot_explosion_range | i64? |
| 50 | Homing_script | str |
| 51 | Core_damage_rate | flt? |
| 52 | Use_function_id_list | LIST |
| 53 | Hurt_function_id_list | LIST |
| 54 | Shake_id | int |
| 55 | ShakeType | int |
| 56 | ShakeWeight | int |
| 57 | Aim_prefab | str |

## CharacterSkill (4277행, 17필드) — listcnt 66048@Before_hurt_function_id_list, 0/4277 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Attack_type | int |
| 2 | Counter_type | int |
| 3 | Prefer_target | int |
| 4 | Prefer_target_condition | int |
| 5 | Skill_cooltime | int |
| 6 | Skill_type | int |
| 7 | Skill_value_data | LIST |
| 8 | Duration_type | flt? |
| 9 | Duration_value | flt? |
| 10 | Before_use_function_id_list | LIST |
| 11 | Before_hurt_function_id_list | LIST |
| 12 | After_use_function_id_list | LIST |
| 13 | After_hurt_function_id_list | LIST |
| 14 | Resource_name | str |
| 15 | Shake_id | int |
| 16 | Icon | str |

## CharacterStat (64800행, 9필드) — MIS 531364/2656804, 64800/64800 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group | int |
| 2 | Level | int |
| 3 | Level_hp | i64? |
| 4 | Level_attack | int |
| 5 | Level_defence | int |
| 6 | Level_energy_resist | int |
| 7 | Level_metal_resist | int |
| 8 | Level_bio_resist | int |

## CharacterStatEnhance (54행, 14필드) — MIS 394/3514, 54/54 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Grade_ratio | flt? |
| 2 | Grade_hp | i64? |
| 3 | Grade_attack | int |
| 4 | Grade_defence | int |
| 5 | Grade_energy_resist | int |
| 6 | Grade_metal_resist | int |
| 7 | Grade_bio_resist | int |
| 8 | Core_hp | i64? |
| 9 | Core_attack | int |
| 10 | Core_defence | int |
| 11 | Core_energy_resist | int |
| 12 | Core_metal_resist | int |
| 13 | Core_bio_resist | int |

## CharacterReaction (2983행, 13필드) — index out of range, 1510/2983 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Reaction_type | int |
| 2 | Special_lobby_change_step | int |
| 3 | Camera_shake | int |
| 4 | Attractive_level_min | int |
| 5 | Attractive_level_max | int |
| 6 | Resource_id | int |
| 7 | Costume_index | int |
| 8 | Eventlobby_id | int |
| 9 | Animation_clip | str |
| 10 | Speech_localkey | str |
| 11 | Rection_voice | int |
| 12 | Probability | int |

## StateEffect (5113행, 4필드) — MIS 391957/785612, 5113/5113 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | StateEffectGroupId | int |
| 1 | EquipmentOptionTid | int |
| 2 | OptionRatio | flt? |
| 3 | StateEffect | int |

## SkillInfo (9130행, 10필드) — listcnt 2032110@Description_value_list, 61/9130 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group_id | int |
| 2 | Skill_level | int |
| 3 | Next_level_id | int |
| 4 | Level_up_cost_id | int |
| 5 | Icon | str |
| 6 | Name_localkey | str |
| 7 | Description_localkey | str |
| 8 | Info_description_localkey | str |
| 9 | Description_value_list | LIST |

## CoverStatEnhance (1200행, 4필드) — index out of range, 145/1200 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Lv | int |
| 2 | Level_hp | i64? |
| 3 | Level_defence | int |

## ConfigBattle (139행, 2필드) — index out of range, 14/139 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Value | int |

## ItemEquip (124행, 15필드) — MIS 1135/30906, 124/124 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Name_localkey | str |
| 2 | Description_localkey | str |
| 3 | Resource_id | int |
| 4 | Item_type | int |
| 5 | Item_sub_type | int |
| 6 | Class | int |
| 7 | Item_rare | int |
| 8 | Grade_core_id | int |
| 9 | Grow_grade | int |
| 10 | Stat | int |
| 11 | Option_slot | int |
| 12 | Option_cost | int |
| 13 | Option_change_cost | int |
| 14 | Option_lock_cost | int |

## ItemHarmonyCube (16행, 15필드) — index out of range, 13/16 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Name_localkey | str |
| 2 | Description_localkey | str |
| 3 | Location_id | int |
| 4 | Location_localkey | str |
| 5 | Order | int |
| 6 | Resource_id | int |
| 7 | Bg | int |
| 8 | Bg_color | int |
| 9 | Item_type | int |
| 10 | Item_sub_type | int |
| 11 | Item_rare | int |
| 12 | Class | int |
| 13 | Level_enhance_id | int |
| 14 | Harmonycube_skill_group | int |

## ItemHarmonyCubeLevel (240행, 9필드) — index out of range, 132/240 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Level_enhance_id | int |
| 2 | Level | int |
| 3 | Skill_levels | int |
| 4 | Material_id | int |
| 5 | Material_value | int |
| 6 | Gold_value | int |
| 7 | Slot | int |
| 8 | Harmonycube_stats | int |

## FavoriteItem (29행, 17필드) — listcnt 1702127973@Collection_skill_group_data, 0/29 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Name_localkey | str |
| 2 | Description_localkey | str |
| 3 | Icon_resource_id | int |
| 4 | Img_resource_id | int |
| 5 | Prop_resource_id | int |
| 6 | Order | int |
| 7 | Favorite_rare | int |
| 8 | Favorite_type | int |
| 9 | Weapon_type | int |
| 10 | Name_code | int |
| 11 | Max_level | int |
| 12 | Level_enhance_id | int |
| 13 | Probability_group | int |
| 14 | Collection_skill_group_data | LIST |
| 15 | Favoriteitem_skill_group_data | LIST |
| 16 | Albumcategory_id | int |

## ObjectStatEnhance (3600행, 5필드) — index out of range, 544/3600 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Grade | int |
| 2 | Lv | int |
| 3 | Level_hp | i64? |
| 4 | Level_defence | int |

## StageStatIncrease (1037행, 6필드) — index out of range, 958/1037 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group_id | int |
| 2 | Battle_power_ratio_min | flt? |
| 3 | Battle_power_ratio_max | flt? |
| 4 | Stat_increase | int |
| 5 | Textcolor | int |

## InterceptNormal (4행, 27필드) — MIS 1052/1188, 4/4 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group | int |
| 2 | Type | int |
| 3 | Name | int |
| 4 | Short_name | str |
| 5 | Description | str |
| 6 | Thumbnail | int |
| 7 | Monster_spine | int |
| 8 | Monster_spine_scale | int |
| 9 | Order | int |
| 10 | Character_lv | int |
| 11 | Monster_stage_lv | int |
| 12 | Dynamic_object_stage_lv | int |
| 13 | Cover_stage_lv | int |
| 14 | Monster_stage_lv_change_group | int |
| 15 | Spot_type | int |
| 16 | Spot_id | int |
| 17 | Dummy_spot_id | int |
| 18 | Auto_charge_id | int |
| 19 | Ticket_count | int |
| 20 | Condition_reward_group | int |
| 21 | Percent_condition_reward_group | int |
| 22 | Use_reward_priority | int |
| 23 | Priority_grade | int |
| 24 | Use_fixed_result | int |
| 25 | Fixed_damage | int |
| 26 | Result_character_resource_id | int |

## InterceptSpecial (6행, 26필드) — MIS 1914/1666, 6/6 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Group | int |
| 2 | Name | int |
| 3 | Short_name | str |
| 4 | Description | str |
| 5 | Thumbnail | int |
| 6 | Monster_spine | int |
| 7 | Monster_spine_scale | int |
| 8 | Order | int |
| 9 | Character_lv | int |
| 10 | Monster_stage_lv | int |
| 11 | Dynamic_object_stage_lv | int |
| 12 | Cover_stage_lv | int |
| 13 | Monster_stage_lv_change_group | int |
| 14 | Spot_type | int |
| 15 | Spot_id | int |
| 16 | Dummy_spot_id | int |
| 17 | Auto_charge_id | int |
| 18 | Ticket_count | int |
| 19 | Condition_reward_group | int |
| 20 | Percent_condition_reward_group | int |
| 21 | Use_reward_priority | int |
| 22 | Priority_grade | int |
| 23 | Use_fixed_result | int |
| 24 | Fixed_damage | int |
| 25 | Result_character_resource_id | int |

## MultiRaid (100행, 16필드) — index out of range, 77/100 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Name | int |
| 2 | Player_count | int |
| 3 | Character_select_time_limit | int |
| 4 | Character_lv | int |
| 5 | Stage_level | int |
| 6 | Monster_stage_lv | int |
| 7 | Dynamic_object_stage_lv | int |
| 8 | Cover_stage_lv | int |
| 9 | Monster_stage_lv_change_group | int |
| 10 | Spot_id | int |
| 11 | Monster_stage_lv_change_group_easy | int |
| 12 | Spot_id_easy | int |
| 13 | Condition_reward_group | int |
| 14 | Reward_limit_count | int |
| 15 | Rank_condition_reward_group | int |

## CampaignStage (4221행, 27필드) — index out of range, 2554/4221 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Chapter_id | int |
| 2 | Chapter_mod | int |
| 3 | Stage_child | int |
| 4 | Parents_id | int |
| 5 | Group_id | int |
| 6 | Name_localkey | str |
| 7 | Stage_category | int |
| 8 | Stage_type | int |
| 9 | Spot_autocontrol | int |
| 10 | Enter_condition | int |
| 11 | Monster_stage_lv | int |
| 12 | Dynamic_object_stage_lv | int |
| 13 | Standard_battle_power | int |
| 14 | Stage_stat_increase_group_id | int |
| 15 | Is_use_quick_battle | int |
| 16 | Field_monster_id | int |
| 17 | Spot_id | int |
| 18 | Reward_id | int |
| 19 | Enter_scenario_type | int |
| 20 | Enter_scenario | int |
| 21 | Exit_scenario_type | int |
| 22 | Exit_scenario | int |
| 23 | Current_outpost_battle_id | int |
| 24 | Cleared_outpost_battle_id | int |
| 25 | Fixed_play_character_id | int |
| 26 | Character_lv | int |

## LostSectorStage (642행, 14필드) — index out of range, 195/642 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Sector | int |
| 2 | Parents_id | int |
| 3 | Name_localkey | str |
| 4 | Monster_stage_lv | int |
| 5 | Dynamic_object_stage_lv | int |
| 6 | Standard_battle_power | int |
| 7 | Stage_stat_increase_group_id | int |
| 8 | Is_use_quick_battle | int |
| 9 | Spot_autocontrol | int |
| 10 | Field_monster_id | int |
| 11 | Spot_id | int |
| 12 | Enter_scenario | int |
| 13 | Exit_scenario | int |

## SquadInfo (66행, 5필드) — index out of range, 25/66 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Squad | int |
| 2 | Squad_name | str |
| 3 | Squad_description | str |
| 4 | Resource_id | int |

## EquipmentGrade (10행, 3필드) — index out of range, 5/10 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Max_level | int |
| 2 | Rarity | int |

## GradeCoreEquipment (10행, 6필드) — index out of range, 9/10 rec
| # | 필드 | 타입추측 |
|--|--|--|
| 0 | Id | int |
| 1 | Grade | int |
| 2 | Max_level | int |
| 3 | Max_grade | int |
| 4 | Material_value | int |
| 5 | Rarity | int |

