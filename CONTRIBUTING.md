# Contributing

Keep changes focused and describe the behavior they affect. Include a
reproduction for bugs and a regression test when practical. Update the matching
example and documentation when changing configuration.

## Layout

- `services/` contains application source and dependencies. Watchers and the location
  tracker share `docker/watcher/Dockerfile`, with separate per-service lockfiles.
- `shared/stack_shared/` contains common LLM, HTTP, calendar, and Signal helpers.
- `services/signal-bot/skills/` contains independently discovered bot skills.
- `services/signal-bot/patches/` and `patches/` contain upstream integration patches.
- `scripts/` contains setup, maintenance, and verification commands.
- `scripts/audiobook/` contains standalone narration, audio checking, and export tools.
- `config/` contains service configuration and host templates.
- `examples/` contains environment-file examples and the knowledge-base template.
- `docs/` describes current interfaces, configuration, and operation.
- Root Compose files and launchers are stable deployment entry points.

Do not commit credentials, private hostnames, personal subscriptions, generated
media, or deployment records. Keep incident reports, upgrade journals, benchmark
runs, and personal setup notes in a private operations repository.

## Development

Production Compose uses bundled code. Opt into source mounts while developing:

```bash
docker compose -f docker-compose.server.yml -f docker-compose.server.dev.yml up -d --build signal-bot voice-agent
```

Restart affected processes after editing mounted Python. Dependency changes
still require a rebuild. The AI host has a corresponding `docker-compose.ai.dev.yml`.
The overrides retain production data volumes; use separate local configuration
and a separate Docker environment when you need isolated test data.

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
| Discovery and polling | `python3 -m unittest discover -s tests -p 'test_runtime_helpers.py' -v` |
| Release packaging | `python3 -m unittest discover -s tests -p 'test_release.py' -v` |
| Bot patch failure checks | `python3 -m unittest discover -s services/signal-bot/patches -p 'test_patches.py' -v` |
| Shared MCP and LLM clients | `python3 -m unittest discover -s tests -p 'test_shared_clients.py' -v` |
| Gateway | `python3 -m unittest discover -s services/public-api-gateway -p 'test_*.py' -v` |
| RSS watcher | `PYTHONPATH=shared:services/rss-watcher python3 -m unittest discover -s services/rss-watcher/tests -v` |
| HTTP and tool boundaries | `PYTHONPATH=shared python3 -m unittest discover -s tests -p 'test_security_boundaries.py' -v` |
| Internal authentication and tool credentials | `PYTHONPATH=shared python3 -m unittest discover -s tests -p 'test_internal_auth.py' -v` |
| Signal images | `python3 -m unittest discover -s services/signal-bot/patches -v` |
| Image-search uploads | `PYTHONPATH=shared python3 -m unittest discover -s services/reverse-image-search -p 'test_*.py' -v` |
| Audio adapters | `PYTHONPATH=services/audio-api python3 -m unittest discover -s services/audio-api/tests -v` |
| Music trimming | `python3 services/signal-bot/skills/music_download/test_trim.py` |

The shared-client suite uses `tests/requirements.txt` and mocked transports; it
does not call models or running services. CI runs it alongside the baseline checks.
The internal-authentication suite uses the same dependencies, the pinned proxy
loader, and local stdio MCP subprocesses. It needs no provider credentials,
models, or running services.

The audio suite needs the audio image's dependencies and ffmpeg but mocks model
inference. GPU listening evaluations are separate manual checks under
`services/audio-api/evaluation/`; keep their generated results outside the repository.

## Dependencies and patches

Use each service's existing dependency manager and update its lockfile alongside
its manifest. Preserve pinned images, models, and upstream revisions unless
updating them intentionally. Explain compatibility workarounds next to the code
and verify patches against the exact upstream version used by the build. Bot
patches live in `services/signal-bot/patches/*.patch`; the installer checks all hunks and
Python syntax before replacing source. Rebuild the bot to validate against its
pinned upstream revision, and review every patch when changing that revision.
Bot and voice constraints pin their runtime dependencies; update those files
intentionally alongside compatibility tests.

Refresh uv projects with `uv lock --upgrade --project services/<service>`.
For services using requirements and constraints, regenerate the constraints with
`uv pip compile requirements.txt --upgrade --python-version 3.12 --no-header
--no-annotate --no-emit-index-url -o constraints.txt` from the service directory.
Use Python 3.13 for the MCP proxy and 3.11 for memory; the bot writes its output
to `patches/constraints.txt`. Keep the declared SDK compatibility limits and
explicit GPU/embedding runtime versions unless testing their migration.

External Docker build images are pinned by digest. Updating a tag alone does not
update its digest. Resolve the new digest, build candidate images, run the affected
tests in those images, and check `pip check` before adopting a release. Local tests
run before committing; CI repeats them independently on the committed source.

Avoid unrelated formatting, dependency upgrades, and service restarts in a
refactor. Changes to model IDs, APIs, volume names, and database schemas need
explicit installation guidance.

## Pull requests

Describe the problem, resulting behavior, and checks run. Call out changed
configuration and installation steps. Keep development narratives in the pull
request rather than adding them to the documentation.
