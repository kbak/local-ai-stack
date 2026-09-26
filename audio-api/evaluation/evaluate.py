"""Generate a reproducible local listening comparison; never sends messages.

Run the candidate backends sequentially after stopping the production audio
container. Mount this directory, output directory, and reference WAVs. VoxCPM
also needs its pinned source and model directories mounted; see the results doc.
"""

import argparse
import html
import io
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np
import soundfile as sf


CASES = [
    {"id": "en_short", "language": "en", "voice": "barack_obama", "text":
     "Good morning. Your appointment is tomorrow at half past nine. Please bring your identification and arrive ten minutes early."},
    {"id": "en_expression", "language": "en", "voice": "barack_obama", "text":
     "Wait, we actually did it? That is wonderful! I was worried we would miss the train, but now we have time for coffee. Let us take a moment and enjoy the view."},
    {"id": "pl_short", "language": "pl", "voice": "potop", "text":
     "Dzień dobry. Twoja wizyta jest jutro o dziewiątej trzydzieści. Zabierz dokument tożsamości i przyjdź dziesięć minut wcześniej."},
    {"id": "pl_expression", "language": "pl", "voice": "potop", "text":
     "Naprawdę nam się udało? To wspaniale! Myślałem, że spóźnimy się na pociąg do Wrocławia, ale mamy jeszcze czas na kawę. Usiądźmy na chwilę i odpocznijmy."},
]


