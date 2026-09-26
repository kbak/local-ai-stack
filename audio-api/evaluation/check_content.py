"""Screen saved clips for missing speech with cached multilingual Whisper small.

This is an automatic content check, not a human pronunciation/quality score.
Run after synthesis candidates exit, on the same isolated 5060 Ti.
"""

import argparse
import json
import os
from pathlib import Path
import re

import torch
from faster_whisper import WhisperModel


def word_error_rate(expected, actual):
    reference = re.findall(r"\w+", expected.casefold())
    hypothesis = re.findall(r"\w+", actual.casefold())
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, candidate in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (word != candidate)))
        previous = current
    return round(previous[-1] / max(1, len(reference)), 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    if not os.environ.get("CUDA_VISIBLE_DEVICES", "").startswith("GPU-"):
        raise RuntimeError("An explicit GPU UUID is required")
    if torch.cuda.device_count() != 1 or "5060 Ti" not in torch.cuda.get_device_name(0):
        raise RuntimeError("Content checking must use only the RTX 5060 Ti")
    model = WhisperModel("small", device="cuda", compute_type="float16", local_files_only=True)
    checks = []
    for report_path in sorted(args.root.glob("**/results.json")):
        report = json.loads(report_path.read_text())
        if "cases" not in report:
            continue
        for case in report["cases"]:
            path = report_path.parent / (case["id"] + ".wav")
            segments, _ = model.transcribe(str(path), language=case["language"],
                                          beam_size=5, condition_on_previous_text=False)
            transcript = " ".join(segment.text.strip() for segment in segments)
            check = {"clip": str(path.relative_to(args.root)), "expected": case["text"],
                     "transcript": transcript, "automatic_wer": word_error_rate(case["text"], transcript)}
            checks.append(check)
            print(json.dumps(check, ensure_ascii=False), flush=True)
    (args.root / "content-checks.json").write_text(json.dumps(
        {"recognizer": "Whisper small, multilingual", "human_reviewed": False, "clips": checks},
        indent=2, ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
