"""Pinned proxy entrypoint with authenticated ingress and per-tool credentials."""
import argparse
import asyncio
import os

from mcp_proxy.config_loader import load_named_server_configs_from_file
from mcp_proxy import mcp_server
from starlette.applications import Starlette

from stack_shared.auth_middleware import BearerAuthMiddleware


TOOL_ENVIRONMENT = {
    "github": ("GITHUB_TOKEN",),
    "google-maps": ("GOOGLE_MAPS_API_KEY",),
    "browser": ("BROWSER_AGENT_API_TOKEN",),
}
PRIVATE_IDENTITIES = {"github": 11001, "google-maps": 11002, "browser": 11003}


def load_servers(path, environment):
    # The pinned loader does not interpolate variables. Supply secrets only to
    # the declared tool; the SDK retains its minimal PATH/HOME environment.
    servers = load_named_server_configs_from_file(path, {})
    for name, params in servers.items():
        params.env = dict(params.env or {})
        for key in TOOL_ENVIRONMENT.get(name, ()):
            if environment.get(key):
                params.env[key] = environment[key]
    return servers


def isolate_servers(servers):
    """Run credentialed tools under distinct identities, outside broker UID 0."""
    for name, params in servers.items():
        uid = PRIVATE_IDENTITIES.get(name, 11000)
        params.env["HOME"] = f"/home/tool-{uid}"
        params.env["UV_CACHE_DIR"] = f"/home/tool-{uid}/.cache/uv"
        params.env["UV_TOOL_DIR"] = f"/home/tool-{uid}/.cache/uv/tools"
        params.env["XDG_CACHE_HOME"] = f"/tmp/tool-cache-{uid}"
        # Maps' reviewed environment is installed read-only at image build,
        # so an uncredentialed uv worker cannot modify its executable code.
        if (name == "google-maps" and params.command == "uv"
                and params.args[-2:] == ["python", "/opt/gmaps-searchtext-shim.py"]):
            params.command = "/opt/maps/bin/python"
            params.args = ["/opt/gmaps-searchtext-shim.py"]
        params.args = ["/opt/run_tool.py", str(uid), params.command, *params.args]
        params.command = "python"
    return servers


def authenticated_application(token):
    # Validate before launching any subprocesses. The pinned proxy constructs
    # its root app through this class; protect all transports before routing.
    BearerAuthMiddleware(None, token)

    class AuthenticatedApplication(Starlette):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.add_middleware(BearerAuthMiddleware, token=token)

    return AuthenticatedApplication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--named-server-config", default="/config.json")
    args = parser.parse_args()
    mcp_server.Starlette = authenticated_application(os.environ.get("MCP_PROXY_AUTH_TOKEN", ""))
    servers = isolate_servers(load_servers(args.named_server_config, os.environ))
    asyncio.run(mcp_server.run_mcp_server(
        mcp_server.MCPServerSettings(bind_host=args.host, port=args.port),
        named_server_params=servers,
    ))


if __name__ == "__main__":
    main()
