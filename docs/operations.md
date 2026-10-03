# Operations

Run commands from the repository root. Use the Compose file for the host being
managed; service and volume names are stable across restarts.

## Inspect services

```bash
docker compose -f docker-compose.server.yml ps
docker compose -f docker-compose.server.yml logs --tail 100 librechat
curl --fail http://localhost:8080/running
```

The llama-swap UI at `/ui` lists loaded workers and supports manual load/unload.
Use a service's `/health` endpoint where available. Avoid posting raw logs or
resolved configuration publicly: they can contain user data or credentials.

## Apply changes

An environment-file change requires container recreation, not just a restart:

```bash
docker compose -f docker-compose.server.yml up -d --no-deps librechat
docker compose -f docker-compose.ai.yml up -d --no-deps audio-api
```

Production application code is bundled in images. Editing shared helpers,
skills, or frontend files takes effect only after rebuilding and recreating the
relevant services. Model launcher or llama-swap configuration changes still
require restarting the affected model worker or router.

Build a release from a clean, committed checkout:

```bash
python3 scripts/build-release.py signal-bot voice-agent rss-watcher
```

The helper builds from a Git archive, excludes private/untracked files, labels
and tags images with the full commit, and refuses to overwrite an existing
revision tag. It prints the deployment command. Set `STACK_VERSION` in local
`.env` to that revision when adopting it as the installation's default. Build
all services you intend to recreate with that version; when deploying a subset,
use the printed `--no-deps` command with dependencies already running.

To roll back, use the previous revision's Compose file and local configuration,
set `STACK_VERSION` to its image tag, and run `up -d --no-build --pull never` for
the affected services. Keep those images until the next release is verified.
Data volumes are retained; code rollback does not undo application data changes.
For the AI host, use `build-release.py --host ai`; deploy each host independently.

For development source mounts, see [contributing](../CONTRIBUTING.md).

## Persistent data and backups

MongoDB stores LibreChat history. Qdrant stores memory vectors. Signal account
state, watcher state, and Nextcloud data use named volumes. Host directories
hold memory documents, music, voice samples, and other private inputs. Do not
remove volumes when applying configuration changes.

`scripts/backup-nextcloud.sh` creates an encrypted archive in `MEMORY_DIR` using
Nextcloud's maintenance mode, a database dump, and copies of data/configuration.
`scripts/restore-nextcloud.sh` restores that archive; read the script before use.
Adapt the path in `scripts/nextcloud-backup.cron` before installing the schedule.
Back up Qdrant and other state separately using their supported snapshot tools.
Test restores without replacing a live installation's data.

## Network and data boundaries

Search and external integrations contact their configured providers even though
the model runs locally. Reverse image search uploads selected images to
Litterbox with a one-hour expiry and sends image URLs to external providers.

The MCP proxy has no authentication; restrict it to trusted clients. The
location tracker requires a bearer token. Browser traffic uses isolated Steel
and the public-egress proxy; local-browser and external-CDP fallbacks are
disabled. Image and PDF downloads reject private destinations. Receipt rows are
written as raw values so email text cannot execute spreadsheet formulas.

Use the [public API gateway](public-openai-api.md) for external chat access.
Keep upgrade records and installation-specific validation results in your
private operations repository.
