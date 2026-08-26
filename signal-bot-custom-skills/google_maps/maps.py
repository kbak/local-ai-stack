"""Google Maps tools via local MCP proxy."""

import json
import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/google-maps/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> str:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        init = client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "signal-bot", "version": "1.0"}},
        })
        init.raise_for_status()
        session_id = init.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No session ID returned")
        resp = client.post(MCP_URL, headers={**headers, "mcp-session-id": session_id}, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        result = data.get("result", {})
        content = result.get("content", [])
        text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        if result.get("isError"):
            raise RuntimeError(text or f"MCP tool {tool_name} failed")
        return text


def _coordinates(location: str) -> str:
    """Return ``lat,lng`` for either coordinates or a human-readable place."""
    parts = [part.strip() for part in location.split(",")]
    if len(parts) == 2:
        try:
            lat, lng = map(float, parts)
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return f"{lat},{lng}"
        except ValueError:
            pass

    response = json.loads(_call_mcp("geocode_address", {"address": location}))
    point = response.get("data", {}).get("location", {})
    if "lat" not in point or "lng" not in point:
        raise RuntimeError(f"Could not resolve location: {location}")
    return f"{point['lat']},{point['lng']}"


@tool
def search_places(query: str, location: str = "") -> str:
    """Search for places using Google Maps — restaurants, cafes, venues, attractions, etc.

    Returns names, addresses, ratings, and opening hours for matching places.

    Args:
        query: What to search for (e.g. 'sushi restaurant', 'coffee near me', 'jazz bar Lisbon').
        location: Optional location context to bias results (e.g. 'São Paulo, Brazil').
    """
    try:
        # The upstream Maps MCP search requires a coordinate bias. When the
        # caller omits a separate location, geocoding the full query still
        # handles searches such as "SEN club Warsaw" or "cafes in Lisbon".
        search_location = location or query
        return _call_mcp("search_places", {
            "location": _coordinates(search_location),
            "keyword": query,
        })
    except Exception as e:
        return f"Places search failed: {e}"


@tool
def get_directions(origin: str, destination: str, mode: str = "driving") -> str:
    """Get directions and travel time between two places using Google Maps.

    Args:
        origin: Starting point (address, place name, or coordinates).
        destination: End point (address, place name, or coordinates).
        mode: Travel mode — 'driving', 'walking', 'bicycling', or 'transit'.
    """
    try:
        return _call_mcp("get_directions", {"origin": origin, "destination": destination, "mode": mode})
    except Exception as e:
        return f"Directions lookup failed: {e}"


@tool
def geocode(address: str) -> str:
    """Convert an address or place name to coordinates, or coordinates to an address.

    Args:
        address: Address, place name, or 'lat,lng' coordinates to look up.
    """
    try:
        return _call_mcp("geocode_address", {"address": address})
    except Exception as e:
        return f"Geocoding failed: {e}"
