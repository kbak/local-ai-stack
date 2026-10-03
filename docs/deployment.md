# Deployment configuration

This public repository contains reusable source, example settings, and service
definitions. Hostnames, GPU selections, user names, recipients, local paths, and
operational records belong to an installation.

## Local files

Copy `.env.example` and the required `*.env.example` files to their ignored
runtime names. Startup scripts read `.env`; Compose also loads service-specific
environment files. Keep values containing spaces quoted for shell compatibility.

| Setting | Purpose |
| --- | --- |
| `STACK_DOMAIN`, `ACME_EMAIL` | HTTPS hostnames and certificate contact |
| `LLM_BASE_URL`, `AUDIO_API_URL`, `MEMORY_MCP_URL`, `YTDLP_SERVICE_URL` | Routes between hosts |
| `MEMORY_ALLOWED_HOSTS`, `MEMORY_ALLOWED_ORIGINS` | Memory MCP proxy allowlist |
| `MEMORY_DEFAULT_USER_ID`, `TIER1_AGENT_NAME` | Memory scope and LibreChat agent selection |
| `PRIMARY_GPU`, `SECONDARY_GPU`, `EXPECTED_AUDIO_GPU` | Device selection and optional audio-device name check |
| `MEMORY_DIR`, `VOICE_SAMPLES_DIR`, `MUSIC_HOST_DIR` | Private host data directories |
| `LOCAL_TIMEZONE`, `BLOG_TIMEZONE` | Calendar and weekly digest timezones |
| `SIGNAL_CALL_GREETING`, `SIGNAL_OFFLINE_REPLIES_FILE` | Optional bot presentation settings |
| `AI_BRIDGE_ADDRESS` | Private Docker-to-llama-swap relay address |

`BLOG_TIMEZONE` belongs in `rss-watcher.env`. Bot group prefixes and account
settings belong in `signal-bot.env`. See the examples for other integrations.

## Separate private repository

A deployment repository can store non-secret host settings, custom proxy
configuration, and operations records. Keep credentials and personal data out of
its Git history too: use encrypted secrets or files provisioned on the host.

For example:

```text
local-ai-stack/                # this public source repository
local-ai-deployment/           # separate private repository
  server/                     # host configuration and proxy settings
  ai/                         # GPU/model overrides and service settings
  operations/                 # private maintenance records
```

Provision the resulting `.env` and service environment files at the paths this
stack expects. They can be symlinks to protected files outside the public
checkout; resolve relative paths from the public checkout when using Compose.
Do not add the private repository as a public submodule or copy its contents
into a Docker build context.

For custom services or volumes, keep a Compose override in the private repo and
pass both files explicitly:

```bash
docker compose -f docker-compose.server.yml -f ../local-ai-deployment/server/compose.yml config --quiet
```

Pin the public source revision in the deployment repository so an installation
can be reproduced. Review resolved configuration before restarting services.

## Host service templates

`systemd/*.service` files contain `@STACK_ROOT@` placeholders. Render them for the
installation path before linking or copying them into systemd:

```bash
python3 scripts/render-systemd.py
```

The generated files go to ignored `.local/systemd/`. Rendering does not install,
restart, or enable anything. If an existing installation links directly to the
tracked units, replace those links with the generated units before reloading
systemd. Installed Caddy and cron configuration also need their host values
supplied at installation time.

The units use `ProtectHome=true`. Install their checkout outside home directories,
such as `/opt/local-ai-stack`, and use `--root /opt/local-ai-stack` when rendering
for that location.

## Existing installations

Before adopting generic defaults, set the installation's actual endpoints,
agent name, timezones, audio GPU name check, greeting, and memory allowlist
explicitly. Keep those settings on every host that uses them. Existing volumes,
model IDs, API paths, and database contents do not need migration.
