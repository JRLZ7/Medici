"""Run an explicitly enabled local Ollama experiment. No automatic imports/pulls."""
import argparse
from pathlib import Path
import httpx
from backend.ollama_adapter import infer_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--runs-dir', type=Path, default=Path('data/analysis/runs'))
    parser.add_argument('--enable-local-inference', action='store_true')
    parser.add_argument('--max-batches', type=int)
    parser.add_argument('--start-batch', type=int, default=0, help='Zero-based window for a focused partial test')
    args = parser.parse_args()
    try:
        result = infer_bundle(args.bundle, args.runs_dir, enabled=args.enable_local_inference,
                              max_batches=args.max_batches, start_batch=args.start_batch, progress=lambda line: print(line, flush=True))
    except KeyboardInterrupt:
        parser.exit(130, 'Local run cancelled; partial output is not importable.\n')
    except (ValueError, KeyError, OSError, httpx.HTTPError) as error:
        parser.exit(1, f'Local run failed: {error}\n')
    print(f'Completed: {result}\nSuggestions await human review; no app observations were imported.')


if __name__ == '__main__':
    main()
