# Signal bot

The bot routes Signal messages to local models, MCP tools, and custom skills.
`services/signal-bot/Dockerfile` builds a pinned uoltz fork with the integration patches
in this repository. Speech uses audio-api; media downloads use yt-dlp-service.

## Setup

Copy `examples/env/signal-bot.env.example` to `signal-bot.env`. Configure `SIGNAL_NUMBER`,
`BRIEFING_RECIPIENT`, and any integration credentials. Set `ALLOWED_NUMBERS` to
restrict senders; an unset list allows anyone who messages the account.

Start the transport and link an existing Signal account:

```bash
docker compose -f docker-compose.server.yml up -d signal-api
docker exec -it signal-api signal-cli-rest-api link -n "local-ai-bot"
```

Account state persists in the `signal-cli-data` volume. Then start the bot:

```bash
docker compose -f docker-compose.server.yml up -d --build signal-bot
```

Groups activate the bot through `BOT_GROUP_PREFIX` or a mention of its number.
Set the prefix in the local environment file. Cross-host URLs and optional
presentation settings are listed in [deployment configuration](deployment.md).

## Skills

Custom skills live in `services/signal-bot/skills/`. Each directory provides a
`skill.yaml` manifest and Python implementation, discovered at startup. Shared
skill helpers live in `_shared/`. Images bundle skills outside the persistent
bot data directory, at `/app/custom_skills`; browser voice uses `/app/skills`.

Both clients load only `module:function` entries listed under `tools`. Optional
`runtimes: [signal]` or `runtimes: [voice]` restricts discovery; omitting it enables
both. Image generation is Signal-only because it requires conversation context
and Signal delivery. Unlisted Python files, including tests, are never scanned
for tools. Rebuild after changing manifests or implementation, or use the
[development override](../CONTRIBUTING.md#development).

| Skills | Purpose |
| --- | --- |
| arxiv, github, searxng, pdf | Research and document tools |
| google_maps, weather, time | Places, forecasts, and timezone tools |
| currency, finance | Exchange rates and market information |
| image_generation, image_search | Local generation/editing and image identification |
| music_download, music_library | Download and search music under `MUSIC_HOST_DIR` |
| sample_download, voices_list, tts_clone | Create, list, and use reference voices |
| roast | Multi-speaker generated audio |

Manifests define the supported arguments. The bot exposes direct commands from
these skills; conversational tool use shares the same implementations. See
[image generation](qwen-image-2.1.md) and [audio](audio.md) for their APIs.

Image attachments and image-search uploads accept up to 20 MiB per image. The
image-search HTTP limit includes room for base64 and JSON overhead. Retained
editing references also have a 16-megapixel limit.

Replies use the quoted message's original image when its attachment metadata
was received by the bot, including group messages that did not activate it.
The conversation-scoped metadata index survives restarts and retains up to 200
image messages for seven days. A quote thumbnail is used when the original is
unavailable and Signal supplies one. Missing quoted images never select another
conversation image. Unquoted follow-up requests can implicitly reuse the latest
image for one hour; older images require an explicit reference or a new upload.

If model inference is unavailable, the bot chooses a response from the configured
offline-reply file. Supply a private file through `SIGNAL_OFFLINE_REPLIES_FILE`
to customize the wording; use one reply per line.

## Experimental calling

The Signal transport includes a pinned signal-call-tunnel build, PulseAudio, and
a call bridge. It accepts only the normalized `BRIEFING_RECIPIENT` number,
rejects concurrent calls, records incoming audio to temporary storage, plays a
locally generated greeting, and hangs up. Call audio does not enter the LLM.

`SIGNAL_CALL_GREETING` is a build-time setting. Rebuild signal-api to change it.
Inspect the bridge with:

```bash
docker exec signal-api supervisorctl status
docker exec signal-api tail -100 /var/log/signal-call-bridge.log
```

Validate calling when changing signal-cli, RingRTC, or the tunnel revision.
