import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge" / "mt5_bridge.py").read_text(encoding="utf-8")
EXECUTOR = (ROOT / "execution" / "trade_executor_primary_only.py").read_text(encoding="utf-8")


class BridgeSafetySourceTests(unittest.TestCase):
    def test_sources_compile(self):
        ast.parse(BRIDGE)
        ast.parse(EXECUTOR)

    def test_demo_guard_checks_mt5_account_mode(self):
        self.assertIn("def ensure_demo_account():", BRIDGE)
        self.assertIn('getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)', BRIDGE)
        self.assertIn('getattr(account, "trade_mode", None)', BRIDGE)
        self.assertIn("EXECUTION BLOCKED", BRIDGE)

    def test_all_state_changing_routes_call_demo_guard(self):
        tree = ast.parse(BRIDGE)
        routes = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators = [ast.unparse(d) for d in node.decorator_list]
                if any("/order" in d or "/position/modify" in d or "/position/close" in d
                       for d in decorators):
                    routes[node.name] = {n.func.id for n in ast.walk(node)
                                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertEqual(set(routes), {"place_order", "modify_position", "close_position"})
        for calls in routes.values():
            self.assertIn("ensure_demo_account", calls)

    def test_position_management_checks_magic_ownership(self):
        self.assertGreaterEqual(BRIDGE.count("Position ownership check failed"), 2)
        self.assertIn("magic: int = MAGIC", BRIDGE)

    def test_magic_number_is_consistent(self):
        self.assertIn("MAGIC = 260927", BRIDGE)
        self.assertIn("MAGIC = 260927", EXECUTOR)
        self.assertIn('"magic": int(magic)', EXECUTOR)

    def test_terminal_path_is_configurable(self):
        self.assertIn('os.getenv("MT5_TERMINAL_PATH") or None', BRIDGE)
        self.assertNotIn(r'C:\Users\pc\AppData\Roaming\MetaTrader 5\terminal64.exe', BRIDGE)

    def test_bridge_url_is_configurable(self):
        self.assertIn('os.getenv("MT5_BRIDGE_URL"', EXECUTOR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
