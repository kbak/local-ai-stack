# On-demand audiobooks

Prepare chaptered text, render resumable narration with Fish S2 Pro or Breeze,
check the audio with local Whisper, and export FLAC and chaptered Ogg/Opus.
These command-line tools live in `scripts/audiobook/` and run separately from
the stack's services. Run the commands below from the repository root.

## Setup

Requirements: Linux, Python 3.12, `uv`, `hf`, Git, FFmpeg with libopus, `flock`,
a compiler toolchain, and a CUDA 12.8-capable driver. Install either renderer:

```bash
bash scripts/audiobook/setup-fish.sh  # Fish S2 Pro
bash scripts/audiobook/setup.sh       # Breeze
```

The installers pin model and code revisions and Python dependencies. Models,
environments, caches, and job data belong under the gitignored
`.maintenance/audiobook/` directory. Keep source manuscripts, reference recordings,
transcripts, and generated audio there; do not add them to the public source tree.

Set `CUDA_VISIBLE_DEVICES` to a single GPU index or UUID before running a renderer;
the default is GPU `0`. Fish requires at least 24 GiB of free VRAM and caps the
PyTorch allocator at 26 GiB or device capacity, whichever is smaller. Breeze
requires 12 GiB free, or 19 GiB with `--fast`, and caps its allocator at 24 GiB.
Allocations outside PyTorch are not covered by these caps. A file lock serializes
workers started through the shell runners. Model processes exit after rendering.

Check the model licenses before use: installers do not grant rights to model
weights, reference voices, source texts, or generated outputs. License references
are in the downloaded model repositories.

## Prepare a job

Input is UTF-8 text, with chapter headings in the form `CHAPTER 1: TITLE` on
separate paragraphs. An optional `FULL SPOKEN SCRIPT` marker excludes preceding
notes. Long paragraphs are split at sentence boundaries.

```bash
JOB=.maintenance/audiobook/jobs/my-book
python3 scripts/audiobook/audiobook.py prepare .maintenance/audiobook/manuscript.txt "$JOB" \
  --engine fish --title 'Example Book'
```

The title defaults to the source filename stem. Optional `--pronunciations FILE`
accepts a JSON object mapping words to spoken replacements. No replacements are
applied by default. `plan.json` records the substitutions and `narration.txt`
contains the exact model input. Use a new job directory when changing preparation
settings for an existing job.

## Supply a narrator and render

Fish expects `narrator.wav` and `narrator.json` in the job directory. Supply a
reference recording you have permission to use and its exact transcript. The JSON
must contain `text` (the transcript) and `sha256` (the SHA-256 digest of the WAV).
Keep both files unchanged throughout a job. Alternatively, copy this pair from
an existing local job whose voice you want to reuse.

```bash
bash scripts/audiobook/run-fish.sh "$JOB" --stop 4
# Listen to the opening, then resume.
bash scripts/audiobook/run-fish.sh "$JOB"
```

For Breeze, prepare with `--engine breeze`, generate a reference with
`bash scripts/audiobook/run.sh voice "$JOB" --instruction 'A clear, calm narrator'`,
then render with `bash scripts/audiobook/run.sh render "$JOB"`. The optional `--fast`
flag is available for Breeze voice creation and rendering.

Both renderers verify saved audio hashes and resume completed passages.
`--start N --stop M` selects a range. Fish also supports `--blocks 10 23` for
individual passages and `--retry` to rerender selected passages with new seeds,
retaining previous files under `rejected/`. Settings or reference mismatches
are rejected to prevent mixing incompatible audio.

## Check and export

For Fish, use its installed environment:

```bash
PYTHON=.maintenance/audiobook/fish-venv/bin/python
"$PYTHON" scripts/audiobook/check_audio.py "$JOB"
python3 scripts/audiobook/status.py "$JOB" --details
"$PYTHON" scripts/audiobook/audiobook.py assemble "$JOB"
```

For Breeze, use `.maintenance/audiobook/venv/bin/python` instead. Audio checking
runs Whisper on the CPU in English; `--watch` checks new passages as rendering
proceeds. `quality-report.json` flags transcript differences for review. Names,
numbers, pronunciation substitutions, and acronyms can produce false positives.
Listen to flagged passages; transcript checks cannot certify perceptual quality.

Assembly verifies passage hashes and formats, inserts pauses, and derives chapter
timestamps from sample counts. It retains `audiobook_unmastered.flac`, measures
loudness and peak level, and applies constant gain targeting -19 LUFS without
exceeding -2 dBTP. When those targets conflict, it accepts a quieter result.

Outputs are `audiobook.flac` and mono `audiobook.ogg` encoded with Opus at nominal
256 kbit/s VBR. The Ogg includes Vorbis chapter tags; `chapters.txt` and
`chapters.json` provide timestamps for players without chapter support.
