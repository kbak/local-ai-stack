# Setup

Run commands from the repository root. Configure only the integrations you plan
to use; start named services when you do not need the full stack.

## Prerequisites

The server host needs Docker Engine with Compose and Bash. The AI host also
needs a compatible NVIDIA driver, CUDA-capable container runtime, llama-swap,
and the model runtimes described in [models](models.md). Startup scripts use
`curl` and `jq`. Model weights and caches live outside this checkout by default.

The supplied profile is resource-intensive. GPU selection is configurable; no
particular workstation brand or card model is required by the repository.
Memory capacity, CUDA support, and model compatibility still constrain which
workers can run together.

## Local configuration

Copy missing examples without overwriting existing files:

```bash
for example in .env.example *.env.example; do
    target="${example%.example}"
    [ -e "$target" ] || cp "$example" "$target"
done
```

The server Compose file references all service environment files even when only
some services are selected. Populate the settings for the services you use:

- In `.env`, set strong secrets, cross-host endpoints, and the absolute
  `MEMORY_DIR`, `VOICE_SAMPLES_DIR`, and `MUSIC_HOST_DIR` paths. Quote values with
  spaces because the startup scripts also load this file as shell syntax.
- Set `PRIMARY_GPU`, `SECONDARY_GPU`, and optionally `EXPECTED_AUDIO_GPU` on the
  AI host. Audio startup requires exactly one visible GPU; the optional expected
  name provides an additional hardware check.
- Set `LOCAL_TIMEZONE` for calendar/location interpretation and `BLOG_TIMEZONE`
  in `rss-watcher.env` for the optional weekly digest. Defaults are UTC.
- Configure Signal using [the Signal guide](signal.md); watchers use its account
  and recipient. Configure other integrations using their matching examples.
- Copy `rss-watcher/blog-sources.example.json` to `rss-watcher/blog-sources.json`
  before starting the RSS service, and replace the example subscriptions.

Generate a secret with `openssl rand -hex 32`. Use different values for unrelated
credentials. Keep real configuration in ignored files or a
[private deployment repository](deployment.md).

## Networking

The server Compose file creates its own bridge. The AI Compose file expects an
external `stack_ai-net` bridge on the AI host. Create that bridge once, choosing
a subnet that does not overlap your other networks:

```bash
docker network inspect stack_ai-net >/dev/null 2>&1 || \
    docker network create --subnet 172.18.0.0/16 --gateway 172.18.0.1 stack_ai-net
```

Cross-host endpoints must be reachable from containers. Set `LLM_BASE_URL`,
`AUDIO_API_URL`, `MEMORY_MCP_URL`, and `YTDLP_SERVICE_URL` to the appropriate
private routes. Defaults use `host.docker.internal`; they do not discover a
remote AI host. Set memory's allowed hosts and origins to match its proxy URL.

Native inference binds to loopback. The [private relays](public-openai-api.md#local-services)
bridge IPv4 and Docker clients to llama-swap's IPv6 listener. Configure the
`AI_BRIDGE_ADDRESS` to match your network's gateway. HTTPS proxy templates are under `caddy/`;
set `STACK_DOMAIN`, `ACME_EMAIL`, and the DNS provider token before installing.

## Validate and start

```bash
docker compose -f docker-compose.server.yml config --quiet
docker compose -f docker-compose.ai.yml config --quiet
```

On the AI host, install the model runtimes and weights, then run:

```bash
./start-ai.sh
```

This starts llama-swap, warms the configured workers, and starts GPU services.
Cold model compilation can take several minutes. It preserves a running main
chat model and otherwise loads the configured startup default.

On the server host, build the local images before starting the full stack:

```bash
docker compose -f docker-compose.server.yml build
./start-server.sh
```

For revision-tagged releases, use [the release helper](operations.md#apply-changes).
To build and start selected services:

```bash
docker compose -f docker-compose.server.yml up -d --build librechat
```

Open LibreChat at `http://localhost:3000`. The llama-swap UI is at
`http://localhost:8080/ui` on the AI host. See [operations](operations.md) for
logs, configuration updates, and backups.
