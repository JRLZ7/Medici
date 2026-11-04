"""Import one completed local run as unreviewed suggestions, without duplication."""
import argparse
import json
from pathlib import Path
import uuid
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', type=uuid.UUID, required=True)
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    args = parser.parse_args()
    run_id = str(args.run_id)
    root = args.data_dir.resolve()
    folder = (root / 'analysis/runs' / run_id).resolve()
    if not folder.is_relative_to(root):
        parser.exit(1, 'Run is outside this workspace.\n')
    try:
        metadata = json.loads((folder / 'run.json').read_text())
        eid = str(uuid.UUID(metadata['experimentId']))
        with httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False, follow_redirects=False, timeout=60) as client:
            health = client.get('/api/health')
            if health.status_code != 200 or not health.json().get('localModelImport'):
                parser.exit(1, 'Restart Medici in its terminal (Ctrl+C, then npm start) before importing local model suggestions.\n')
            response = client.post(f'/api/experiments/{eid}/analysis-runs/import',
                                   json={'runId':run_id}, headers={'X-Medici-Request':'1'})
            if response.status_code != 200:
                detail = response.json().get('detail', 'Restart Medici and retry.')
                parser.exit(1, f'Import failed: {detail}\n')
            result = response.json()
            count = sum(o.get('analysisRunId') == run_id for o in result['observations'])
            print(f'Imported run {run_id}: {count} suggestions. Existing human edits were preserved.')
    except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
        parser.exit(1, f'Import failed: {error}\n')


if __name__ == '__main__':
    main()
