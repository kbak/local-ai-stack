# Contributing

Keep changes focused and describe the behavior they affect. Include a
reproduction for bugs and a regression test when practical. Update the matching
example and documentation when changing configuration.

## Layout

- Service directories contain their Dockerfile, source, and dependencies.
- `shared/stack_shared/` contains common LLM, HTTP, calendar, and Signal helpers.
- `signal-bot-custom-skills/` contains independently discovered bot skills.
- `signal-bot-patches/` and `patches/` contain upstream integration patches.
- `scripts/` contains setup, maintenance, and verification commands.
- `docs/` describes current interfaces, configuration, and operation.
- Root Compose files and launchers are stable deployment entry points.

Do not commit credentials, private hostnames, personal subscriptions, generated
media, or deployment records. Keep incident reports, upgrade journals, benchmark
runs, and personal setup notes in a private operations repository.

## Checks

CI uses Python 3.12, Node.js 22, Bash, and Docker Compose. Baseline checks need no
models, credentials, running containers, or network access:

```bash
python3 scripts/check-repo.py
node scripts/test-librechat-render.cjs
python3 -m unittest discover -s tests -p 'test_configuration.py' -v
python3 scripts/check-compose.py
git diff --check
```

`check-compose.py` renders both Compose files in a temporary checkout using only
example values. It does not start services or read your local environment files.

Run affected service tests in that service's dependency environment:

| Area | Command from repository root |
| --- | --- |
| Gateway | `python3 -m unittest discover -s public-api-gateway -p 'test_*.py' -v` |
| RSS watcher | `PYTHONPATH=shared:rss-watcher python3 -m unittest discover -s rss-watcher/tests -v` |
| HTTP and tool boundaries | `PYTHONPATH=shared python3 -m unittest discover -s tests -p 'test_security_boundaries.py' -v` |
| Signal images | `python3 -m unittest discover -s signal-bot-patches -v` |
| Audio adapters | `PYTHONPATH=audio-api python3 -m unittest discover -s audio-api/tests -v` |
| Music trimming | `python3 signal-bot-custom-skills/music_download/test_trim.py` |

The audio suite needs the audio image's dependencies and ffmpeg but mocks model
inference. GPU listening evaluations are separate manual checks under
`audio-api/evaluation/`; keep their generated results outside the repository.

## Dependencies and patches

Use each service's existing dependency manager and update its lockfile alongside
its manifest. Preserve pinned images, models, and upstream revisions unless
updating them intentionally. Explain compatibility workarounds next to the code
and verify patches against the exact upstream version used by the build.

Avoid unrelated formatting, dependency upgrades, and service restarts in a
refactor. Changes to model IDs, APIs, volume names, and database schemas need
explicit installation guidance.

## Pull requests

Describe the problem, resulting behavior, and checks run. Call out changed
configuration and installation steps. Keep development narratives in the pull
request rather than adding them to the documentation.
