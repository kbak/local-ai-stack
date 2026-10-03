from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Transport(BaseModel):
    mode: Literal["flight", "train", "bus"]
    source_code: str = ""
    destination_code: str = ""
    source_name: str
    destination_name: str
    source_location: str
    departure: datetime
    arrival: datetime
    booking_codes: list[str] = Field(default_factory=list)
    service_number: str = ""


class Hotel(BaseModel):
    name: str
    location: str
    city: str = ""
    check_in: datetime
    check_out: datetime | None = None


class Itinerary(BaseModel):
    is_travel: bool = False
    confidence: Literal["high", "medium", "low"] = "low"
    transports: list[Transport] = Field(default_factory=list)
    hotels: list[Hotel] = Field(default_factory=list)
