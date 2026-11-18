"""Synthetic model-output assurance pilot with no external model or services."""
from hashlib import sha256
from time import perf_counter

# Synthetic candidates with independently specified expected totals and manifests.
TASKS = (
    {"id": "clean", "values": [2, 3, 5], "answer": 10, "expected": 10},
    {"id": "contradiction", "values": [2, 3, 5], "answer": 11, "expected": 10},
    {"id": "source_integrity", "values": [4, 7], "answer": 11, "expected": 11, "corrupt": True},
    {"id": "dependency_integrity", "values": [6, 7], "answer": 13, "expected": 13, "observed_inputs": ["input-a"]},
)


def checks(task):
    values = task["values"]
    source = repr(values).encode()
    observed = source + b" altered" if task.get("corrupt") else source
    expected_inputs = {"input-a", "input-b"}
    observed_inputs = set(task.get("observed_inputs", expected_inputs))
    return {
        "contradiction": task["answer"] == task["expected"],
        "source_integrity": sha256(observed).digest() == sha256(source).digest(),
        "dependency_integrity": expected_inputs == observed_inputs,
    }


def run(controller):
    records = []
    started = perf_counter()
    for task in TASKS:
        candidate = controller.register(
            f"The total for {task['values']} is {task['answer']}.",
            f"synthetic-model-output:{task['id']}", actor="fixture-generator",
        )
        controller.transition(candidate, "UNVERIFIED", actor="pilot", role="researcher",
                              rationale="Registered for assessment")

        def record(kind, result, source, group, method):
            controller.add_evidence(
                candidate, kind=kind, outcome="PASS" if result else "FAIL",
                source=source, source_group=group, method=method,
                detail=f"{method} {'passed' if result else 'failed'}", actor="pilot",
            )

        record("support", True, "candidate-format", "generator", "Integer and list format check")
        for desired in ("SUPPORTED", "ADVERSARIAL_TEST"):
            controller.transition(candidate, desired, actor="pilot", role="researcher",
                                  rationale="Start synthetic perturbation checks")
        for kind, result in checks(task).items():
            record(kind, result, "fixture-manifest", "manifest", kind)
        total = 0
        for value in task["values"]:
            total += value
        record("reproduction", total == task["answer"], "independent-replay", "replay",
               "Iterative addition")
        record("validation", sum(task["values"]) == task["answer"], "validator", "validator",
               "Built-in integer summation")
        for desired in ("REPRODUCED", "VALIDATED", "STABLE", "ASSURED"):
            decision = controller.transition(candidate, desired, actor="pilot",
                                             role="approver", rationale="Execute pilot policy")
            if not decision["accepted"]:
                break

        records.append({
            "fixture": task["id"],
            "expected_assurable": task["id"] == "clean",
            "accept_all_baseline": True,
            "arithmetic_only_baseline": sum(task["values"]) == task["answer"],
            "researchos": controller.assurance(candidate),
        })
    elapsed = perf_counter() - started
    metrics = {}
    for name in ("accept_all_baseline", "arithmetic_only_baseline", "researchos"):
        accepted = [record for record in records if (
            record[name]["state"] == "ASSURED" if name == "researchos" else record[name]
        )]
        metrics[name] = {
            "accepted": len(accepted),
            "false_acceptances": sum(not row["expected_assurable"] for row in accepted),
            "true_acceptances": sum(row["expected_assurable"] for row in accepted),
        }
    return {"records": records, "metrics": metrics, "researchos_elapsed_seconds": elapsed}
