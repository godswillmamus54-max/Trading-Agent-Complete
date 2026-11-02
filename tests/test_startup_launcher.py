
import os
import unittest
from unittest.mock import Mock, patch

import requests

import start_trading_agent as launcher


class LauncherConfigurationTests(unittest.TestCase):

    @patch.object(launcher, "load_dotenv")
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_is_rejected(self, mock_load):
        with self.assertRaisesRegex(RuntimeError, "MT5_BRIDGE_API_KEY"):
            launcher.validate_configuration()

    @patch.object(launcher, "load_dotenv")
    @patch.dict(
        os.environ,
        {"MT5_BRIDGE_API_KEY": "REPLACE_WITH_TEST_SECRET"},
        clear=True,
    )
    def test_placeholder_api_key_is_rejected(self, mock_load):
        with self.assertRaisesRegex(RuntimeError, "placeholder"):
            launcher.validate_configuration()

    @patch.object(launcher, "load_dotenv")
    @patch.dict(
        os.environ,
        {
            "MT5_BRIDGE_API_KEY": "test-secret",
            "MT5_BRIDGE_URL": "https://example.com:8000",
        },
        clear=True,
    )
    def test_external_bridge_url_is_rejected(self, mock_load):
        with self.assertRaisesRegex(RuntimeError, "local bridge"):
            launcher.validate_configuration()

    @patch.object(launcher, "load_dotenv")
    @patch.dict(
        os.environ,
        {
            "MT5_BRIDGE_API_KEY": "test-secret",
            "MT5_BRIDGE_URL": "http://127.0.0.1:8000",
        },
        clear=True,
    )
    def test_local_bridge_url_is_accepted(self, mock_load):
        api_key, bridge_url = launcher.validate_configuration()

        self.assertEqual(api_key, "test-secret")
        self.assertEqual(bridge_url, "http://127.0.0.1:8000")


class LauncherBridgeVerificationTests(unittest.TestCase):

    def setUp(self):
        self.process = Mock()
        self.process.poll.return_value = None

        self.health_response = Mock()
        self.health_response.json.return_value = {
            "status": "ok",
            "mt5_connected": True,
            "terminal_connected": True,
        }
        self.health_response.raise_for_status.return_value = None

        self.account = {
            "is_demo": True,
            "trade_allowed": True,
            "trade_expert": True,
            "login": 123456,
            "server": "Demo-Server",
            "balance": 1000.0,
        }

        self.account_response = Mock()
        self.account_response.json.return_value = self.account
        self.account_response.raise_for_status.return_value = None

    @patch.object(launcher.requests, "get")
    def test_verified_demo_account_is_accepted(self, mock_get):
        mock_get.side_effect = [
            self.health_response,
            self.account_response,
        ]

        result = launcher.verify_bridge(
            self.process,
            "test-secret",
            "http://127.0.0.1:8000",
        )

        self.assertEqual(result, self.account)
        self.assertEqual(mock_get.call_count, 2)

    @patch.object(launcher.requests, "get")
    def test_live_or_unverified_account_is_rejected(self, mock_get):
        self.account["is_demo"] = False
        mock_get.side_effect = [
            self.health_response,
            self.account_response,
        ]

        with self.assertRaisesRegex(RuntimeError, "not verified as DEMO"):
            launcher.verify_bridge(
                self.process,
                "test-secret",
                "http://127.0.0.1:8000",
            )

    @patch.object(launcher.requests, "get")
    def test_disabled_trading_permission_is_rejected(self, mock_get):
        self.account["trade_allowed"] = False
        mock_get.side_effect = [
            self.health_response,
            self.account_response,
        ]

        with self.assertRaisesRegex(RuntimeError, "does not currently permit"):
            launcher.verify_bridge(
                self.process,
                "test-secret",
                "http://127.0.0.1:8000",
            )

    @patch.object(launcher.requests, "get")
    def test_disabled_expert_permission_is_rejected(self, mock_get):
        self.account["trade_expert"] = False
        mock_get.side_effect = [
            self.health_response,
            self.account_response,
        ]

        with self.assertRaisesRegex(RuntimeError, "expert trading permission"):
            launcher.verify_bridge(
                self.process,
                "test-secret",
                "http://127.0.0.1:8000",
            )


if __name__ == "__main__":
    unittest.main()
