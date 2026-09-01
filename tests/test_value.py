"""Regression tests for the value function's tribe handling.

The historical bug: comps.json ("Elementals"), minions.json ("ELEMENTAL") and
bans.canon() ("Elemental") never intersected, so W_TRIBE never fired, the
banned-tribe penalty hit every minion, and _best_comp returned the first comp
in the file. These tests pin the corrected behavior.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value
from value import _best_comp, minion_value, sell_recommendation

EL = "BG33_886"   # Tusked Camper (Beast, t1) — present in the real BG pool
MECH = "BG29_503"  # a real mech in minions.json if present; tests skip if not


def _card(cid, atk=3, health=4):
    return value._load_card_db().get(cid) or {
        "name": cid, "race": "Beast", "attack": atk, "health": health,
        "mechanics": [], "text": "",
    }


class TestBestComp(unittest.TestCase):
    COMPS = {
        "mech-ladder": {"name": "Mech", "tribe": "Mech", "core": [], "addons": []},
        "beast-pack": {"name": "Beast", "tribe": "Beast", "core": [], "addons": []},
    }

    def test_matches_board_tribes_not_dict_order(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        self.assertIs(_best_comp(board, self.COMPS), self.COMPS["beast-pack"])

    def test_no_fit_returns_none(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": None}]
        self.assertIsNone(_best_comp(board, self.COMPS))

    def test_legacy_plural_comps_still_match(self):
        comps = {"beast-pack": {"name": "Beast", "tribe": "Beasts",
                                "core": [], "addons": []}}
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        self.assertIs(_best_comp(board, comps), comps["beast-pack"])


class TestWTribe(unittest.TestCase):
    def test_w_tribe_fires_for_matching_comp(self):
        m = {"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}
        card = _card(EL)
        base = minion_value(m, card, None)
        # Card NOT in the comp's core/addons: the only difference is W_TRIBE.
        same = minion_value(m, card, {"tribe": "Beast", "core": [], "addons": []})
        other = minion_value(m, card, {"tribe": "Mech", "core": [], "addons": []})
        self.assertEqual(same - base, value.W_TRIBE)
        self.assertEqual(other - base, 0.0)

    def test_traditionally_failing_legacy_comp_tribe(self):
        """A comp still carrying the legacy plural must still get the bonus
        (normalize handles it) — and the raw-log board minion matches it."""
        m = {"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}
        card = _card(EL)
        base = minion_value(m, card, None)
        legacy = minion_value(m, card, {"tribe": "Beasts", "core": [], "addons": []})
        self.assertEqual(legacy - base, value.W_TRIBE)


class TestBannedPenalty(unittest.TestCase):
    def test_penalty_only_for_actually_banned_tribes(self):
        """Same minion, two games: Beast allowed vs Beast banned. Delta is
        exactly the penalty."""
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        allowed = dict(sell_recommendation(board, [], allowed_tribes=["Beast"]))
        banned = dict(sell_recommendation(board, [], allowed_tribes=["Mech"]))
        self.assertEqual(banned[EL] - allowed[EL], -2.0)

    def test_no_penalty_without_ban_info(self):
        """allowed_tribes=None (= no ban data) must not penalize anyone — the
        old fail-closed behavior penalized every minion in every game."""
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        ranked = sell_recommendation(board, [], allowed_tribes=None)
        ranked_empty = sell_recommendation(board, [], allowed_tribes=[])
        self.assertEqual(ranked, ranked_empty)

    def test_compound_tribe_playable_if_either_half_allowed(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "DEMON/BEAST"}]
        penalized = dict(sell_recommendation(board, [], allowed_tribes=["Mech"]))
        clean = dict(sell_recommendation(board, [], allowed_tribes=["Beast"]))
        self.assertEqual(penalized[EL] - clean[EL], -2.0)


if __name__ == "__main__":
    unittest.main()

class TestCorpusBonus(unittest.TestCase):
    def _with_corpus(self, stats):
        import json
        import tempfile
        old_path, old_cache = value._CORPUS_PATH, value._CORPUS
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"comps": stats}, tmp)
        tmp.close()
        value._CORPUS_PATH = tmp.name
        value._CORPUS = None
        return lambda: (setattr(value, "_CORPUS_PATH", old_path),
                        setattr(value, "_CORPUS", old_cache),
                        os.unlink(tmp.name))

    def test_large_sample_can_beat_meta_tier(self):
        comps = {"weak": {"name": "Weak", "meta_tier": "B", "core": [], "addons": []},
                 "meta": {"name": "Meta", "meta_tier": "A", "core": [], "addons": []}}
        undo = self._with_corpus({"Weak": {"games": 20, "avg_place": 2.0},
                                  "Meta": {"games": 20, "avg_place": 6.0}})
        try:
            self.assertIs(value.comp_target([], comps), comps["weak"])
        finally:
            undo()

    def test_single_game_barely_moves_the_pick(self):
        """n=1 must not flip a tier decision — shrinkage n/(n+3)."""
        comps = {"a": {"name": "A", "meta_tier": "A", "core": [], "addons": []},
                 "b": {"name": "B", "meta_tier": "B", "core": [], "addons": []}}
        undo = self._with_corpus({"B": {"games": 1, "avg_place": 1.0}})
        try:
            self.assertIs(value.comp_target([], comps), comps["a"])
        finally:
            undo()

    def test_missing_corpus_is_neutral(self):
        comps = {"a": {"name": "A", "meta_tier": "A", "core": [], "addons": []},
                 "b": {"name": "B", "meta_tier": "B", "core": [], "addons": []}}
        undo = self._with_corpus({})
        try:
            self.assertIs(value.comp_target([], comps), comps["a"])
        finally:
            undo()
