"""Roll-vs-level decision helpers (analysis/engine_coaching.md Plan 3).

Covers the roll-for-fuel dial's conservative gates (engine live on board,
tier >= 4, not dying/streak/heavy-hit, near-complete comp) and the shared
hunt-feasibility evaluation both the hunt block and the roll filler
(pieces mode / anti-roll) consume. The level-section wiring itself (the
lobby-pace anchor, the flip deferrals, the dual coaching output) is
validated end-to-end by validate_advice.py against the real 09-15 session.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from value import _fuel_roll_mode, _hunt_feasible

ENGINE_BOARD = [{"card": "BG36_352"}]  # Unbound Tempest (fuel spec)


def _analysis(**over):
    a = {
        "tier": 5, "board": ENGINE_BOARD, "health": 20, "armor": 0,
        "loss_streak": 0, "damage_last": None,
        "target_state": "committing", "target_cards": {"core": [], "addons": []},
    }
    a.update(over)
    return a


class TestFuelRollMode(unittest.TestCase):
    def test_live_engine_at_tempo_fires(self):
        spec = _fuel_roll_mode(_analysis())
        self.assertIsNotNone(spec)
        self.assertEqual(spec.get("fuel_tribe"), "Elemental")

    def test_tier_floor(self):
        self.assertIsNone(_fuel_roll_mode(_analysis(tier=3)))
        self.assertIsNotNone(_fuel_roll_mode(_analysis(tier=4)))

    def test_stabilize_gates(self):
        self.assertIsNone(_fuel_roll_mode(_analysis(health=10)))     # dying
        self.assertIsNone(_fuel_roll_mode(_analysis(loss_streak=1)))
        self.assertIsNone(_fuel_roll_mode(_analysis(damage_last=10)))
        self.assertIsNotNone(_fuel_roll_mode(_analysis(damage_last=9)))

    def test_no_engine_no_mode(self):
        self.assertIsNone(_fuel_roll_mode(_analysis(board=[{"card": "BGS_123"}])))

    def test_far_from_complete_stays_level(self):
        a = _analysis(target_cards={"core": [
            {"card": "BG36_352", "owned": False, "banned": False},
            {"card": "BG32_846", "owned": False, "banned": False},
            {"card": "BG31_843", "owned": False, "banned": False}],
            "addons": []})
        self.assertIsNone(_fuel_roll_mode(a))

    def test_near_complete_passes_and_engine_covers_no_target(self):
        near = _analysis(target_cards={"core": [
            {"card": "BG36_352", "owned": True, "banned": False},
            {"card": "BG32_846", "owned": False, "banned": False}],
            "addons": []})
        self.assertIsNotNone(_fuel_roll_mode(near))
        # a banned-tribe build has no targetable comp - the engine is the
        # direction (the 09-15 game-4 case)
        self.assertIsNotNone(_fuel_roll_mode(_analysis(target_state=None)))


class TestHuntFeasible(unittest.TestCase):
    def test_no_target_no_hunt(self):
        self.assertEqual(_hunt_feasible({"target_state": None}, 5), ([], []))
        self.assertEqual(_hunt_feasible({"target_state": "committing"}, None),
                         ([], []))

    def test_missing_cores_are_evaluated(self):
        a = {
            "target_state": "committing", "tier": 5, "turn": 10,
            "target_cards": {"core": [
                {"card": "BGS_115", "owned": False, "banned": False}],
                "addons": []},
        }
        feasible, evaluated = _hunt_feasible(a, 5)
        self.assertEqual(len(evaluated), 1)
        self.assertEqual([r["card"] for r in feasible], ["BGS_115"])

    def test_owned_cores_not_evaluated(self):
        a = {
            "target_state": "committing", "tier": 5, "turn": 10,
            "target_cards": {"core": [
                {"card": "BGS_115", "owned": True, "banned": False}],
                "addons": []},
        }
        self.assertEqual(_hunt_feasible(a, 5), ([], []))


if __name__ == "__main__":
    unittest.main()
