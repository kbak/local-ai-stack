#!/usr/bin/env python3
"""Local ASR comparison; flags are review aids, not proof of audible quality."""
import argparse
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

from audiobook import STATE, digest, read_json, write_json


def words(text):
    text = text.lower()
    text = re.sub(r'\b(?:[a-z][ .-]+){1,}[a-z]\b',
                  lambda m: re.sub('[^a-z]', '', m.group()), text)
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)


def compare(expected, actual):
    a, b = words(expected), words(actual)
    changes = []
    cost = 0
    longest_missing = 0
    for tag, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != 'equal':
            cost += max(j-i, l-k)
            if tag == 'delete':
                longest_missing = max(longest_missing, j-i)
            changes.append({'type': tag, 'expected': ' '.join(a[i:j]), 'heard': ' '.join(b[k:l])})
    ratio = cost / max(1, len(a))
    return {'approx_word_error_ratio': ratio, 'longest_missing_run': longest_missing,
            'flagged': ratio > 0.14 or longest_missing >= 5, 'changes': changes}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('job', type=Path)
    p.add_argument('--watch', action='store_true')
    p.add_argument('--voice', action='store_true')
    p.add_argument('--threads', type=int, default=6)
    args = p.parse_args()
    from faster_whisper import WhisperModel
    model = WhisperModel(str(STATE / 'models/whisper-large-v3-turbo'), device='cpu',
                         compute_type='int8', cpu_threads=args.threads, num_workers=1)
    job = args.job.resolve()
    if args.voice:
        segments, _ = model.transcribe(str(job / 'narrator.wav'), language='en', beam_size=5,
                                       condition_on_previous_text=False)
        transcript = ' '.join(s.text.strip() for s in segments)
        result = {'transcript': transcript, **compare(read_json(job / 'narrator.json')['text'], transcript)}
        write_json(job / 'narrator-check.json', result)
        print(json.dumps(result), flush=True)
        return
    plan = read_json(job / 'plan.json')
    checks = job / 'checks'
    checks.mkdir(exist_ok=True)
    while True:
        pending = 0
        for block in plan['blocks']:
            wav = job / 'chunks' / f"{block['id']:04d}.wav"
            output = checks / f"{block['id']:04d}.json"
            if not wav.exists():
                pending += 1
                continue
            sha = digest(wav.read_bytes())
            if output.exists() and read_json(output).get('audio_sha256') == sha:
                continue
            start = time.monotonic()
            segments, _ = model.transcribe(str(wav), language='en', beam_size=5,
                                           condition_on_previous_text=False, vad_filter=True)
            transcript = ' '.join(s.text.strip() for s in segments)
            result = {'block': block['id'], 'audio_sha256': sha, 'transcript': transcript,
                      'expected': block['text'], **compare(block['text'], transcript),
                      'check_seconds': time.monotonic()-start}
            write_json(output, result)
            print(json.dumps({'block': block['id'], 'flagged': result['flagged'],
                              'difference': round(result['approx_word_error_ratio'], 3)}), flush=True)
        all_checks = [read_json(f) for f in sorted(checks.glob('*.json'))]
        write_json(job / 'quality-report.json', {'checked': len(all_checks), 'total': len(plan['blocks']),
                                                'flagged': [c for c in all_checks if c['flagged']]})
        if not args.watch or pending == 0:
            break
        time.sleep(10)


if __name__ == '__main__':
    main()
