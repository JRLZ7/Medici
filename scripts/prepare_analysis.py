"""Build a private, checksum-bound frame bundle. No model executes."""
import argparse
import json
from pathlib import Path
from backend.analysis import prepare_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New private directory, normally under data/analysis/")
    parser.add_argument("--spacing", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=32)
    args = parser.parse_args()
    try:
        record = json.loads(args.export.read_text())
        result = prepare_bundle(record["experiment"], args.video, args.output, args.spacing, args.max_frames)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"Preparation failed: {error}\n")
    print(json.dumps({"status": "ready", "frames": len(result["frames"]), "inferenceExecuted": False}))


if __name__ == "__main__":
    main()
