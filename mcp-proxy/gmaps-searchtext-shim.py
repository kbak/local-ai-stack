"""Launcher shim for google-maps-mcp-server 0.2.1.

Upstream's PlacesTool._search_nearby_new_api calls the New Places API's
searchNearby with empty included_types and then does client-side keyword
filtering. When the 20 nearest POIs don't match the keyword, results are
empty. This shim swaps the method to use searchText, which has native
query support in the New API.

Invoked in place of `google-maps-mcp-server` by mcp-proxy. Does not touch
the installed package on disk.
"""

from typing import Any

from google.api_core import client_options
from google.maps import places_v1
from google.type import latlng_pb2

from google_maps_mcp_server.server import main
from google_maps_mcp_server.tools.places import PlacesTool


def _search_via_text(
    self: PlacesTool,
    lat: float,
    lng: float,
    radius: float,
    keyword: str,
    place_type: str | None = None,
) -> list[dict[str, Any]]:
    opts = client_options.ClientOptions(api_key=self.settings.google_maps_api_key)
    client = places_v1.PlacesClient(client_options=opts)

    request = places_v1.SearchTextRequest(
        text_query=keyword or (place_type or ""),
        location_bias=places_v1.SearchTextRequest.LocationBias(
            circle=places_v1.Circle(
                center=latlng_pb2.LatLng(latitude=lat, longitude=lng),
                radius=radius,
            )
        ),
        included_type=place_type or "",
        max_result_count=min(20, self.settings.max_results),
    )

    field_mask = (
        "places.displayName,places.formattedAddress,places.location,"
        "places.rating,places.types,places.id"
    )

    response = client.search_text(
        request=request, metadata=[("x-goog-fieldmask", field_mask)]
    )

    out: list[dict[str, Any]] = []
    for place in response.places:
        out.append(
            {
                "name": place.display_name.text if place.display_name else None,
                "address": place.formatted_address if place.formatted_address else None,
                "location": {
                    "lat": place.location.latitude if place.location else None,
                    "lng": place.location.longitude if place.location else None,
                },
                "rating": place.rating if hasattr(place, "rating") else None,
                "types": list(place.types) if place.types else [],
                "place_id": place.id if place.id else None,
            }
        )
    return out


PlacesTool._search_nearby_new_api = _search_via_text

if __name__ == "__main__":
    main()
