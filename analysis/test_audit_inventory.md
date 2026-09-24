# Test inventory (phase 0, generated 2026-09-19)

583 tests in 36 files.


## test_advice_gates.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestDyingHardGate.test_affordable_level_after_buy_stays_deferred | 8 | dict |  | 2 | t16 regression: dying at 8 HP, the level IS affordable after the |
| TestDyingHardGate.test_short_level_form_unchanged | 8 | dict |  | 2 | A dying plan whose buy leaves the level short keeps the short |
| TestDyingHardGate.test_healthy_board_still_gets_actionable_level | 8 | dict |  | 1 | Same shape at healthy HP: the affordable level is still advised. |
| TestCastGoldGate.test_gold_zero_cast_survives | 11 | dict |  | 3 | The old gate demoted a hand cast at gold 0 ('no gold to cast') — |
| TestCastGoldGate.test_cast_never_eats_or_demotes_on_the_buy | 12 | dict |  | 2 | A hand cast rides along with the committed buy — no pricing |
| TestCastGoldGate.test_funded_cast_survives | 10 | dict |  | 1 | 'Castable NOW', not a ban: a funded cast keeps its step. |
| TestStickyFlipRules.test_dying_blocks_cross_tribe_flip_even_with_evidence | 5 | - |  | 1 | Equal hits, empty board — nothing stronger to take over with. |
| TestStickyFlipRules.test_dying_takes_over_on_dominant_board | 16 | - |  | 1 | 2026-09-18 regression: a triple-golden Mech core at 4 HP stayed |
| TestStickyFlipRules.test_dying_still_holds_on_minority_evidence | 11 | - |  | 1 | Equal hits, the new comp a minority of the board (the t16 |
| TestStickyFlipRules.test_dying_flips_on_strictly_more_evidence | 6 | - |  | 1 |  |
| TestNeverWonLadder.test_zero_wins_defers_level_at_any_tier | 7 | dict |  | 2 |  |
| TestNeverWonLadder.test_a_win_breaks_the_alarm | 5 | dict |  | 1 |  |
| TestOpponentRunClause.test_run_clause_renders | 5 | - |  | 1 |  |
| TestOpponentRunClause.test_no_run_clause_without_quiet | 4 | - |  | 1 |  |
| TestOpponentRunClause.test_fresh_bleed_no_clause | 5 | - |  | 1 |  |
| TestOpponentRunClause.test_single_unit_board_blocks_evidence_free_flip | 7 | - |  | 1 |  |
| TestOpponentRunClause.test_two_units_flip | 7 | - |  | 1 |  |
| TestOpponentRunClause.test_stronger_evidence_flips_without_units | 6 | - |  | 1 |  |
| TestForecastHonesty.test_favored_fresh_anchor_unchanged | 4 | - |  | 1 |  |
| TestForecastHonesty.test_low_hp_caps_favored | 5 | - |  | 1 | 'favored' at <=10 eff HP read as a guarantee (t12/t16 deaths). |
| TestForecastHonesty.test_estimate_carries_tilde_and_age | 5 | - |  | 1 |  |
| TestForecastHonesty.test_close_and_behind_carry_marks_too | 5 | - |  | 1 |  |

## test_art.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestArtFetch.test_fetch_failure_negative_caches | 7 | mock |  | 2 | A 404 upstream is remembered — the browser re-requests images on |
| TestArtFetch.test_fetch_success_writes_cache | 17 | mock |  | 3 |  |

## test_art_extract.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestIdRegex.test_bg_card_ids_match | 6 | - |  | 1 |  |
| TestIdRegex.test_other_sets_rejected | 4 | - |  | 1 |  |

## test_board_state.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestHeldTrinkets.test_friendly_play_trinket_found | 11 | log |  | 2 |  |
| TestHeldTrinkets.test_other_zones_and_players_excluded | 12 | log |  | 1 |  |
| TestHeldTrinkets.test_placeholder_change_entity_becomes_the_trinket | 19 | log |  | 2 | The 2026-09-08 13:33 log's exact shape: BG30_Trinket_1st swaps to |
| TestDarkGifts.test_marker_name_and_host_link | 31 | log |  | 4 |  |
| TestDarkGifts.test_non_gift_tag_1234_ignored | 14 | log |  | 2 |  |
| TestHand.test_hand_carries_minions_and_spells | 20 | log |  | 2 | The hand is a coaching input (2026-09-04: five spells sat in hand |
| TestHand.test_cast_spell_leaves_the_hand | 16 | log |  | 2 | Casting moves the spell out of HAND — the hand (and the plan) |
| TestControllerLock.test_same_block_bracket_does_not_undo_controller | 9 | log |  | 1 |  |
| TestControllerLock.test_bracket_flip_without_controller_write_still_seeds | 8 | log |  | 2 |  |
| TestControllerLock.test_ghost_card_leaves_the_hand | 15 | log |  | 2 | Bought into hand, then moved to the other player: hand(friendly) |
| TestUpdatingForm.test_updating_block_targets_its_own_entity | 22 | log |  | 3 | A Tusked Camper (3/4) followed by a PTL Updating block of a *different* |
| TestUpdatingForm.test_updating_nested_brackets_empty_cardid | 8 | log |  | 1 | `[entityName=UNKNOWN ENTITY [cardType=INVALID] id=N ...] CardID=` must |
| TestUpdatingForm.test_updating_empty_cardid_keeps_existing_card | 8 | log |  | 1 |  |
| TestGolden.test_golden_minion_is_a_board_minion | 8 | - |  | 3 |  |
| TestGolden.test_recreated_golden_not_corrupted_by_following_updating_blocks | 18 | - |  | 4 | Snow Baller repro: a re-created minion followed by PTL Updating blocks |
| TestBareEntityTagChanges.test_bare_zone_play_empties_hand | 9 | log |  | 3 |  |
| TestBareEntityTagChanges.test_numeric_entity_not_swallowed_by_account_branch | 11 | log |  | 2 |  |
| TestBareEntityTagChanges.test_damage_cap_on_numeric_gameentity | 7 | log |  | 1 |  |
| TestBareEntityTagChanges.test_bare_entity_retargets_continuation_lines | 12 | log |  | 1 |  |
| TestShowEntityBracketed.test_continuation_tags_land_on_revealed_entity | 17 | log |  | 5 |  |
| TestHandPositionZeroExit.test_position_zero_clears_hand | 10 | log |  | 2 |  |
| TestHandPositionZeroExit.test_real_hand_card_at_position_one_stays | 10 | log |  | 2 |  |

## test_card_meta.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestCardMetaMap.test_minion_and_spell_tier_in_map | 6 | dict | coach_ui | 4 |  |
| TestCardMetaMap.test_golden_id_resolves_to_base | 4 | dict | coach_ui | 1 |  |
| TestCardMetaMap.test_hero_pick_row_gets_no_badge | 8 | dict | coach_ui | 1 |  |
| TestCardMetaMap.test_unknown_card_absent | 6 | dict | coach_ui | 1 |  |

## test_check_meta.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestCheckMeta.test_validator_passes_on_committed_meta | 5 | - | meta | 1 |  |
| TestCheckMeta.test_validator_catches_off_vocabulary_tribes | 29 | - | meta,tribes | 1 | Feed it a comps.json with the legacy plural vocabulary -> exit 1. |

## test_choices.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestChoiceParsing.test_trinket_block_kind_source_options | 5 | - |  | 3 |  |
| TestChoiceParsing.test_ptl_copies_skipped | 6 | - |  | 2 | PowerTaskList re-prints choices — counting them doubles options. |
| TestChoiceParsing.test_reprinted_options_deduped | 5 | - |  | 1 | The hero-selection screen re-prints the same option lines. |
| TestChoiceParsing.test_kind_detection_fallbacks | 6 | - |  | 3 |  |
| TestChoiceParsing.test_trinket_effect_discover_is_trinket | 27 | - |  | 4 | A trinket's EFFECT discover (Trip Vouchers, 2026-09-08 20:35 log): |
| TestChoiceParsing.test_unranked_options_still_score_none | 7 | - |  | 3 | Genuinely unknown picks keep their rows but stay unranked — the |
| TestRanking.test_heroes_ranked_by_pick_rate_with_power_text | 7 | - |  | 3 |  |
| TestRanking.test_unknown_hero_still_listed | 4 | - |  | 2 |  |
| TestRanking.test_locked_heroes_filtered_out | 8 | - |  | 1 | Season-pass-locked heroes (the player's list) never get recommended |
| TestRanking.test_trinkets_ranked_by_meta | 6 | - |  | 2 |  |
| TestRanking.test_unknown_trinket_still_listed | 4 | - |  | 2 |  |
| TestCuratedTrinkets.test_all_trinkets_annotated | 6 | - | meta | 2 |  |
| TestCuratedTrinkets.test_curated_synergy_fits_the_board | 9 | - |  | 2 |  |
| TestCuratedTrinkets.test_curated_tribe_synergy | 7 | - |  | 1 |  |
| TestCuratedTrinkets.test_discover_prefers_comp_core | 12 | - |  | 2 |  |
| TestCuratedTrinkets.test_discover_labels_key_on_the_displayed_comp | 34 | - |  | 4 | The 2026-09-11 report: Lurking Leviathan (core of Beasts - |
| TestCuratedTrinkets.test_discover_without_a_direction_makes_no_comp_claim | 11 | - | live | 2 | No displayed target -> no comp wording at all; the top option is |
| TestLiveWiring.test_pending_choice_tracked_and_resolved | 9 | log |  | 4 |  |
| TestLiveWiring.test_ptl_choice_lines_ignored | 5 | log |  | 1 |  |
| TestLiveWiring.test_sendchoices_still_counts_as_discover | 10 | log |  | 1 | The choice tracking must not swallow SendChoices from the action |

## test_decision_log.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestDecisionLog.test_advise_records_with_join_keys | 13 | log,real-log | decision_log,live | 8 |  |
| TestDecisionLog.test_unchanged_state_not_recorded | 5 | log | live | 1 | The fingerprint dedup gates the record — one line, not one per poll. |
| TestDecisionLog.test_pick_advice_recorded | 9 | log | live | 2 |  |
| TestDecisionLog.test_never_raises_on_bad_target | 4 | - | decision_log | 0 |  |
| TestDecisionLog.test_game_counter_bumps_per_game | 5 | log |  | 2 |  |

## test_engine_recipes.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestRecipeTables.test_recipe_exists_and_mechanical | 9 | - | meta | 6 |  |
| TestRecipeTables.test_hero_power_text_quotes_match_heroes_db | 13 | - | meta | 2 | A patch that rewords a hero power must flag the stale semantics |
| TestActivation.test_hero_plus_trinket_activates | 3 | - |  | 1 |  |
| TestActivation.test_trinket_matched_by_db_id_or_name | 7 | - |  | 2 |  |
| TestActivation.test_wrong_hero_no_activation | 2 | - |  | 1 |  |
| TestActivation.test_missing_trinket_no_activation | 5 | - |  | 2 |  |
| TestActivation.test_plain_string_trinkets_accepted | 4 | - |  | 1 |  |
| TestActivation.test_observed_confidence_never_activates | 4 | - |  | 1 | Observed rows sit inert until corpus data justifies them. |
| TestFuelHit.test_battlecry_text_hits | 4 | - | meta | 1 |  |
| TestFuelHit.test_non_battlecry_misses | 6 | - | meta | 3 |  |
| TestPlayTime.test_shop_boost_is_exactly_the_recipe_boost | 7 | - |  | 1 |  |
| TestPlayTime.test_shop_boost_applies_to_golden_variant | 6 | - |  | 1 |  |
| TestPlayTime.test_other_cards_untouched | 12 | - | value | 1 |  |
| TestPlayTime.test_buy_intention_names_the_engine | 5 | - |  | 1 |  |
| TestPlayTime.test_comp_core_outranks_recipe_fuel | 6 | - |  | 1 |  |
| TestPickTime.test_recipe_term_on_required_trinket | 8 | - |  | 2 |  |
| TestPickTime.test_no_term_for_other_hero | 4 | - |  | 1 |  |
| TestPickTime.test_synergy_capped_at_syn_cap | 11 | - |  | 3 | Board fit + recipe term together still add at most SYN_CAP. |
| TestPickTime.test_rank_choices_passes_hero_through | 6 | - | choices | 1 |  |
| TestCompNudge.test_trinket_tips_equal_evidence | 4 | - |  | 1 |  |
| TestCompNudge.test_no_trinket_no_flip | 3 | - |  | 1 |  |
| TestCompNudge.test_nudge_never_manufactures_direction | 6 | - |  | 1 | No core hits anywhere -> still no direction (modulates, never |
| TestCompNudge.test_progress_rows_carry_fit_but_ready_needs_two_hits | 16 | - |  | 4 |  |
| TestHeldTrinketResolution.test_log_id_resolves_directly | 16 | log | meta,refresh_trinkets | 3 |  |
| TestHeldTrinketResolution.test_unknown_cid_resolves_by_bracket_name | 8 | - | meta | 1 | The bracket-name fallback stays for cids the DB doesn't know — |
| TestHeldTrinketResolution.test_exact_id_still_resolves | 7 | - | meta | 1 |  |
| TestHeldTrinketResolution.test_unknown_trinket_dropped_not_crashed | 5 | - |  | 1 |  |

## test_extract_board.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestExtractBoard.test_duplicates_preserved_and_noise_excluded | 7 | - |  | 2 |  |
| TestExtractBoard.test_removed_minion_not_reported | 6 | - |  | 3 |  |
| TestExtractBoard.test_noise_tail_digits_normalized | 5 | - |  | 3 |  |

## test_friendly_player.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestChoiceSignal.test_choice_option_line_captures_player | 4 | - |  | 2 |  |
| TestChoiceSignal.test_choice_header_not_matched | 4 | - |  | 1 |  |
| TestChoiceSignal.test_extract_game_returns_choice_players | 3 | - |  | 1 |  |
| TestChoiceSignal.test_choice_wins_while_heroes_are_lone_opponent | 7 | - |  | 1 | The live misfire, in miniature: the hero pick printed (player 8) |
| TestChoiceSignal.test_choice_beats_a_wrongly_split_counter | 9 | - |  | 1 | Even a materialized split defers to the choice signal: opponents |
| TestHeuristicFallback.test_no_choices_unsplit_returns_none | 8 | - |  | 1 | THE regression: old code returned the lone player (16) and the |
| TestHeuristicFallback.test_no_choices_tied_split_returns_none | 7 | - |  | 1 | Two bracket ids at one hero each: the 1-vs-7 shape hasn't |
| TestHeuristicFallback.test_no_choices_full_split_names_friendly | 14 | - |  | 1 | The original 1-vs-7 contract on a complete parse: 7 opponents |
| TestHeuristicFallback.test_no_heroes_no_choices_returns_none | 2 | - |  | 1 |  |
| TestHeuristicFallback.test_ambiguous_choices_fall_through_to_heuristic | 15 | - |  | 1 | Two distinct bracket numbers on choice lines can't happen in a |
| TestLiveLockContract.test_choices_alone_do_not_lock | 5 | - |  | 3 |  |
| TestLiveLockContract.test_hero_placement_completes_the_lock | 7 | - |  | 3 |  |
| TestLiveLockContract.test_wrong_player_hero_still_waits | 9 | - |  | 2 | An opponent hero spawning first (the morning misfire's shape) |
| TestLiveLockContract.test_late_lock_drains_pending_hero_stats | 17 | log | coach,live_coach | 3 | Armor/health writes that arrived before the lock are buffered in |
| TestRealLog.test_incremental_lock_matches_full_parse | 34 | - |  | 1 | On every game of the newest real session, the friendly player the |

## test_fuel_tag.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestButcheringFuelTag.test_safe_undead_tagged_as_fuel | 8 | dict | coach_ui | 2 |  |
| TestButcheringFuelTag.test_no_butchering_no_fuel_tag | 4 | dict | coach_ui | 1 |  |
| TestButcheringFuelTag.test_keep_group_not_tagged | 7 | dict | coach_ui | 1 |  |

## test_hand_engine.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestSellParsesAtPhaseEnd.test_end_of_phase_drag_sell_counts_once | 6 | - | player_actions | 3 |  |
| TestSellParsesAtPhaseEnd.test_mid_phase_sell_not_double_counted | 9 | - | player_actions | 1 |  |
| TestHandChargeKit.test_hold_while_deployer_lives | 7 | - | value | 3 |  |
| TestHandChargeKit.test_hold_with_full_board_names_the_blocker | 5 | - | value | 2 |  |
| TestHandChargeKit.test_play_once_the_deployer_is_gone | 5 | - | value | 2 |  |
| TestHandChargeKit.test_golden_pairing_still_wins | 6 | - | value | 1 |  |
| TestHandChargeKit.test_hand_engine_status | 9 | - | value | 4 |  |
| TestSellReason.test_categories | 25 | - | value | 7 |  |
| TestShopWantsTheDeployer.test_deployer_boosted_when_charger_in_hand | 7 | - | value | 1 |  |
| TestRenderCarriesEngineAndReasons.test_render_json | 10 | dict | coach_ui | 4 |  |

## test_integration_real_log.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestRealLog.test_turn_one_advises_when_monitor_started_before_game | 33 | log | coach,live,live_coach | 3 | Regression: a game that starts while live.py is already running |
| TestRealLog.test_turns_and_board_are_plausible | 23 | log | coach,live_coach | 2 |  |

## test_live_updates.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestStateFingerprint.test_none_before_hero_parsed | 2 | - |  | 1 |  |
| TestStateFingerprint.test_gold_change_changes_fingerprint | 9 | log |  | 1 | A buy spends gold — the fingerprint must notice (affordability). |
| TestStateFingerprint.test_shop_change_changes_fingerprint | 13 | log |  | 2 | After a roll the shop loses an offer — the advice must re-run. |
| TestStateFingerprint.test_picking_changes_fingerprint | 11 | - |  | 1 | Resolving a pick changes no gold/board/shop — without the choice |
| TestStateFingerprint.test_scout_change_changes_fingerprint | 8 | log |  | 1 | A newly announced next opponent changes what the advice says. |
| TestStateFingerprint.test_hand_change_changes_fingerprint | 10 | log |  | 1 | A spell bought into hand (or cast out) changes the plan without |
| TestGoldSpending.test_spent_gold_is_subtracted | 8 | log |  | 2 | Gold = RESOURCES - RESOURCES_USED. The purse alone made mid-turn |
| TestGoldSpending.test_fingerprint_notices_spending | 8 | log |  | 1 |  |
| TestLevelCost.test_live_button_cost_wins | 6 | log |  | 1 | The TechUp button's COST tag is the authoritative upgrade price. |
| TestLevelCost.test_death_writes_and_zero_costs_ignored | 12 | log |  | 1 | Teardown writes (COST 0, or after the button left PLAY) must not |
| TestLevelCost.test_turn1_button_costs_5 | 7 | - |  | 1 | Turn 1: the tier-2 button costs 5 (3 gold cannot level — the old |
| TestLevelCost.test_price_drops_per_turn_at_tier | 6 | - |  | 1 | Wiki rule: tier+5 minus turns at the tier (2nd turn: 4). |
| TestLevelCost.test_top_move_uses_real_cost | 10 | - | value | 2 | Turn 1 (gold 3, button 5): no impossible LEVEL step at all — an |
| TestLevelVsBoard.test_dying_hero_buys_instead_of_levels | 5 | dict |  | 2 |  |
| TestLevelVsBoard.test_core_card_beats_level | 5 | dict |  | 2 |  |
| TestLevelVsBoard.test_level_still_leads_when_both_fit | 7 | dict |  | 2 | Healthy, no core pick, and the leftover covers the top card: |
| TestLevelVsBoard.test_level_leads_when_healthy_and_no_core | 4 | dict |  | 1 |  |
| TestLevelGates.test_payoff_next_tier_reason | 11 | dict | value | 1 | A comp piece the player needs sits at tier+1: the level states |
| TestLevelGates.test_needs_here_stays_and_buys | 11 | dict | value | 3 | The comp's missing pieces are ON the current tier: leveling would |
| TestLevelGates.test_loss_streak_defers_level_with_reason | 8 | dict |  | 3 | Two straight real losses and the level + top card can't both fit: |
| TestLevelGates.test_single_real_loss_defers_with_reason | 5 | dict |  | 2 |  |
| TestLevelGates.test_early_game_losses_do_not_flip | 5 | dict |  | 1 | Tiers 1-2 are shop-driven (Jeef): early losses don't gate levels. |
| TestLevelGates.test_flip_reason_carries_scout_numbers | 6 | dict |  | 1 |  |
| TestLevelGates.test_strong_board_converts_to_level | 8 | dict |  | 1 | Shadybunny's Q0: already winning — strength converts into a |
| TestLevelGates.test_token_loss_does_not_flip | 6 | dict |  | 1 | A close 2-damage loss with no streak is no tempo alarm (tier 2 is |
| TestLevelGates.test_close_losses_still_flip | 9 | dict |  | 2 | Any damage is a loss (a won combat never drops health+armor): the |
| TestLevelGates.test_curve_prior_names_itself | 4 | dict |  | 1 |  |
| TestLevelGates.test_addon_next_tier_does_not_defeat_core_here_stay | 17 | dict | value | 2 | A missing CORE on the current tier outranks a lone ADDON at |
| TestLevelGates.test_lower_tier_core_counts_as_here | 11 | dict | value | 2 | A tier-3 core while at tier 4: leveling dilutes sub-tier pool |
| TestLevelGates.test_more_next_cores_than_here_levels | 12 | dict | value | 1 | The comp's missing cores live mostly one tier up: LEVEL states |
| TestLevelGates.test_unranked_pick_never_blessed | 11 | dict | value | 1 | An unranked pick (no data — score None) gets no 'PICK X' step: |
| TestArmorFlow.test_damage_last_and_streak | 21 | log |  | 5 |  |
| TestArmorFlow.test_armor_gain_is_not_a_loss | 15 | log |  | 2 |  |
| TestOpponentScout.test_combat_board_mapped_to_announced_opponent | 20 | log |  | 6 |  |
| TestOpponentScout.test_unfought_next_opponent_falls_back | 10 | log |  | 3 |  |
| TestOpponentScout.test_deaths_snapshot_the_fought_board | 20 | log |  | 1 | The fullest view of the board we faced wins: combat deaths |
| TestOpponentScout.test_turn_not_resolved_before_its_fight | 21 | log |  | 3 | A turn is only resolved once its fight is over: during the turn's |
| TestOpponentScout.test_teardown_remnants_never_committed | 39 | log |  | 3 | The remnants of the previous fight are torn down during the next |
| TestBoardFallback.test_empty_board_falls_back_to_snapshot | 16 | - |  | 1 | A full-board turn's combat teardown leaves the log's PLAY board |
| TestBoardFallback.test_real_board_beats_snapshot | 15 | log |  | 1 | When the live PLAY board exists it is used (no snapshot ghosting). |
| TestBoardEstimate.test_fullest_snapshot_wins | 8 | - | coach,live_coach | 1 |  |
| TestBoardEstimate.test_remnant_only_when_nothing_fresher | 4 | - | live_coach | 1 |  |
| TestBoardEstimate.test_empty_snapshots | 3 | - | live_coach | 1 |  |
| TestStickyBanGate.test_removed_comp_releases_the_direction | 23 | log |  | 1 |  |
| TestStickyBanGate.test_still_playable_comp_holds | 20 | log |  | 1 |  |
| TestBuyStep.test_unaffordable_headline_walks_down | 9 | dict |  | 3 | Gold 7, level 5 (budget 2), headline minion costs 3: the plan buys |
| TestBuyStep.test_nothing_affordable_after_level_is_silence | 9 | dict |  | 4 | Gold 5, level 5 (budget 0): the level spent everything — no |
| TestBuyStep.test_impossible_level_not_recommended | 9 | dict |  | 2 | Gold 6 with the level costing 7: the upgrade is out of reach this |
| TestBuyStep.test_zero_gold_passes | 9 | dict |  | 4 | Gold 0, nothing affordable, level out of reach: pass, not a |
| TestBuyEvidence.test_buy_is_tracked | 15 | log |  | 3 |  |
| TestBuyEvidence.test_hand_reentry_not_double_counted | 10 | log |  | 1 | The bracket re-prints zone=HAND on every sibling write — only the |
| TestBanGate.test_partial_pool_reveal_fails_open | 20 | mock | coach,live_coach | 4 | One tribe's pool minions seen (allowed=[Beast]) is NOT ban info — |
| TestBanGate.test_detection_window_lists_confirmed_tribes_only | 37 | mock | coach,live_coach | 8 | The pool reveals stream in with the shop rolls (5/5 lands turn |
| TestBanGate.test_detection_window_empty_confirmed_set_hides_all | 26 | mock | coach,live_coach | 5 | Early window (0/5 confirmed — with the 3-distinct-card gate this |
| TestBanGate.test_complete_ban_set_locks | 16 | mock | coach,live_coach | 4 |  |
| TestBanGate.test_bans_resolve_when_hero_parsed_first | 25 | mock | coach,live_coach | 1 | The pool streams after the hero parses; _ensure_meta returns early |
| TestManualBans.test_manual_set_is_authoritative | 12 | - | coach,coach_ui | 6 |  |
| TestManualBans.test_manual_beats_earlier_inference_lock | 14 | - | coach,coach_ui | 2 | The inference locked 5/5 first (pool streamed fast), THEN the |
| TestManualBans.test_changing_the_taps_reapplies | 11 | - | coach,coach_ui | 2 |  |
| TestManualBans.test_clearing_reopens_detection | 11 | - | coach,coach_ui | 4 |  |
| TestManualBans.test_store_validates_against_the_roster | 7 | - | coach,coach_ui | 4 |  |
| TestManualBans.test_reset_with_the_game | 11 | - | coach,coach_ui | 3 | bans_manual rides _GAME_DEFAULTS: a new game resets it (the tap |
| TestRenderJsonComps.test_playable_comps_become_rich_tier_rows | 28 | dict | coach_ui | 7 | The comps panel needs more than names: each playable comp row |
| TestRenderJsonComps.test_playable_comps_no_ban_info_keeps_all | 11 | dict | coach_ui | 2 | A comp without _blocked_core marks nothing banned — unknown ban |
| TestRenderJsonComps.test_game_comps_preferred_tribe_flag_rides | 28 | dict | coach_ui | 4 | The panel renders game_comps (the live coach's game-level list) |
| TestRenderJsonComps.test_tribes_detecting_rides_the_payload | 15 | dict | coach_ui | 3 | During the detection window the comps panel labels its |
| TestRenderJsonComps.test_comp_progress_raw_needs_do_not_crash_render | 19 | dict | coach_ui,value | 2 | The comp meter's RAW rows carry needs as bare card-id strings |
| TestRenderJsonComps.test_sell_rank_groups_duplicates | 12 | dict | coach_ui | 3 | Two board copies of one card showed as two confusing rows; they |
| TestRenderJsonComps.test_sell_row_excludes_hand_minions | 15 | dict | coach_ui | 1 | A hand minion can't be sold — it has to be played first |
| TestRenderJsonComps.test_shop_rows_carry_tavern_prices | 18 | dict | coach_ui | 3 | Prices are invisible in the UI, so a wrong one ("thinks minions |
| TestRenderJsonComps.test_unpriced_cards_carry_no_price | 6 | dict | coach_ui | 1 |  |
| TestGameStateTable.test_reset_restores_fresh_state | 10 | - | live_coach | 1 |  |

## test_lobby.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestScout.test_staged_burst_resolves_to_opp_board | 11 | - |  | 2 |  |
| TestScout.test_subtracts_our_holdings | 11 | - |  | 1 |  |
| TestScout.test_golden_weights_three_and_flags | 11 | - |  | 3 |  |
| TestScout.test_round_scoping_no_recount | 11 | - |  | 1 |  |
| TestScout.test_unstaged_turn_resolves_nothing | 5 | - |  | 1 |  |
| TestScout.test_seat_tag_names_and_fights | 10 | log |  | 1 |  |
| TestScout.test_shop_offers_and_summons_excluded | 12 | - |  | 1 |  |
| TestScout.test_final_duel_stages_opponent_only | 8 | - |  | 1 |  |
| TestConsumers.test_merged_holdings_fresh_only | 4 | - |  | 2 |  |
| TestConsumers.test_fresh_seats_age_window | 4 | - |  | 3 |  |
| TestConsumers.test_committed_uses_tribe_membership | 17 | log | lobby | 3 |  |
| TestConsumers.test_committed_unknown_tribe_is_silent | 3 | - |  | 1 |  |

## test_locked_hand.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestLockedHandCards.test_hand_flags_locked_card | 7 | log |  | 2 |  |
| TestLockedHandCards.test_unlock_tag_clears_the_lock | 9 | log |  | 1 | LITERALLY_UNPLAYABLE value=0 (the 60-gold payoff) unlocks. |
| TestLockedHandCards.test_hand_plan_excludes_locked_cards | 8 | log |  | 1 | A locked card can't be played or cast — the plan must not advise |
| TestLockedHandCards.test_unlocked_card_returns_to_the_plan | 11 | log |  | 2 | An unlocked known card is planned again (BG34_950 itself isn't in |

## test_package_corpus.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestPackage.test_bundle_contains_both_and_no_tags | 17 | real-log | package_corpus | 9 |  |
| TestPackage.test_no_decision_log_still_packages | 7 | real-log | decision_log,package_corpus | 1 |  |

## test_patch_notes.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestDuplicateNames.test_duplicate_name_is_ambiguous_not_wrongly_applied | 7 | - |  | 2 |  |
| TestDuplicateNames.test_ambiguous_reports_distinguishing_descriptions | 10 | - |  | 3 | Dark gifts have no tier field; the report must show the descriptions |
| TestDuplicateNames.test_unique_name_still_applies | 7 | - |  | 1 |  |

## test_player_actions_sells.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestMagneticPlaysAreNotSells.test_magnetic_attach_is_not_a_sell | 9 | - |  | 3 | Prosthetic Hand (BG_DEEP_015, MAGNETIC) played onto a mech leaves |
| TestMagneticPlaysAreNotSells.test_non_magnetic_leaver_still_counts | 8 | - |  | 2 | The backstop must keep catching real sells: a played non-magnetic |
| TestMagneticPlaysAreNotSells.test_magnetic_sold_via_drag_to_sell_still_counts | 11 | - |  | 2 | A magnetic minion actually sold still goes through the Drag To Sell |

## test_pool.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestOwnHoldings.test_regular_is_one_copy | 3 | - | pool | 1 |  |
| TestOwnHoldings.test_golden_flag_counts_three | 3 | - | pool | 1 |  |
| TestOwnHoldings.test_golden_id_suffix_counts_three | 3 | - | pool | 1 |  |
| TestOwnHoldings.test_hand_holds_too | 4 | - | pool | 1 |  |
| TestOwnHoldings.test_duplicates_accumulate | 3 | - | pool | 1 |  |
| TestLeft.test_pool_minus_holdings | 3 | - | pool | 1 |  |
| TestLeft.test_clamps_at_zero | 3 | - | pool | 1 |  |
| TestLeft.test_unknown_tier_is_no_opinion | 2 | - | pool | 1 |  |
| TestLeft.test_sizes_override | 2 | - | pool | 1 |  |
| TestLeft.test_meta_pool_sizes_accessor | 4 | - | meta | 2 |  |
| TestChip.test_dry | 2 | - | pool | 1 |  |
| TestChip.test_last_copy | 2 | - | pool | 1 |  |
| TestChip.test_count_left | 3 | - | pool | 1 |  |
| TestChip.test_unknown_tier_no_chip | 2 | - | pool | 1 |  |
| TestHandPlanPoolGate.test_hold_when_pool_can_produce | 8 | - | value | 2 |  |
| TestHandPlanPoolGate.test_play_when_pool_dry | 11 | - | pool,value | 2 |  |
| TestHandPlanPoolGate.test_no_pool_arg_keeps_hold | 6 | - | value | 1 |  |
| TestTripleNotePool.test_golden_needs_more_pool_short | 7 | - | value | 2 |  |
| TestTripleNotePool.test_golden_pool_can_produce_untouched | 5 | - | value | 2 |  |
| TestTripleNotePool.test_completing_buy_unaffected | 5 | - | value | 1 |  |
| TestHuntPoolGate.test_pool_dry_blocks_hunt | 6 | - | value | 2 |  |
| TestHuntPoolGate.test_pool_available_hunts_on | 5 | - | value | 2 |  |
| TestHuntPoolGate.test_no_pool_arg_unchanged | 3 | - | value | 1 |  |

## test_reachability.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestTables.test_every_source_is_mechanical_with_a_name | 8 | - | meta | 3 |  |
| TestTables.test_source_ids_exist_in_the_dbs | 16 | - | meta | 2 |  |
| TestTables.test_fuel_specs_reference_real_minions_with_known_tribe | 9 | - | meta | 4 |  |
| TestLiveSources.test_board_hand_trinket_and_hero | 10 | - |  | 1 |  |
| TestLiveSources.test_same_card_on_board_and_in_hand_is_one_source | 4 | - |  | 1 |  |
| TestLiveSources.test_unheld_cards_produce_nothing | 3 | - |  | 1 |  |
| TestHuntReachability.test_tier_gate_blocks_unreachable_above_piece | 4 | - |  | 2 |  |
| TestHuntReachability.test_discover_source_passes_the_tier_gate | 4 | - |  | 2 |  |
| TestHuntReachability.test_random_generate_never_passes_any_gate | 5 | - |  | 2 |  |
| TestHuntReachability.test_token_generator_passes_for_its_grant_only | 10 | - |  | 3 |  |
| TestHuntReachability.test_discover_bypasses_a_dry_pool | 7 | - |  | 3 |  |
| TestHuntReachability.test_recency_still_applies_when_reachable | 5 | - |  | 2 |  |
| TestHuntReachability.test_tier_cap_resolutions | 9 | - |  | 3 |  |
| TestHuntReachability.test_weak_hit_needs_the_tribe | 3 | - |  | 2 |  |
| TestHuntReachability.test_weak_mention_footnote | 4 | - |  | 2 |  |
| TestQ1Exception.test_unreachable_above_piece_vetoes_the_stay | 3 | - |  | 1 |  |
| TestQ1Exception.test_discover_reachable_above_piece_does_not_veto | 4 | - |  | 1 |  |
| TestQ1Exception.test_random_reachable_above_piece_still_vetoes | 4 | - |  | 1 |  |
| TestFuelLine.test_fires_with_engine_on_board_and_idle_gold | 7 | - |  | 3 |  |
| TestFuelLine.test_minion_body_outranks_costlier_spell | 6 | - |  | 1 |  |
| TestFuelLine.test_gates | 10 | - |  | 5 |  |

## test_roll_vs_level.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestFuelRollMode.test_live_engine_at_tempo_fires | 4 | dict |  | 2 |  |
| TestFuelRollMode.test_tier_floor | 3 | dict |  | 2 |  |
| TestFuelRollMode.test_stabilize_gates | 5 | dict |  | 4 |  |
| TestFuelRollMode.test_no_engine_no_mode | 2 | dict |  | 1 |  |
| TestFuelRollMode.test_far_from_complete_stays_level | 7 | dict |  | 1 |  |
| TestFuelRollMode.test_near_complete_passes_and_engine_covers_no_target | 9 | dict |  | 2 |  |
| TestHuntFeasible.test_no_target_no_hunt | 4 | - |  | 2 |  |
| TestHuntFeasible.test_missing_cores_are_evaluated | 10 | - |  | 2 |  |
| TestHuntFeasible.test_owned_cores_not_evaluated | 8 | - |  | 1 |  |

## test_sanitize.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestSanitizeText.test_battletags_replaced_with_stable_placeholders | 11 | - |  | 5 |  |
| TestSanitizeText.test_non_tag_hashes_untouched | 5 | - |  | 1 | Card ids / game text with # don't exist, but a near-miss (short |
| TestSanitizeText.test_placeholder_parsing_survives | 11 | log | coach,live,live_coach | 1 | The live coach must parse a sanitized log identically (names are |
| TestSanitizeText.test_real_log_fully_redacted | 13 | - |  | 1 | Integration (local logs): after sanitizing, zero BattleTag |

## test_scrape_comps_diff.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestDiffComp.test_no_changes_reports_empty | 2 | - |  | 1 |  |
| TestDiffComp.test_tier_move | 4 | - |  | 1 |  |
| TestDiffComp.test_core_swap_uses_card_names | 4 | - |  | 1 |  |
| TestDiffComp.test_unknown_ids_fall_back_to_raw_id | 4 | - |  | 1 |  |
| TestDiffComp.test_text_fields_report_length_only | 4 | - |  | 1 |  |
| TestDiffComp.test_representative_change | 4 | - |  | 1 |  |
| TestLoadCardNames.test_loads_real_minions_meta | 3 | - |  | 1 |  |
| TestLoadCardNames.test_missing_file_returns_empty_map | 2 | - |  | 1 |  |

## test_shop_costs.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestCostCapture.test_creation_block_carries_cost | 8 | - |  | 2 |  |
| TestCostCapture.test_minion_dict_carries_cost | 6 | - |  | 1 |  |
| TestCostCapture.test_tag_change_updates_cost | 8 | - |  | 1 |  |
| TestCostCapture.test_named_cost_tag_also_captured | 5 | - |  | 1 |  |
| TestShopCostMap.test_offer_priced_from_log | 5 | - |  | 1 |  |
| TestShopCostMap.test_unpriced_card_absent | 4 | - |  | 1 |  |
| TestShopCostMap.test_later_entity_wins | 7 | - |  | 1 |  |
| TestShopCostMap.test_golden_maps_both_ids | 4 | - |  | 1 |  |
| TestTopMoveAffordability.test_minion_costs_flat_three | 8 | dict | value | 3 |  |
| TestTopMoveAffordability.test_minion_affordable_at_three | 5 | dict | value | 2 |  |
| TestTopMoveAffordability.test_spell_log_cost_decides | 9 | dict | value | 1 |  |
| TestTopMoveAffordability.test_spell_fallback_walk_uses_log_costs | 12 | dict | value | 1 |  |
| TestShopCostMapEntityExact.test_offer_entity_beats_later_same_card_write | 13 | - | live_coach | 1 |  |
| TestShopCostMapEntityExact.test_cid_scan_fallback_without_eids | 8 | - | live_coach | 1 |  |

## test_shop_parsing.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestShopParsing.test_tavern_offers_exclude_own_minions_and_buttons | 10 | log |  | 1 |  |
| TestShopParsing.test_latest_block_wins | 14 | log |  | 1 | Options re-print after every event; the shop is the most recent |
| TestShopParsing.test_fired_advice_uses_current_shop | 9 | log | live | 1 | The live.py fire condition (pending + tavern_offers) must not fire |
| TestShopParsing.test_discovery_block_does_not_replace_shop | 19 | log |  | 2 | A Murloc Holmes discovery block (2026-09-05) offered the shop's own |

## test_simulate_growth.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestMechsMagnetics.test_standard_chain_hand_computed | 7 | - |  | 2 |  |
| TestMechsMagnetics.test_balinda_doubles_the_trigger | 7 | - |  | 2 |  |
| TestMechsMagnetics.test_golden_balinda_triples_the_trigger | 6 | - |  | 2 |  |
| TestMechsMagnetics.test_drakkari_doubles_the_end_of_turn_step | 6 | - |  | 1 |  |
| TestMechsMagnetics.test_golden_glambot_doubles_its_buff | 9 | - |  | 2 |  |
| TestMechsMagnetics.test_no_drone_no_downstream_gain | 4 | - |  | 1 |  |
| TestMechsMagnetics.test_copper_coil_fires_only_with_the_trinket | 10 | - |  | 2 |  |
| TestMechsMagnetics.test_zero_trigger_zero_gain | 3 | - |  | 1 |  |
| TestElementalsCompounding.test_tribe_scope_step_hand_computed | 9 | - |  | 1 |  |
| TestElementalsCompounding.test_nomi_buffs_the_eaten_tavern_minions | 7 | - |  | 1 |  |
| TestElementalsCompounding.test_golden_nomi_doubles_the_shop_buff | 6 | - |  | 1 |  |
| TestElementalsCompounding.test_cumulative_defaults_to_primary_when_absent | 5 | - |  | 1 |  |
| TestElementalsCompounding.test_enforcer_absent_no_compounding | 6 | - |  | 1 |  |
| TestTribeScaling.test_cumulative_count_used | 5 | - |  | 1 |  |
| TestTribeScaling.test_attack_proxy_fallback | 4 | - |  | 1 |  |
| TestTribeScaling.test_no_source_no_gain | 4 | - |  | 1 |  |

## test_spells.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestSpellEffect.test_choose_one_takes_best_branch_not_sum | 4 | - |  | 1 | '+3/+1; or +1/+3' resolves ONE branch — 4 stat points, not 8. |
| TestSpellEffect.test_plain_buff_counts_both_stats | 2 | - |  | 1 |  |
| TestSpellEffect.test_board_wide_scope_scales_with_board_size | 5 | - |  | 2 |  |
| TestSpellEffect.test_scaling_text_is_worth_more | 5 | - |  | 1 |  |
| TestSpellEffect.test_cost_efficiency | 5 | - |  | 1 | The same effect at cost 1 outscores cost 5. |
| TestSpellEffect.test_gold_grants_score | 10 | - |  | 3 | Economy spells (player-flagged 2026-09-08: Overconfidence, the |
| TestCuratedSpells.test_all_spells_annotated | 5 | - | value | 1 |  |
| TestCuratedSpells.test_annotated_spell_scores_from_the_curated_read | 5 | - | value | 1 |  |
| TestCuratedSpells.test_choose_one_takes_the_max_branch | 5 | - | value | 2 |  |
| TestCuratedSpells.test_board_scope_scales_with_the_board | 4 | - | value | 2 |  |
| TestCuratedSpells.test_golden_making_and_set_stats | 5 | - | value | 2 |  |
| TestCuratedSpells.test_regex_fallback_for_unannotated_spells | 3 | - |  | 1 |  |
| TestCastGeneratingSpells.test_spitescale_generates_three_casts | 4 | - |  | 1 |  |
| TestCastGeneratingSpells.test_word_number_parsed | 3 | - |  | 1 |  |
| TestCastGeneratingSpells.test_plain_spell_generates_nothing | 2 | - |  | 1 |  |
| TestCastGeneratingSpells.test_fuel_counts_generated_casts | 9 | - |  | 1 | With a running cast engine, the spellcraft spell's fuel delta is |
| TestCastGeneratingSpells.test_generated_fuel_lifts_the_score | 10 | - |  | 1 |  |
| TestSpellFuel.test_fuel_fires_on_a_cast_spell_engine | 5 | - |  | 1 |  |
| TestSpellFuel.test_no_fuel_without_the_engine | 3 | - |  | 1 |  |
| TestSpellFuel.test_no_fuel_with_no_board | 2 | - |  | 1 |  |
| TestSpellFuel.test_fuel_boosts_a_spell_score | 8 | - | value | 1 |  |
| TestShopRankingSpells.test_spell_ranked_alongside_minions | 4 | - |  | 1 |  |
| TestShopRankingSpells.test_unknown_ids_still_skipped_silently | 4 | - |  | 1 |  |
| TestShopRankingSpells.test_engine_board_ranks_spell_above_plain_body | 9 | - |  | 1 | A running Glambot makes ANY spell worth more than a filler body — |
| TestTopMoveSpells.test_buy_spell_line_and_intention | 4 | dict |  | 2 |  |
| TestTopMoveSpells.test_cannot_afford_spell_falls_back | 5 | dict |  | 3 |  |
| TestTopMoveSpells.test_turn1_prefers_affordable_minion_over_spell | 13 | dict | value | 2 | 2026-09-04 live note: turn 1 recommended a spell over a minion — |
| TestTopMoveSpells.test_spell_still_wins_after_turn2 | 11 | dict | value | 1 | The early-game rule is scoped to turns 1-2: after that the ranked |
| TestGrowthCalibration.test_one_shot_battlecry_discounted | 5 | - | value | 1 |  |
| TestGrowthCalibration.test_repeating_trigger_keeps_full_magnitude | 4 | - | value | 1 |  |
| TestGrowthCalibration.test_committed_comp_damps_off_tribe_shop_cards | 16 | - | value | 2 | Same off-tribe card, committed vs not committed: delta is exactly |
| TestGrowthCalibration.test_neutral_cards_not_growth_discounted | 16 | - | value | 1 |  |
| TestTopMovePriority.test_steps_are_numbered_and_level_leads | 5 | dict |  | 1 |  |
| TestTopMovePriority.test_minion_costs_flat_three | 12 | dict | value | 3 | Minions cost a FLAT 3 for all tiers (2026-09-06, player-confirmed; |
| TestTopMovePriority.test_buy_budgeted_from_leftover_after_leveling | 13 | dict | value | 3 | When leveling leads, buys must fit the LEFTOVER gold, not the purse: |
| TestCompCards.test_pivot_override_follows_recent_buys | 13 | - | value | 1 | The board is backward-looking: two old Naga cores among a mixed |
| TestCompCards.test_no_pivot_on_one_recent_core | 5 | - | value | 1 |  |
| TestCompCards.test_board_dominant_commit_holds_on_a_tie | 14 | - | value | 1 | A deep single-tribe board is the commitment: 2 incidental recent |
| TestCompCards.test_same_comp_recent_buys_not_a_pivot | 7 | - | value | 1 | Buying more Naga cores stays committed to Nagas (no flip-flop). |
| TestCompCards.test_no_board_commit_uses_recent_buys | 5 | - | value | 1 | An empty board pivots to whatever the player just bought, too. |
| TestCompCards.test_owned_flags_and_names | 11 | - | value | 5 |  |
| TestCompCards.test_no_target_returns_none | 2 | - | value | 1 |  |

## test_tribe_lookup.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestScanFile.test_captures_reveals | 7 | - |  | 1 |  |
| TestScanFile.test_interleaved_components_both_captured | 12 | - |  | 1 |  |
| TestScanFile.test_compound_multiple_race_tags | 9 | - |  | 1 |  |
| TestScanFile.test_run_ends_at_non_tag_line | 14 | - |  | 1 |  |
| TestScanFile.test_hidden_entities_skipped | 10 | - |  | 1 |  |
| TestRefreshTribes.test_union_not_log_wins | 9 | - |  | 3 |  |
| TestRefreshTribes.test_override_beats_everything | 7 | - |  | 2 |  |
| TestRefreshTribes.test_amalgam_from_log | 5 | - |  | 1 |  |
| TestRefreshTribes.test_conflicting_sources_keep_log_and_report | 6 | - |  | 2 |  |
| TestRefreshTribes.test_paste_value_kept_when_no_source_knows | 7 | - |  | 4 |  |
| TestRefreshTribes.test_unknown_listed_for_curation | 7 | - |  | 3 |  |
| TestParseCompoundAware.test_compound | 4 | - |  | 2 |  |
| TestParseCompoundAware.test_amalgam | 2 | - |  | 1 |  |
| TestParseCompoundAware.test_untribed | 4 | - |  | 2 |  |

## test_tribes.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestNormalize.test_raw_log_values | 4 | - |  | 3 |  |
| TestNormalize.test_already_canonical_is_idempotent | 3 | - |  | 1 |  |
| TestNormalize.test_legacy_plural_forms | 5 | - |  | 3 |  |
| TestNormalize.test_compound | 4 | - |  | 3 |  |
| TestNormalize.test_never_banned_markers_and_none | 7 | - |  | 6 |  |
| TestCanon.test_mech_special_case | 2 | - |  | 1 |  |
| TestCanon.test_round_trip_over_all_tribes | 3 | - |  | 1 |  |
| TestCanon.test_all_tribes_map_to_display | 3 | - |  | 1 |  |
| TestIsBanned.test_allowed_tribe_not_banned | 3 | - |  | 2 |  |
| TestIsBanned.test_banned_tribe | 2 | - |  | 1 |  |
| TestIsBanned.test_compound_either_half_allowed | 3 | - |  | 2 |  |
| TestIsBanned.test_fail_open_on_unknown_and_no_info | 4 | - |  | 3 |  |
| TestTribeBanKillsComps.test_banned_tribe_drops_all_its_comps | 6 | - |  | 1 |  |
| TestTribeBanKillsComps.test_hybrid_comp_survives_with_blocked_pieces | 9 | - |  | 3 |  |
| TestBansFromLogCardRace.test_log_native_races_reveal_tribes_without_cache | 24 | log | bans | 7 |  |
| TestBansFromLogCardRace.test_cache_fallback_for_blocks_without_race_tag | 13 | log | bans | 2 |  |
| TestBansFromLogGenerationLeaks.test_partial_reveal_pending_not_banned | 15 | log | bans | 3 | One tribe below the gate (2 distinct cards): allowed AND banned |
| TestBansFromLogGenerationLeaks.test_singleton_leak_does_not_become_allowed | 5 | log | bans | 0 |  |
| TestBansFromLogGenerationLeaks.test_two_card_leak_also_ignored | 7 | log | bans | 1 |  |
| TestBansFromLogGenerationLeaks.test_three_distinct_cards_make_a_tribe | 7 | log | bans | 1 |  |
| TestBansFromLogGenerationLeaks.test_repeat_copies_do_not_pad_the_count | 8 | log | bans | 1 |  |
| TestTribesFromRaces.test_single_race | 3 | - |  | 2 |  |
| TestTribesFromRaces.test_compound_preserved | 5 | - |  | 1 |  |
| TestTribesFromRaces.test_all_marker_not_collapsed | 4 | - |  | 2 |  |
| TestTribesFromRaces.test_empty_and_neutral | 4 | - |  | 3 |  |
| TestParts.test_all_expands_to_every_tribe | 2 | - |  | 1 |  |
| TestParts.test_compound_splits | 2 | - |  | 1 |  |
| TestParts.test_raw_and_canonical | 3 | - |  | 2 |  |
| TestParts.test_untribed_matches_nothing | 3 | - |  | 2 |  |
| TestMatches.test_compound_membership | 4 | - |  | 3 |  |
| TestMatches.test_amalgam_matches_everything | 3 | - |  | 1 |  |
| TestMatches.test_untribed_matches_nothing | 3 | - |  | 2 |  |
| TestMatches.test_raw_forms_accepted_on_both_sides | 3 | - |  | 2 |  |
| TestOverlaps.test_compound_vs_compound_shared_part | 3 | - |  | 2 |  |
| TestOverlaps.test_amalgam_overlaps_any_tribed_field | 4 | - |  | 3 |  |
| TestOverlaps.test_untribed_overlaps_nothing | 4 | - |  | 3 |  |
| TestOverlaps.test_is_the_w_tribe_fit_test | 4 | - |  | 1 |  |

## test_trinket_meta.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestLogIdAddressing.test_reno_game_trinkets_present_by_log_id | 9 | - | meta | 3 | The two trinkets of the 2026-09-16 win, pinned by log id. |
| TestLogIdAddressing.test_sous_chef_under_log_id | 6 | - | meta | 2 | The original drift case: log printed BG35_MagicItem_801, the |
| TestLogIdAddressing.test_flaming_portrait_annotated_as_elemental | 7 | - | meta | 2 | The pick ranker's synergy term must see the Enforcer amp as an |
| TestOfferedCoverage.test_all_offered_trinkets_in_db | 21 | real-log | meta | 1 |  |

## test_turn_counting.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestParseActions.test_ptl_step_duplicates_do_not_spawn_turns | 19 | - |  | 2 | GameState and PowerTaskList both log tag=STEP; the PTL MAIN_ACTION |
| TestParseActions.test_first_main_action_is_a_real_buy_phase | 7 | - |  | 2 | In Battlegrounds the first MAIN_ACTION has a full shop; a turn-1 buy |
| TestParseActions.test_turn_1_pass_is_kept_numbering_stable | 7 | - |  | 2 |  |
| TestLiveActions.test_ptl_steps_ignored_and_first_turn_counted | 10 | log |  | 1 |  |
| TestLiveActions.test_full_game_shape | 10 | log |  | 1 | Three buy phases + interleaved PTL copies -> 3 turns, not 5-6. |

## test_upload_corpus.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestUpload.test_put_file_builds_contents_api_body | 26 | mock |  | 4 |  |
| TestUpload.test_upload_uses_default_repo_and_streams_the_file | 6 | mock |  | 2 |  |
| TestUpload.test_repo_env_override | 7 | mock |  | 1 |  |
| TestUpload.test_token_env_passed_through | 7 | mock |  | 1 |  |

## test_value.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestBestComp.test_matches_board_tribes_not_dict_order | 3 | - |  | 1 |  |
| TestBestComp.test_no_fit_returns_none | 3 | - |  | 1 |  |
| TestBestComp.test_legacy_plural_comps_still_match | 5 | - |  | 1 |  |
| TestWTribe.test_w_tribe_fires_for_matching_comp | 9 | - | value | 2 |  |
| TestWTribe.test_traditionally_failing_legacy_comp_tribe | 8 | - | value | 1 | A comp still carrying the legacy plural must still get the bonus |
| TestBannedPenalty.test_penalty_only_for_actually_banned_tribes | 7 | - |  | 1 | Same minion, two games: Beast allowed vs Beast banned. Delta is |
| TestBannedPenalty.test_no_penalty_without_ban_info | 7 | - |  | 1 | allowed_tribes=None (= no ban data) must not penalize anyone — the |
| TestBannedPenalty.test_compound_tribe_playable_if_either_half_allowed | 5 | - |  | 1 |  |
| TestNoEvidenceNoComp.test_no_evidence_no_comp | 4 | - | value | 1 |  |
| TestNoEvidenceNoComp.test_one_board_core_is_not_a_commit | 3 | - | value | 1 |  |
| TestNoEvidenceNoComp.test_board_copies_commit | 5 | - | value | 1 | 2x one core is a commit (copies count, same as a pivot). |
| TestNoEvidenceNoComp.test_board_plus_recent_hits_commit | 9 | - | value | 1 | One core on the board + a DIFFERENT one among recent acquisitions |
| TestNoEvidenceNoComp.test_same_card_in_board_and_recent_is_one_hit | 8 | - | value | 1 | 2026-09-18 regression: one Tasty Lobster bought then played sat in |
| TestNoEvidenceNoComp.test_tribe_evidence_across_comps | 15 | - | value | 2 | A build straddling two comps of one tribe (2026-09-04 beasts game: |
| TestCompProgress.test_no_evidence_no_rows | 4 | - | value | 1 |  |
| TestCompProgress.test_one_hit_is_visible_but_not_ready | 9 | - | value | 3 | The pre-commit blind spot: 1 core hit is not a commit, but the |
| TestCompProgress.test_two_hits_ready_and_needs_exclude_owned | 12 | - | value | 3 |  |
| TestCompProgress.test_recent_hits_count | 5 | - | value | 1 |  |
| TestCompProgress.test_sorted_by_hits_then_meta_tier | 8 | - | value | 1 |  |
| TestCompProgress.test_tribe_signal_annotates_rows | 23 | - | value | 4 | Tribe evidence spread across comps (1 + 1 hits, one tribe) — |
| TestActivations.test_activation_parsed | 4 | - | value | 2 |  |
| TestActivations.test_activation_beats_useless_reroll | 11 | - | value | 2 | 1 gold, everything in the shop costs 3, a usable activation on |
| TestActivations.test_unaffordable_activation_still_rolls | 10 | - | value | 2 |  |
| TestActivations.test_live_capture | 39 | log | live_coach | 2 | The friendly's usable activation rides the settled options block; |
| TestCommittedMaximizes.test_missing_core_outranks_a_strong_generic | 10 | - | value | 1 |  |
| TestCommittedMaximizes.test_missing_core_outscores_dupe_by_the_completion_gap | 18 | - | value | 1 | Equal-raw core cards: the missing one (+14) outscores the dupe |
| TestSharedUtilityCores.test_balinda_does_not_manufacture_direction | 9 | - | value | 2 |  |
| TestSharedUtilityCores.test_specific_cores_still_commit | 5 | - | value | 1 |  |
| TestSharedUtilityCores.test_shared_card_stays_in_shopping_list | 6 | - | value | 2 |  |
| TestRollHunt.test_off_build_buy_becomes_a_hunt | 6 | dict | value | 2 |  |
| TestRollHunt.test_comp_piece_still_buys | 7 | dict | value | 2 |  |
| TestRollHunt.test_dying_buys_a_body | 3 | dict | value | 1 |  |
| TestRollHunt.test_no_hunt_without_missing_core | 5 | dict | value | 1 |  |
| TestRollHunt.test_hunt_names_specific_cores_first | 16 | dict | value | 2 | A shared-utility card (Balinda) is still on the shopping list, |
| TestRollHunt.test_hunt_skips_core_above_the_tavern | 8 | dict | value | 2 | A tier-6 core at tavern 5 can't be bought at all — the old plan |
| TestRollHunt.test_hunt_paused_when_core_gone_cold | 12 | dict | value | 2 | The Morchie t9-t19 pattern: the tier-3 Gem Rat hunted from a |
| TestRollHunt.test_hunt_fires_on_recent_sighting | 11 | dict | value | 2 | A below-tavern core the shop IS showing stays huntable — evidence |
| TestRollHunt.test_never_shown_core_is_not_hunted | 9 | dict | value | 2 | Tracked session, core never offered: the strongest don't-hunt |
| TestRollHunt.test_untracked_analysis_keeps_the_legacy_hunt | 6 | dict | value | 1 | No shop_seen key (older callers): no recency gate — but the tier |
| TestSkipTurnHero.test_turn1_pass_names_the_hero | 8 | - | value | 3 |  |
| TestSkipTurnHero.test_other_heroes_keep_a_turn1_plan | 7 | - | value | 1 |  |
| TestSkipTurnHero.test_gate_is_turn1_only | 7 | - | value | 1 |  |
| TestTrinketSynergy.test_curated_tribe_record_hits | 14 | - | value | 2 |  |
| TestTrinketSynergy.test_curated_keyword_record_hits | 10 | - | value | 1 |  |
| TestTrinketSynergy.test_string_fallback_substring | 10 | - | value | 1 |  |
| TestShopGolden.test_golden_shop_offer_is_ranked_not_dropped | 3 | - | value | 1 |  |
| TestShopGolden.test_golden_scores_golden_body_plus_reward | 6 | - | value | 1 |  |
| TestShopGolden.test_golden_outranks_missing_core | 8 | - | value | 1 |  |
| TestShopGolden.test_golden_priced_flat_three | 3 | - | value | 1 |  |
| TestShopGolden.test_top_move_buys_a_golden_at_three | 6 | - | value | 2 |  |
| TestCombatForecast.test_favored_with_edges | 8 | - | value | 3 |  |
| TestCombatForecast.test_close_and_behind | 7 | - | value | 3 |  |
| TestCombatForecast.test_none_without_opponent | 3 | - | value | 1 |  |
| TestStrengthGapLevelGate.test_losing_and_far_behind_buys_stats | 7 | dict | value | 3 |  |
| TestStrengthGapLevelGate.test_losing_but_on_curve_levels | 4 | dict | value | 1 |  |
| TestStrengthGapLevelGate.test_tier1_stays_curve_driven | 4 | dict | value | 1 |  |
| TestQ1StayGate.test_tie_between_here_and_next_cores_levels | 8 | dict | value | 2 |  |
| TestQ1StayGate.test_core_beyond_next_tier_vetoes_stay | 7 | dict | value | 1 |  |
| TestQ1StayGate.test_all_missing_cores_here_stays | 7 | dict | value | 1 |  |
| TestButcheringTargets.test_casts_capped_at_board_undead | 6 | - | value | 1 |  |
| TestButcheringTargets.test_no_targets_no_casts | 3 | - | value | 1 |  |
| TestButcheringTargets.test_why_says_reborn_first | 3 | - | value | 1 |  |
| TestButcheringTargets.test_no_reborn_names_generators | 8 | - | value | 1 | With no Reborn targets, the why points at the comp page's |
| TestSituationLine.test_zero_armor_mortality | 9 | - | value | 3 |  |
| TestSituationLine.test_dying_overrides | 6 | - | value | 2 |  |
| TestSituationLine.test_damage_cap_bands | 13 | - | value | 2 | This season caps per-combat damage (BACON_COMBAT_DAMAGE_CAP, |
| TestSituationLine.test_quiet_when_nothing_to_say | 5 | - | value | 1 |  |
| TestSituationLine.test_never_won_alarm_subsumes_streak | 11 | - | value | 3 | 2026-09-19 Reno game: bled in every fight from t2 and died 8th — |
| TestSituationLine.test_never_won_needs_three_turns | 6 | - | value | 1 | One lost fight is just a loss — the alarm needs a sample. |
| TestStickyCompTarget.test_same_tribe_sticks | 4 | - | value | 1 |  |
| TestStickyCompTarget.test_more_evidence_switches | 4 | - | value | 1 |  |
| TestStickyCompTarget.test_cross_tribe_pivot_always_passes | 4 | - | value | 1 |  |
| TestStickyCompTarget.test_subthreshold_dip_holds | 7 | - | value | 1 | No new target anywhere, the previous comp still has 1 core hit — |
| TestStickyCompTarget.test_zero_evidence_drops_the_direction | 3 | - | value | 1 |  |
| TestUndeadEngine.test_butchering_growth | 14 | - | simulate_growth | 2 |  |
| TestUndeadEngine.test_engine_pieces_credited | 12 | - | value | 2 |  |
| TestUndeadEngine.test_best_engine_picked_on_undead_board | 8 | - | value | 1 |  |
| TestEngineFit.test_off_dominant_engine_damped | 16 | - | value | 3 |  |
| TestEngineFit.test_tribe_engine_undamped_on_its_board | 12 | - | value | 1 |  |
| TestEngineFit.test_precommit_off_tribe_growth_damped | 20 | - | value | 1 | No target yet, but the board is already one tribe: an off-tribe |
| TestEngineFit.test_precommit_untribed_growth_exempt | 17 | - | value | 2 | Untribed cards fit any build — no pre-commit damp, on any board. |
| TestCombatOnlyGains.test_lobster_is_not_a_growth_engine | 11 | - | value | 4 |  |
| TestCombatOnlyGains.test_during_combat_gain_is_combat_only | 5 | - | value | 2 |  |
| TestCombatOnlyGains.test_explicit_expiry_markers | 5 | - | value | 2 |  |
| TestCombatOnlyGains.test_overrides_for_deceptive_prose | 11 | - | value | 4 |  |
| TestCombatOnlyGains.test_persist_markers_keep_growth | 9 | - | value | 4 |  |
| TestCombatOnlyGains.test_persistent_halves_keep_their_terms | 6 | - | value | 2 |  |
| TestCombatOnlyGains.test_summons_from_combat_triggers_still_grow | 6 | - | value | 2 |  |
| TestCombatOnlyGains.test_deathrattle_stat_buff_vs_tavern_refresh | 10 | - | value | 4 |  |
| TestCombatOnlyGains.test_self_improving_combat_engines | 21 | - | value | 6 |  |
| TestCombatOnlyGains.test_self_improving_label | 6 | - | value | 2 |  |
| TestCombatOnlyGains.test_rally_and_attack_triggers_are_combat_only | 17 | - | value | 1 |  |
| TestCombatOnlyGains.test_rally_permanent_wording_still_persists | 5 | - | value | 1 |  |
| TestCombatOnlyGains.test_hand_targeted_gains_persist | 13 | - | value | 4 |  |
| TestCombatOnlyGains.test_dual_phase_snazzy_phantom_keeps_engine_status | 7 | - | value | 2 |  |
| TestCombatOnlyGains.test_flat_text_marker_across_line_wraps | 7 | - | value | 2 |  |
| TestBlockedCore.test_comp_cards_marks_banned | 11 | - | value | 4 |  |
| TestBlockedCore.test_progress_needs_exclude_blocked | 7 | - | value | 1 |  |
| TestHandPlan.test_casts_and_plays_carry_verbs | 9 | - | value | 4 |  |
| TestHandPlan.test_engine_fuel_boosts_a_cast | 12 | - | value | 2 | A running cast-spell engine turns every cast into compounding |
| TestHandPlan.test_unknown_spell_skipped | 4 | - | value | 1 | Generated spell entities without a real id can't be advised. |
| TestHandPlan.test_make_room_never_sells_a_held_card | 15 | - | value | 2 | One plan, one direction (2026-09-06 Guff t12): the hand said |
| TestHandPlan.test_triple_awareness | 14 | - | value | 4 | 2 on board: the hand copy IS the triple — play now. 1 on board: |
| TestHandPlan.test_triple_play_outranks_a_bigger_free_play | 7 | - | value | 1 |  |
| TestHandPlan.test_triple_awareness_ignores_a_board_golden | 13 | - | value | 2 | A golden on board is NOT one of the three copies — goldens |
| TestHandPlan.test_a_golden_hand_copy_never_triples | 17 | - | value | 4 | A golden is terminal: playing it is a golden-body play, never |
| TestBuyIntentionTriple.test_golden_on_board_does_not_count | 6 | - | value | 2 |  |
| TestBuyIntentionTriple.test_two_regulars_the_buy_completes | 4 | - | value | 1 |  |
| TestBuyIntentionTriple.test_no_copies_no_note | 4 | - | value | 1 |  |
| TestTopMoveHand.test_hand_casts_lead_the_plan | 6 | dict | value | 2 |  |
| TestTopMoveHand.test_copies_group_and_rest_summarize | 10 | dict | value | 3 |  |
| TestTopMoveHand.test_more_than_three_kinds_summarize | 5 | dict | value | 1 |  |
| TestTopMoveHand.test_hand_minion_on_full_board_says_make_room | 6 | dict | value | 1 |  |
| TestTopMoveHand.test_wait_for_end_of_turn_casts_first | 11 | dict | value | 2 | End-of-turn compounding counts casts made THIS turn — the hand |
| TestTopMoveHand.test_committed_endgame_says_scale | 11 | dict | value | 2 | Once committed the endgame is enriching what we have (2026-09-04: |
| TestTavernBuffWaste.test_held_when_the_plan_buys_nothing | 12 | - | value | 4 |  |
| TestTavernBuffWaste.test_cast_kept_and_warned_with_a_minion_buy | 12 | - | value | 3 |  |
| TestTavernBuffWaste.test_recurring_tavern_buffs_are_exempt | 8 | - | value | 4 | Refresh-scaling tavern spells re-apply on future refreshes — a |
| TestTavernBuffWaste.test_shop_buff_buy_swapped_for_an_affordable_minion | 13 | - | value | 2 | Buying Them Apples out of the shop with no room for a minion |
| TestTavernBuffWaste.test_shop_buff_buy_with_no_minion_fits_rolls | 11 | - | value | 2 |  |
| TestMultiplierProtect.test_balinda_is_recognized_as_a_multiplier | 3 | - | value | 1 |  |
| TestMultiplierProtect.test_spellcraft_generators_are_scaling | 4 | - | value | 1 |  |
| TestMultiplierProtect.test_glue_never_ranks_safest | 12 | - | value | 5 |  |
| TestCompFilteredBuy.test_no_evidence_no_arbitrary_comp_bonus | 6 | - | value | 1 |  |
| TestCompFilteredBuy.test_recent_evidence_blesses_only_that_comp | 11 | - | value | 2 |  |
| TestTribeLookups.test_compound_minion_fits_either_half | 11 | - | value | 2 |  |
| TestTribeLookups.test_amalgam_fits_every_comp | 7 | - | value | 1 |  |
| TestTribeLookups.test_engine_membership_by_db_tribe | 11 | - | value | 1 |  |
| TestTribeLookups.test_untribed_engine_still_matches_via_text | 11 | - | value | 1 |  |
| TestTribeLookups.test_non_tribed_non_engine_gets_no_engine_bonus | 7 | - |  | 1 |  |
| TestTribeLookups.test_sell_reason_compound_not_off_comp | 10 | - |  | 2 |  |
| TestCoreHitsNoDoubleCount.test_bought_and_played_counts_once | 4 | - |  | 1 |  |
| TestCoreHitsNoDoubleCount.test_second_copy_in_hand_still_counts | 4 | - |  | 1 |  |
| TestCoreHitsNoDoubleCount.test_two_copies_in_hand_no_board | 3 | - |  | 1 |  |
| TestCoreHitsNoDoubleCount.test_ambiguous_single_counts_are_conservative | 9 | - |  | 1 | board=1 + rc=1 can mean 'the same copy' (1 physical) or 'an old |

## test_zone_shop.py

| test | LOC | fixture | pins | A# | docstring |
|---|---|---|---|---|---|
| TestZoneShop.test_roll_reveals_offer_without_options_block | 15 | log |  | 1 | A mid-phase re-roll: the new generation's entity writes land with |
| TestZoneShop.test_buy_midphase_keeps_remaining_offers | 11 | log |  | 1 | A buy used to blank the shop until the next options block (which |
| TestZoneShop.test_removed_write_prunes | 9 | log |  | 1 | A re-rolled-away offer leaves via ZONE REMOVEDFROMGAME. |
| TestZoneShop.test_tavern_spell_offer_tracked | 9 | log |  | 1 | Tavern spells carry HAS_DRAG_TO_BUY too (BG28_888 = Misplaced Tea |
| TestZoneShop.test_sell_options_never_become_offers | 15 | log |  | 3 | Storm blocks list the player's own minions (sell options) and |
| TestZoneShop.test_phase_start_rebuilds_fresh_table | 11 | log |  | 1 | A new buy phase clears the zone table; the phase's options block |
| TestZoneShop.test_midphase_offer_changes_fingerprint | 16 | log |  | 2 | The monitor re-advises when the decision state changes — a mid-roll |
| TestZoneShop.test_shop_sightings_recorded | 25 | log | value | 3 | Every shop generation feeds the hunt's evidence |
