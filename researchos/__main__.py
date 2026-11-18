"""JSON command-line interface for local operators and pipeline adapters."""
import argparse
import json
import sqlite3

from .controller import Controller
from .pilot import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="researchos.sqlite3")
    parser.add_argument("operation", choices=(
        "pilot", "register", "add_evidence", "link", "resolve", "transition", "assurance",
    ))
    parser.add_argument("payload", nargs="?", default="{}", help="JSON object of operation arguments")
    args = parser.parse_args()
    controller = None
    try:
        payload = json.loads(args.payload)
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
        controller = Controller(args.db)
        if args.operation == "pilot":
            if payload:
                raise ValueError("Pilot takes no arguments")
            result = run(controller)
        else:
            result = getattr(controller, args.operation)(**payload)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result is False or isinstance(result, dict) and result.get("accepted") is False else 0
    except (ValueError, TypeError, sqlite3.Error) as error:
        parser.exit(2, json.dumps({"error": str(error)}) + "\n")
    finally:
        if controller is not None:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
