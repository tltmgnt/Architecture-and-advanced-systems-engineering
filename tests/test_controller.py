import tempfile
import unittest
from pathlib import Path

from researchos.controller import Controller
from researchos.pilot import run


class ControllerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "pilot.sqlite3"
        self.controller = Controller(self.path)
        self.addCleanup(self.controller.close)

    def transition(self, claim, state, role="approver"):
        return self.controller.transition(claim, state, actor="test", role=role, rationale="test")

    def test_matched_pilot_and_persistent_ledger(self):
        report = run(self.controller)
        self.assertEqual([row["researchos"]["state"] for row in report["records"]],
                         ["ASSURED", "CONTESTED", "CONTESTED", "CONTESTED"])
        self.assertEqual([stats["false_acceptances"] for stats in report["metrics"].values()],
                         [3, 2, 0])
        clean = report["records"][0]["researchos"]
        other_connection = Controller(self.path)
        try:
            self.assertEqual(other_connection.assurance(clean["id"]), clean)
        finally:
            other_connection.close()

    def test_governance_and_dependency_reopening(self):
        report = run(self.controller)
        upstream = report["records"][0]["researchos"]["id"]
        downstream = run(self.controller)["records"][0]["researchos"]["id"]
        self.controller.link(downstream, "depends_on", upstream, actor="test")
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.controller.link(upstream, "depends_on", downstream, actor="test")
        self.assertFalse(self.transition(downstream, "UNVERIFIED", "researcher")["accepted"])
        for state in ("UNVERIFIED", "SUPPORTED", "ADVERSARIAL_TEST", "REPRODUCED"):
            self.assertTrue(self.transition(downstream, state)["accepted"])
        self.assertFalse(self.transition(downstream, "VALIDATED")["accepted"])
        self.controller.add_evidence(
            downstream, kind="validation", outcome="PASS", source="recheck",
            source_group="recheck", method="test", detail="checked", actor="test",
        )
        for state in ("VALIDATED", "STABLE"):
            self.assertTrue(self.transition(downstream, state)["accepted"])
        self.assertFalse(self.transition(downstream, "ASSURED", "reviewer")["accepted"])
        self.assertTrue(self.transition(downstream, "ASSURED")["accepted"])
        failure = self.controller.add_evidence(
            upstream, kind="validation", outcome="FAIL", source="new", source_group="new",
            method="test", detail="counterexample", actor="test",
        )
        self.assertEqual(self.controller.assurance(downstream)["state"], "CONTESTED")
        self.assertTrue(self.transition(upstream, "UNVERIFIED")["accepted"])
        self.assertFalse(self.transition(upstream, "SUPPORTED")["accepted"])
        self.assertFalse(self.controller.resolve(upstream, failure, "reason",
                                                 actor="test", role="researcher"))
        self.assertTrue(self.controller.resolve(upstream, failure, "reason",
                                                actor="test", role="reviewer"))
        self.assertTrue(self.transition(upstream, "SUPPORTED")["accepted"])
