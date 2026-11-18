import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PilotCliTests(unittest.TestCase):
    def test_pilot_exports_expected_results_and_persists_assurance(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, "-m", "researchos", "--db",
                       str(Path(directory) / "pilot.sqlite3")]
            report = subprocess.run(command + ["pilot"], check=True, capture_output=True, text=True)
            payload = json.loads(report.stdout)
            self.assertEqual(payload["metrics"]["researchos"], {
                "accepted": 1, "false_acceptances": 0, "true_acceptances": 1,
            })
            states = {row["fixture"]: row["researchos"]["state"] for row in payload["records"]}
            self.assertEqual(states, {
                "clean": "ASSURED",
                "contradiction": "CONTESTED",
                "source_integrity": "CONTESTED",
                "dependency_integrity": "CONTESTED",
            })
            clean = next(row["researchos"] for row in payload["records"] if row["fixture"] == "clean")
            saved = subprocess.run(
                command + ["assurance", json.dumps({"claim": clean["id"]})],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual(json.loads(saved.stdout), clean)
