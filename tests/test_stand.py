"""Ошибки приёмки не должны выглядеть как готовый настоящий стенд."""
import json
import unittest
from unittest.mock import MagicMock, patch

import stand


class StandReadinessTests(unittest.TestCase):
    def test_only_known_ready_statuses_are_accepted(self):
        for status, ready in [("ok", True), ("degraded", True), ("loading", False),
                              ("failed", False), (None, False), ("unexpected", False),
                              ([], False), ({}, False)]:
            with self.subTest(status=status):
                service = stand.Service("ИИ", [], "http://127.0.0.1/health", "test.log")
                with patch.object(stand, "http_get", return_value=(200, json.dumps({"status": status}).encode())), \
                     patch.object(stand, "say"):
                    self.assertEqual(service.ready(), ready)

    def test_missing_ai_does_not_silently_start_stub(self):
        with patch("sys.argv", ["stand.py"]), patch.object(stand, "AI_RUN") as path, \
             patch.object(stand, "Service") as service, patch.object(stand, "say"):
            path.exists.return_value = False
            self.assertEqual(stand.main(), 1)
            service.assert_not_called()

    def run_mock_stand(self, argv, check_code=0):
        service = MagicMock()
        service.status = "ok"
        with patch("sys.argv", ["stand.py", *argv]), \
             patch.object(stand, "port_busy", return_value=False), \
             patch.object(stand, "ai_install_mode", return_value="full"), \
             patch.object(stand, "Service", return_value=service) as factory, \
             patch.object(stand, "wait_ready", return_value=True), \
             patch.object(stand, "http_get", return_value=(200, b'{"ai":{"status":"ok"}}')), \
             patch.object(stand, "banner"), patch.object(stand, "say"), \
             patch.object(stand.subprocess, "call", return_value=check_code), \
             patch.object(stand, "watch", return_value=0) as watch:
            result = stand.main()
        return result, factory, service, watch

    def test_real_start_overrides_inherited_stub_flag(self):
        with patch.dict("os.environ", {"AI_STUB": "1"}):
            result, factory, _, _ = self.run_mock_stand([])
        self.assertEqual(result, 0)
        self.assertEqual(factory.call_args_list[0].kwargs["env"]["AI_STUB"], "0")

    def test_failed_check_stops_services_and_returns_failure(self):
        result, _, service, watch = self.run_mock_stand(["--check"], check_code=1)
        self.assertEqual(result, 1)
        watch.assert_not_called()
        self.assertEqual(service.stop.call_count, 2)

    def test_explicit_stub_does_not_start_ai(self):
        result, factory, _, _ = self.run_mock_stand(["--stub"])
        self.assertEqual(result, 0)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(factory.call_args.kwargs["env"]["DEFFECTOR_AI_MODE"], "stub")


if __name__ == "__main__":
    unittest.main()
