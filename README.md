# Local AI Stack

A self-hosted assistant stack with local model serving, web and Signal chat,
speech, image generation, search, and scheduled integrations.

Application services run in Docker Compose. GPU services combine Compose with
native model launchers and can run on a separate host. Operators supply model
weights, credentials, personal data, and deployment settings.

## Getting started

Follow the [setup guide](docs/setup.md) for prerequisites, configuration, and
startup. Review [model serving](docs/models.md) before downloading weights: the
supplied profile runs several models and needs substantial GPU memory.

| Entry point | Purpose |
| --- | --- |
| [docker-compose.server.yml](docker-compose.server.yml) | LibreChat, Signal, tools, watchers, and Nextcloud |
| [docker-compose.ai.yml](docker-compose.ai.yml) | Speech, memory, and vector storage |
| [llama-swap.yaml](config/llama-swap.yaml) | Chat, autocomplete, images, and reranking |
| [.env.example](.env.example) | Endpoints, host paths, and integration settings |

Most service ports are intended for a trusted network. Public chat access uses a
separate [authenticated gateway](docs/public-openai-api.md).

## Documentation

- [Architecture and service map](docs/architecture.md)
- [Deployment configuration](docs/deployment.md)
- [Models and GPU allocation](docs/models.md)
- [Search and MCP tools](docs/tools.md)
- [Browser agent](docs/browser-agent.md)
- [Audio and voice chat](docs/audio.md)
- [On-demand audiobooks](scripts/audiobook/README.md)
- [Image generation and editing](docs/qwen-image-2.1.md)
- [Signal bot](docs/signal.md)
- [Scheduled watchers](docs/watchers.md)
- [Operations and backups](docs/operations.md)

The [knowledge-base template](examples/knowledge-base/GUIDE.md) is a standalone companion
for organizing source documents and generated notes.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) for the layout and development checks.
Keep installation-specific values and operational records in local files or a
separate private deployment repository.

Original code is available under the [MIT license](LICENSE). Dependencies, data,
patches, and model weights retain their own terms; see
[third-party notices](THIRD_PARTY_NOTICES.md).
