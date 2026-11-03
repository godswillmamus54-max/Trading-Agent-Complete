import ast
import unittest
from pathlib import Path
ROOT = Path.cwd()
BRIDGE = ROOT / "bridge" / "mt5_bridge.py"
ENGINE = ROOT / "engine" / "live_multi_state_machine_v28_5_2_primary_only_breakeven.py"
TEST_DIR = ROOT / "tests"
class ProfitProtectionFinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = BRIDGE.read_text(encoding="utf-8")
        cls.engine = ENGINE.read_text(encoding="utf-8")
        cls.bridge_tree = ast.parse(cls.bridge)
        cls.engine_tree = ast.parse(cls.engine)
    def function_source(self, tree, source, name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])
        self.fail(f"Function not found: {name}")
    def test_both_sources_parse(self):
        ast.parse(self.bridge)
        ast.parse(self.engine)
    def test_initial_stop_and_reward_ratio(self):
        self.assertIn("INITIAL_SL_DISTANCE = 10.0", self.engine)
        self.assertIn("RR_RATIO = 2.0", self.engine)
    def test_initial_buy_and_sell_stops(self):
        source = self.function_source(
            self.engine_tree, self.engine, "calculate_order"
        )
        self.assertIn("entry - INITIAL_SL_DISTANCE", source)
        self.assertIn("entry + INITIAL_SL_DISTANCE", source)
        self.assertIn("entry + risk_distance * RR_RATIO", source)
        self.assertIn("entry - risk_distance * RR_RATIO", source)
    def test_profit_protection_configuration(self):
        self.assertIn("PROFIT_LOCK_TARGET_USD = 3.0", self.engine)
        self.assertIn("PROFIT_PROTECTION_STEP = 5.0", self.engine)
    def test_profit_protection_has_buy_sell_logic(self):
        source = self.function_source(
            self.engine_tree, self.engine, "manage_open_positions"
        )
        self.assertIn('direction == "BUY"', source)
        self.assertIn("favorable_move // PROFIT_PROTECTION_STEP", source)
        self.assertIn("locked_distance", source)
    def test_profit_estimator_uses_mt5_calculation(self):
        source = self.function_source(
            self.bridge_tree, self.bridge, "position_profit_at_price"
        )
        self.assertIn("mt5.order_calc_profit", source)
        self.assertIn("estimated_net_profit", source)
        self.assertIn("estimate_only", source)
    def test_profit_estimator_checks_ownership_and_demo(self):
        source = self.function_source(
            self.bridge_tree, self.bridge, "position_profit_at_price"
        )
        self.assertIn("ensure_demo_account()", source)
        self.assertIn("Position ownership check failed", source)
    def test_commission_estimate_is_disclosed(self):
        source = self.function_source(
            self.bridge_tree, self.bridge, "position_profit_at_price"
        )
        self.assertIn("commission_data_observed", source)
        self.assertIn("estimated_round_turn_commission", source)
    def test_original_take_profit_is_preserved(self):
        source = self.function_source(
            self.engine_tree, self.engine, "manage_open_positions"
        )
        self.assertIn("candidate_sl", source)
        self.assertIn("current_tp", source)
        self.assertIn("candidate_sl", source)
        self.assertIn("result.get(\"observed_sl\")", source)
    def test_broker_readback_confirms_sl_and_tp(self):
        source = self.function_source(
            self.bridge_tree, self.bridge, "modify_position"
        )
        self.assertIn("observed_sl_check", source)
        self.assertIn("observed_tp_check", source)
        self.assertIn("if not sl_matches or not tp_matches", source)
    def test_broker_modification_checks_demo_and_ownership(self):
        source = self.function_source(
            self.bridge_tree, self.bridge, "modify_position"
        )
        self.assertIn("ensure_demo_account()", source)
        self.assertIn("Position ownership check failed", source)
    def test_h4_exit_is_preserved(self):
        source = self.function_source(
            self.engine_tree, self.engine, "manage_open_positions"
        )
        self.assertIn("trend_exit_confirmed", source)
        self.assertIn("close_position", source)
        self.assertIn("H4_TREND_EXIT", self.engine)
    def test_protection_does_not_loosen_sl(self):
        source = self.function_source(
            self.engine_tree, self.engine, "manage_open_positions"
        )
        self.assertIn("_is_more_protective", source)
    def test_engine_does_not_use_old_be_trailing_constants(self):
        for old_name in (
            "BE_TRIGGER_PRICE_PERCENT",
            "BE_TRIGGER_R",
            "TRAIL_TRIGGER_R",
            "BE_PLUS",
            "TRAIL_BUFFER",
        ):
            self.assertNotIn(old_name, self.engine)
    def test_existing_test_suite_is_discoverable(self):
        self.assertTrue(TEST_DIR.exists())
        self.assertTrue((TEST_DIR / "test_bridge_safety_source.py").exists())
        self.assertTrue((TEST_DIR / "test_startup_launcher.py").exists())
if __name__ == "__main__":
    unittest.main(verbosity=2)
