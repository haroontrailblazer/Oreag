"""The Render failover job must pick the right account and never flap."""
import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

import render_failover as rf

HEXRA = "https://oreag.onrender.com"
STANDBY = "https://oreag-tpsy.onrender.com"


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class ProbeTests(unittest.TestCase):
    def probe_with(self, status, headers=None):
        with patch.object(rf, "http", return_value=(status, headers or {}, "")):
            return rf.probe("https://x")

    def test_200_is_up(self):
        self.assertEqual(self.probe_with(200), "up")

    def test_render_suspension_is_recognised(self):
        self.assertEqual(
            self.probe_with(503, {"x-render-routing": "suspend-by-user"}), "suspended"
        )

    def test_other_503_is_only_down(self):
        self.assertEqual(self.probe_with(503, {"x-render-routing": "no-server"}), "down")

    def test_network_error_is_down(self):
        with patch.object(rf, "http", side_effect=TimeoutError()):
            self.assertEqual(rf.probe("https://x"), "down")


class PickBackendTests(unittest.TestCase):
    def pick(self, states):
        calls, sleeps = [], []

        def check(base):
            calls.append(base)
            return states[base].pop(0)

        with quiet():
            chosen = rf.pick_backend([HEXRA, STANDBY], check=check, sleep=sleeps.append)
        return chosen, calls, sleeps

    def test_primary_up_never_wakes_the_standby(self):
        chosen, calls, _ = self.pick({HEXRA: ["up"], STANDBY: ["up"]})
        self.assertEqual(chosen, HEXRA)
        self.assertEqual(calls, [HEXRA])

    def test_suspended_primary_fails_over_without_waiting(self):
        chosen, _, sleeps = self.pick({HEXRA: ["suspended"], STANDBY: ["up"]})
        self.assertEqual(chosen, STANDBY)
        self.assertEqual(sleeps, [])

    def test_one_failed_probe_does_not_flip_production(self):
        chosen, calls, sleeps = self.pick({HEXRA: ["down", "up"], STANDBY: ["up"]})
        self.assertEqual(chosen, HEXRA)
        self.assertEqual(calls, [HEXRA, HEXRA])
        self.assertEqual(len(sleeps), 1)

    def test_primary_down_twice_fails_over(self):
        chosen, _, _ = self.pick({HEXRA: ["down", "down"], STANDBY: ["up"]})
        self.assertEqual(chosen, STANDBY)

    def test_nothing_up_returns_none(self):
        chosen, _, _ = self.pick({HEXRA: ["suspended"], STANDBY: ["suspended"]})
        self.assertIsNone(chosen)


class MainTests(unittest.TestCase):
    def run_main(self, desired, current, argv=(), token="tok"):
        env = {"VERCEL_TOKEN": token} if token else {}
        switch = MagicMock()
        with patch.object(rf, "pick_backend", return_value=desired), \
             patch.object(rf, "live_backend", return_value=current), \
             patch.object(rf, "switch", switch), \
             patch.dict(rf.os.environ, env, clear=True), quiet():
            code = rf.main(list(argv))
        return code, switch

    def test_already_on_the_right_backend_changes_nothing(self):
        code, switch = self.run_main(STANDBY, STANDBY)
        self.assertEqual(code, 0)
        switch.assert_not_called()

    def test_switches_back_to_hexra_when_it_returns(self):
        code, switch = self.run_main(HEXRA, STANDBY)
        self.assertEqual(code, 0)
        self.assertEqual(switch.call_args.args[1], HEXRA)

    def test_fails_over_to_the_standby(self):
        code, switch = self.run_main(STANDBY, HEXRA)
        self.assertEqual(code, 0)
        self.assertEqual(switch.call_args.args[1], STANDBY)

    def test_dry_run_changes_nothing(self):
        code, switch = self.run_main(HEXRA, STANDBY, argv=["--dry-run"])
        self.assertEqual(code, 0)
        switch.assert_not_called()

    def test_unreadable_app_never_switches_blind(self):
        code, switch = self.run_main(HEXRA, None)
        self.assertEqual(code, 1)
        switch.assert_not_called()

    def test_no_backend_up_fails_the_run(self):
        code, switch = self.run_main(None, STANDBY)
        self.assertEqual(code, 1)
        switch.assert_not_called()

    def test_missing_token_fails_instead_of_skipping(self):
        code, switch = self.run_main(HEXRA, STANDBY, token=None)
        self.assertEqual(code, 1)
        switch.assert_not_called()


class SwitchTests(unittest.TestCase):
    def vercel(self, states):
        vercel = MagicMock()
        vercel.project.return_value = {"id": "prj_1", "name": "oreag"}
        vercel.production_deployments.return_value = [
            {"uid": f"dpl_{i}", "state": s} for i, s in enumerate(states)
        ]
        vercel.redeploy.return_value = {"url": "oreag-new.vercel.app"}
        return vercel

    def test_sets_the_variable_and_redeploys_the_latest_ready_build(self):
        vercel = self.vercel(["READY", "READY"])
        with quiet():
            rf.switch(vercel, HEXRA)
        vercel.set_production_env.assert_called_once_with("prj_1", rf.API_VAR, HEXRA)
        vercel.redeploy.assert_called_once_with("oreag", "dpl_0")

    def test_a_running_build_is_not_doubled(self):
        vercel = self.vercel(["BUILDING", "READY"])
        with quiet():
            rf.switch(vercel, HEXRA)
        vercel.set_production_env.assert_called_once()
        vercel.redeploy.assert_not_called()

    def test_skips_failed_builds_when_choosing_what_to_redeploy(self):
        vercel = self.vercel(["ERROR", "READY"])
        with quiet():
            rf.switch(vercel, STANDBY)
        vercel.redeploy.assert_called_once_with("oreag", "dpl_1")


if __name__ == "__main__":
    unittest.main()
