"""Versioned TECT policy and transactional epistemic graph."""
from contextlib import contextmanager
import json
import sqlite3
from uuid import uuid4

POLICY_VERSION = "tect-pilot/1"
STATES = (
    "GENERATED", "UNVERIFIED", "SUPPORTED", "ADVERSARIAL_TEST",
    "REPRODUCED", "VALIDATED", "STABLE", "ASSURED",
)
CHALLENGES = {"contradiction", "source_integrity", "dependency_integrity"}
KINDS = {"support", "reproduction", "validation"} | CHALLENGES
OUTCOMES = {"PASS", "FAIL", "UNCERTAIN"}
ROLES = {"researcher", "reviewer", "approver"}
# Only dependencies and derivations propagate changes to downstream claims.
RELATIONS = {"depends_on", "derives_from", "supports", "contradicts",
             "reproduces", "qualifies", "invalidates"}


class Controller:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY, statement TEXT NOT NULL, source TEXT NOT NULL,
                state TEXT NOT NULL, version INTEGER NOT NULL, last_validation TEXT
            );
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, claim TEXT NOT NULL REFERENCES claims(id),
                kind TEXT NOT NULL, outcome TEXT NOT NULL, source TEXT NOT NULL,
                method TEXT NOT NULL, source_group TEXT NOT NULL,
                detail TEXT NOT NULL, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS edges (
                claim TEXT NOT NULL REFERENCES claims(id),
                relation TEXT NOT NULL, target TEXT NOT NULL REFERENCES claims(id),
                PRIMARY KEY (claim, relation, target), CHECK (claim != target)
            );
            CREATE TABLE IF NOT EXISTS ledger (
                sequence INTEGER PRIMARY KEY, claim TEXT NOT NULL REFERENCES claims(id),
                action TEXT NOT NULL, actor TEXT NOT NULL, details TEXT NOT NULL,
                policy TEXT NOT NULL, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self, *, write=True):
        self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _claim(self, claim):
        row = self.db.execute("SELECT * FROM claims WHERE id = ?", (claim,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown claim {claim}")
        return dict(row)

    def _log(self, claim, action, actor, **details):
        self.db.execute(
            "INSERT INTO ledger(claim, action, actor, details, policy) VALUES (?,?,?,?,?)",
            (claim, action, actor, json.dumps(details, sort_keys=True), POLICY_VERSION),
        )

    @staticmethod
    def _require_text(*values):
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("Nonempty text is required")

    def register(self, statement, source, *, actor):
        self._require_text(statement, source, actor)
        claim = str(uuid4())
        with self.transaction():
            self.db.execute("INSERT INTO claims VALUES (?,?,?,'GENERATED',1,NULL)",
                            (claim, statement, source))
            self._log(claim, "registered", actor, version=1)
        return claim

    def add_evidence(self, claim, *, kind, outcome, source, method, source_group, detail, actor):
        self._require_text(source, method, source_group, detail, actor)
        if kind not in KINDS or outcome not in OUTCOMES:
            raise ValueError("Unknown evidence kind or outcome")
        evidence = str(uuid4())
        with self.transaction():
            self._claim(claim)
            self.db.execute(
                "INSERT INTO evidence(id,claim,kind,outcome,source,method,source_group,detail)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (evidence, claim, kind, outcome, source, method, source_group, detail),
            )
            self._log(claim, "evidence_recorded", actor, evidence=evidence, outcome=outcome)
            self._reopen(claim, actor, f"Evidence added ({evidence})", force=outcome == "FAIL")
        return evidence

    def link(self, claim, relation, target, *, actor):
        self._require_text(actor)
        if relation not in RELATIONS:
            raise ValueError("Unknown relationship")
        with self.transaction():
            self._claim(claim)
            self._claim(target)
            if claim == target:
                raise ValueError("A claim cannot link to itself")
            if relation in {"depends_on", "derives_from"} and target in self._dependents(claim):
                raise ValueError("Dependency cycle")
            self.db.execute("INSERT INTO edges VALUES (?,?,?)", (claim, relation, target))
            self._log(claim, "linked", actor, relation=relation, target=target)
            self._reopen(claim, actor, f"Relationship added ({relation})",
                         force=relation in {"contradicts", "invalidates"})

    def _dependents(self, target):
        rows = self.db.execute("""
            WITH RECURSIVE connected(id) AS (
                SELECT ? UNION SELECT edges.claim FROM edges JOIN connected
                ON edges.target = connected.id
                WHERE edges.relation IN ('depends_on','derives_from')
            ) SELECT id FROM connected
        """, (target,))
        return {row["id"] for row in rows}

    def _set_state(self, claim, state, actor, reason, *, role="controller"):
        current = self._claim(claim)
        self.db.execute("""
            UPDATE claims SET state=?, version=version+1,
            last_validation=CASE WHEN ?='VALIDATED' THEN CURRENT_TIMESTAMP ELSE last_validation END
            WHERE id=?
        """, (state, state, claim))
        self._log(claim, "transition_accepted", actor, previous=current["state"], state=state,
                  version=current["version"] + 1, reason=reason, role=role)

    def _reopen(self, claim, actor, reason, *, force):
        if not force and self._claim(claim)["state"] not in {
            "VALIDATED", "STABLE", "ASSURED"
        }:
            return
        for affected in sorted(self._dependents(claim)):
            if self._claim(affected)["state"] not in {"CONTESTED", "REJECTED"}:
                self._set_state(affected, "CONTESTED", actor, reason)

    def resolve(self, claim, evidence, rationale, *, actor, role):
        self._require_text(rationale, actor)
        with self.transaction():
            row = self.db.execute("SELECT outcome FROM evidence WHERE id=? AND claim=?",
                                  (evidence, claim)).fetchone()
            if role not in {"reviewer", "approver"} or row is None or row["outcome"] == "PASS":
                self._log(claim, "resolution_blocked", actor, evidence=evidence, role=role)
                return False
            self._log(claim, "evidence_resolved", actor, evidence=evidence, rationale=rationale,
                      role=role)
            return True

    def _resolved(self, claim):
        return {json.loads(row["details"])["evidence"] for row in self.db.execute(
            "SELECT details FROM ledger WHERE claim=? AND action='evidence_resolved'", (claim,)
        )}

    def _gate(self, claim, current, desired, role):
        if role not in ROLES:
            return "Unknown role"
        if current == "CONTESTED" and desired == "REJECTED":
            return None if role in {"reviewer", "approver"} else "Reviewer or approver required"
        if current == "CONTESTED" and desired == "UNVERIFIED":
            return None if role in {"reviewer", "approver"} else "Reviewer or approver required"
        if current not in STATES[:-1] or desired != STATES[STATES.index(current) + 1]:
            return "Transition must follow the policy sequence"
        if desired == "UNVERIFIED":
            return None
        if desired == "ASSURED" and role != "approver":
            return "Approver required"
        if role == "researcher" and desired in {"VALIDATED", "STABLE"}:
            return "Reviewer or approver required"
        resolved = self._resolved(claim)
        evidence = list(self.db.execute("SELECT * FROM evidence WHERE claim=?", (claim,)))
        outcomes = [item for item in evidence if item["id"] not in resolved]
        if any(item["outcome"] == "FAIL" for item in outcomes):
            return "Unresolved failed evidence"
        edges = self.db.execute("""
            SELECT relation, target, state FROM edges JOIN claims ON claims.id = edges.target
            WHERE edges.claim=?
        """, (claim,)).fetchall()
        if any(edge["relation"] in {"contradicts", "invalidates"} and edge["state"] != "REJECTED"
               for edge in edges):
            return "Unresolved contradictory claim"
        dependencies = [edge for edge in edges if edge["relation"] in {"depends_on", "derives_from"}]
        passed = [item for item in outcomes if item["outcome"] == "PASS"]
        kinds = {item["kind"] for item in passed}
        if "support" not in kinds:
            return "Passing support is required"
        if desired in {"REPRODUCED", "VALIDATED", "STABLE", "ASSURED"}:
            if CHALLENGES - kinds or any(item["outcome"] == "UNCERTAIN" and item["kind"] in CHALLENGES
                                         for item in outcomes):
                return "All three challenge classes require a passing result and resolution of uncertainty"
            support_groups = {item["source_group"] for item in passed if item["kind"] == "support"}
            if not any(item["kind"] == "reproduction" and item["source_group"] not in support_groups
                       for item in passed):
                return "Independent passing reproduction is required"
        if desired in {"VALIDATED", "STABLE", "ASSURED"}:
            reopened_at = 0
            recorded_at = {}
            for entry in self.db.execute(
                "SELECT sequence, action, details FROM ledger WHERE claim=? ORDER BY sequence", (claim,)
            ):
                details = json.loads(entry["details"])
                if entry["action"] == "transition_accepted" and details["state"] == "CONTESTED":
                    reopened_at = entry["sequence"]
                if entry["action"] == "evidence_recorded":
                    recorded_at[details["evidence"]] = entry["sequence"]
            if not any(item["kind"] == "validation" and recorded_at[item["id"]] > reopened_at
                       for item in passed):
                return "Passing validation recorded after the last contest is required"
            if any(item["outcome"] == "UNCERTAIN" for item in outcomes):
                return "Passing validation and resolution of remaining uncertainty are required"
            allowed = {"VALIDATED", "STABLE", "ASSURED"} if desired != "ASSURED" else {"ASSURED"}
            if any(edge["state"] not in allowed for edge in dependencies):
                return "Dependencies must meet the required assurance level"
        return None

    def transition(self, claim, desired, *, actor, role, rationale):
        self._require_text(actor, rationale, desired)
        with self.transaction():
            current = self._claim(claim)["state"]
            reason = self._gate(claim, current, desired, role)
            if reason:
                self._log(claim, "transition_blocked", actor, previous=current, requested=desired,
                          reason=reason, rationale=rationale, role=role)
                return {"accepted": False, "state": current, "reason": reason}
            self._set_state(claim, desired, actor, rationale, role=role)
            return {"accepted": True, "state": desired}

    def assurance(self, claim):
        with self.transaction(write=False):
            snapshot = self._claim(claim)
            for table in ("evidence", "edges", "ledger"):
                rows = self.db.execute(f"SELECT * FROM {table} WHERE claim=? ORDER BY rowid", (claim,))
                snapshot[table] = [dict(row) for row in rows]
            for entry in snapshot["ledger"]:
                entry["details"] = json.loads(entry["details"])
            snapshot["policy"] = POLICY_VERSION
            snapshot["resolved_evidence"] = sorted(self._resolved(claim))
            snapshot["perturbation_family"] = sorted(CHALLENGES)
            return snapshot
