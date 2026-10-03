# Public OpenAI API through Cloudflare Tunnel

This stack exposes only the selected chat models through a separate local
gateway. Private clients can continue using the internal model routes.

```text
Internet -> api.example.com -> Cloudflare -> cloudflared in WSL
         -> 127.0.0.1:8093 strict gateway -> [::1]:8080 llama-swap
         -> selected vLLM service on 127.0.0.2
```

The public gateway:

- permits only `GET /v1/models`, `GET /v1/models/<model>`,
  `POST /v1/chat/completions`, `POST /v1/completions`, and
  `POST /v1/responses`;
- returns 404 for all other paths, including vLLM management routes;
- requires `Authorization: Bearer <key>` on every `/v1/*` request;
- filters requests and `/v1/models` to `qwen3.8-27B-FP8` and
  `qwen3.6-35B-A3B-FP8`;
- strips the public credential before forwarding;
- emits no-store cache headers and streams upstream bytes without buffering.

`VLLM_API_KEY` is intentionally not set. Adding it would change existing
private clients, and vLLM documents that its key does not protect every raw
inference endpoint. Authentication therefore happens after the strict public
path gate and before llama-swap.

## Local services

Initialize local secrets and install the pinned gateway dependencies:

```bash
./scripts/init-public-api-secrets.sh
cd public-api-gateway
UV_CACHE_DIR=/tmp/public-api-uv-cache uv sync --frozen --no-dev
cd ..
```

Install the checksum-pinned `cloudflared` binary beside the stack:

```bash
./scripts/install-cloudflared-public-api.sh
```

Render the unit templates for this checkout, then link the generated files.
Enable user lingering separately if these services should survive logout.
The tunnel service stays disabled until a real token exists.

```bash
python3 scripts/render-systemd.py
systemctl --user link "$PWD/.local/systemd/public-api-gateway.service" \
  "$PWD/.local/systemd/llama-swap-private-relays.service" \
  "$PWD/.local/systemd/cloudflared-public-api.service"
systemctl --user daemon-reload
systemctl --user enable --now public-api-gateway.service \
  llama-swap-private-relays.service
```

Store the tunnel token without putting it in shell history:

```bash
./scripts/set-cloudflared-token.sh
systemctl --user enable --now cloudflared-public-api.service
```

## Cloudflare dashboard configuration

Use your own domain and tunnel. These steps publish the selected API endpoints.

1. In **Zero Trust > Networks > Tunnels**, create a Cloudflared tunnel named
   `local-ai-wsl` (or open the tunnel whose token was supplied).
2. Under **Routes**, add a **Published application** route:
   - Subdomain: `api`
   - Domain: `example.com`
   - Path: `^/v1/.*$`
   - Service type: `HTTP`
   - Service URL: `127.0.0.1:8093`
3. Leave HTTP/2-to-origin disabled and do not enable **No TLS Verify**. The
   loopback origin is plain HTTP and SSE uses HTTP/1.1 chunked streaming.
4. Ensure the generated tunnel configuration retains its final unmatched
   `http_status:404` rule. The local gateway is a second independent 404 gate.
5. In the `example.com` zone, open **Rules > Cache Rules** and create
   `Bypass OpenAI API cache` with this expression:

   ```text
   (http.host eq "api.example.com" and starts_with(http.request.uri.path, "/v1/"))
   ```

   Set **Cache eligibility** to **Bypass cache**. Place it after any broader
   rule that makes content cache-eligible, because the last conflicting Cache
   Rule wins.

Creating the Published application route creates or changes the proxied DNS
record for `api.example.com`. Apply it only when you intend to publish this API.

## Validation

Local validation uses the ignored bearer key without printing it:

```bash
./scripts/validate-public-api.sh
```

After the hostname is live, validate the same path through Cloudflare:

```bash
PUBLIC_API_BASE_URL=https://api.example.com ./scripts/validate-public-api.sh
```

## Disable public access

Remove public access immediately while retaining the safer local listeners and
the private IPv4/Docker compatibility relays:

```bash
systemctl --user disable --now cloudflared-public-api.service \
  public-api-gateway.service
systemctl --user unlink cloudflared-public-api.service \
  public-api-gateway.service
systemctl --user daemon-reload
```

Also remove the Published application route and Cache Rule in the Cloudflare
dashboard. Stopping the tunnel and gateway removes public access while keeping
local inference and private relays available.
