"""Validate a saved candidate response without importing it or running inference."""
import argparse
import json
from pathlib import Path
from backend.analysis import validate_response, compare_reviewed_anchors, write_private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--reference-export", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.exit(1, "Use a new report path to preserve earlier results.\n")
    try:
        result = validate_response(args.bundle, json.loads(args.response.read_text()))
        report = {"valid": True, "responseKind": result.responseKind, "candidateCount": len(result.findings),
                  "inferenceExecutedByChecker": False, "imported": False,
                  "notice": "Structure and evidence references validated; factual claims still require human review."}
        if args.reference_export:
            report["evaluation"] = compare_reviewed_anchors(result, json.loads(args.reference_export.read_text())["experiment"])
        write_private(args.report, report)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"Validation failed: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
