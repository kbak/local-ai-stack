# Browser agent

`browser-agent-api` provides a generic asynchronous HTTP interface over Browser
Use and the local OpenAI-compatible Qwen endpoint. It is deliberately separate
from site-specific prompts and workflows.

Submit a task:

```bash
curl -X POST http://127.0.0.1:8092/v1/tasks \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $BROWSER_AGENT_API_TOKEN" \
  -d '{
    "task": "Extract the first three quotes and their authors",
    "start_url": "https://quotes.toscrape.com/",
    "allowed_domains": ["quotes.toscrape.com"],
    "max_steps": 10
  }'
```

Poll `GET /v1/tasks/<task_id>` for `queued`, `running`, `completed`, or
`failed`. Compose runs a self-hosted Steel browser on the mini PC. Each API task
creates an isolated Steel session, connects through its returned CDP WebSocket,
and releases the session afterward. Steel is isolated on an internal Docker
network and routes browser traffic through the public-only `public-egress` proxy.
Local Chromium and external CDP fallbacks are disabled; browser tasks require
this isolated Steel deployment. Steel's UI is host-local on port 3090. The
agent API is also bound to loopback by default; set `BROWSER_AGENT_API_TOKEN`
before exposing it to the LAN.

For image-heavy pages, add `image_analysis`. The browsing agent only opens the
relevant gallery; a deterministic stage then traverses the DOM and shadow DOM,
downloads the largest discovered assets, and sends them to Qwen in small
vision batches. Results include the source URL for every analyzed image, the
individual batch reports, and a merged `image_analysis_summary`:

```json
{
  "task": "Open the product listing and its photo gallery",
  "start_url": "https://example.com/product/123",
  "allowed_domains": ["example.com", "images.examplecdn.com"],
  "max_steps": 12,
  "use_vision": true,
  "image_analysis": {
    "prompt": "Report visible wear or damage; do not infer hidden defects.",
    "max_images": 20,
    "batch_size": 4
  }
}
```