def write_index(root):
    reports = [report for p in sorted(root.glob("*/results.json"))
               if "cases" in (report := json.loads(p.read_text()))]
    labels = {"current": "Previous stack", "chatterbox-v3": "Chatterbox V3",
              "voxcpm2": "VoxCPM2 trial"}
    titles = {"en_short": "English: appointment", "en_expression": "English: expressive speech",
              "pl_short": "Polish: appointment", "pl_expression": "Polish: expressive speech"}
    parts = ["<!doctype html><meta charset='utf-8'><title>English and Polish TTS comparison</title>",
             "<style>body{font:17px system-ui;max-width:1100px;margin:40px auto;padding:20px;background:#f5f5f5;color:#222}"
             "article{background:white;padding:20px;margin:20px 0;border-radius:12px}td,th{padding:12px;text-align:left;vertical-align:top}"
             "table{width:100%}audio{max-width:100%;width:330px}small{display:block;color:#555}</style>",
             "<h1>English and Polish TTS comparison</h1><p>All clips are AI-generated evaluation samples, not authentic recordings of the reference speakers. "
             "Compare naturalness, pronunciation, speaker similarity, and missing or repeated words. "
             "WAV is the original output; Opus uses the stack's Signal encoding. "
             "Previous stack means the saved output from before the upgrade. Timings are single runs; "
             "the first reference can include additional setup overhead.</p>"]
    for case in CASES:
        parts.append(f"<article><h2>{html.escape(titles[case['id']])}</h2><p>{html.escape(case['text'])}</p><table><tr><th>Model</th><th>WAV</th><th>Signal Opus</th></tr>")
        for report in reports:
            for row in report["cases"]:
                if row["id"] != case["id"]:
                    continue
                stem = f"{report['engine']}/{case['id']}"
                parts.append(f"<tr><td>{html.escape(labels.get(report['engine'], report['engine']))}<small>{row['seconds']:.2f}s generation; "
                             f"{row['duration']:.2f}s audio; RTF {row['rtf']:.2f}</small></td>"
                             f"<td><audio controls preload='none' src='{stem}.wav'></audio></td>"
                             f"<td><audio controls preload='none' src='{stem}.ogg'></audio></td></tr>")
        parts.append("</table></article>")
    (root / "index.html").write_text("\n".join(parts))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["current", "chatterbox-v3", "voxcpm2"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8088")
    parser.add_argument("--model-dir", default="/models/VoxCPM2")
    parser.add_argument("--reference-dir", type=Path, default=Path("/app/voice-samples"))
    args = parser.parse_args()
    root = args.output
    out = root / args.engine
    out.mkdir(parents=True, exist_ok=True)
    report = {"engine": args.engine, "cases": [],
              "seed": None if args.engine == "current" else 20260925}
    torch = None

    if args.engine == "current":
        import httpx
        client = httpx.Client(base_url=args.api_url, timeout=240)

        def synthesize(case):
            response = client.post("/v1/audio/clone", json={
                "text": case["text"], "language": case["language"],
                "voice": case["voice"], "response_format": "wav",
            })
            response.raise_for_status()
            return response.content
    else:
        # Check isolation before constructing any model or CUDA tensors.
        import torch
        if not os.environ.get("CUDA_VISIBLE_DEVICES", "").startswith("GPU-"):
            raise RuntimeError("Evaluation requires an explicit GPU UUID")
        if torch.cuda.device_count() != 1 or "5060 Ti" not in torch.cuda.get_device_name(0):
            raise RuntimeError("Only the RTX 5060 Ti may be visible to audio evaluation")
        report["gpu"] = torch.cuda.get_device_name(0)
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        if args.engine == "chatterbox-v3":
            from app import chatterbox_engine
            chatterbox_engine.load()
            from app import config
            report["revision"] = config.CHATTERBOX_REVISION
            report["english_model"] = config.CHATTERBOX_ENGLISH_MODEL
            report["runtime_commit"] = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"

            def synthesize(case):
                return chatterbox_engine.synthesize(
                    case["text"], voice=case["voice"], language=case["language"],
                )
        else:
            from voxcpm import VoxCPM
            model = VoxCPM.from_pretrained(
                args.model_dir, load_denoiser=False, optimize=False, device="cuda:0",
            )
            report["revision"] = "32279effe8c19989596f05d353d1447f51d9e915"
            report["runtime_commit"] = "f772e498a45fbb5fb8e13fbf9b9c48be9fe33e69"
            report["optimize"] = False
            report["inference_timesteps"] = 10
            # A short warmup ensures scored cases do not include first kernel setup.
            model.generate(text="This is a short warmup.", seed=20260925, max_len=256)

            def synthesize(case):
                audio = model.generate(
                    text=case["text"],
                    reference_wav_path=str(args.reference_dir / (case["voice"] + ".wav")),
                    cfg_value=2.0, inference_timesteps=10, normalize=False, denoise=False,
                    seed=20260925, max_len=1024, retry_badcase_max_times=1,
                )
                buffer = io.BytesIO()
                sf.write(buffer, audio, model.tts_model.sample_rate, format="WAV", subtype="PCM_16")
                return buffer.getvalue()
        report["load_and_warmup_seconds"] = round(time.perf_counter() - started, 3)

    for case in CASES:
        if torch is not None:
            torch.manual_seed(20260925)
            torch.cuda.synchronize()
        started = time.perf_counter()
        wav = synthesize(case)
        elapsed = time.perf_counter() - started
        data, rate = sf.read(io.BytesIO(wav))
        if len(data) == 0 or not np.isfinite(data).all():
            raise RuntimeError(f"Invalid audio for {case['id']}")
        duration = len(data) / rate
        path = out / (case["id"] + ".wav")
        path.write_bytes(wav)
        subprocess.run([
            "ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-c:a", "libopus",
            "-b:a", "24k", "-vbr", "on", "-application", "voip", str(path.with_suffix(".ogg")),
        ], check=True)
        row = {**case, "seconds": round(elapsed, 3), "duration": round(duration, 3),
               "rtf": round(elapsed / duration, 3), "sample_rate": rate,
               "peak_amplitude": round(float(np.max(np.abs(data))), 5),
               "clipped_fraction": float(np.mean(np.abs(data) >= 0.999))}
        report["cases"].append(row)
        if torch is not None:
            report["peak_torch_allocated_mib"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
            report["peak_torch_reserved_mib"] = round(torch.cuda.max_memory_reserved() / 2**20, 1)
            free, total = torch.cuda.mem_get_info()
            report["device_used_mib_after_case"] = round((total - free) / 2**20, 1)
        (out / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        write_index(root)
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
