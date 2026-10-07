"""Print progress without loading any model."""
import argparse
import json
import statistics
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('--details', action='store_true')
    args = parser.parse_args()
    job = args.job
    plan = json.loads((job / 'plan.json').read_text())
    renders = [json.loads(p.read_text()) for p in sorted((job / 'chunks').glob('*.json'))]
    checks = [json.loads(p.read_text()) for p in sorted((job / 'checks').glob('*.json'))]
    flagged = [c for c in checks if c['flagged']]
    audio_seconds = sum(r['seconds'] for r in renders)
    result = {'rendered': len(renders), 'total': len(plan['blocks']),
              'chapter': plan['blocks'][renders[-1]['block']]['chapter'] if renders else None,
              'audio_minutes': round(audio_seconds/60, 1), 'checked': len(checks),
              'flagged': [c['block'] for c in flagged]}
    if len(renders) > 3:
        result['median_render_factor'] = round(statistics.median(
            r['generation_seconds']/r['seconds'] for r in renders[1:]), 3)
        result['peak_GiB'] = round(max(r['peak_allocated_GiB'] for r in renders), 2)
    print(json.dumps(result), flush=True)
    if args.details:
        for c in flagged:
            print(json.dumps({'block': c['block'], 'changes': c['changes']}), flush=True)


if __name__ == '__main__':
    main()
