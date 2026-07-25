"""rapp-coop: several twins, one world, no collisions.

A twin is any participant -- a person or a model. This package gives them a
shared chat and expiring claims so concurrent work does not corrupt itself.
"""

from .coop import (
    CLAIM_TTL,
    DEFAULT_CHANNEL,
    PRESENCE_TTL,
    RESOURCES,
    Claim,
    Neighborhood,
    ResourceBusy,
    Twin,
)
from .server import DEFAULT_PORT, RemoteNeighborhood, serve

__version__ = "1.0.0"

__all__ = [
    "CLAIM_TTL",
    "DEFAULT_CHANNEL",
    "DEFAULT_PORT",
    "PRESENCE_TTL",
    "RESOURCES",
    "Claim",
    "Neighborhood",
    "RemoteNeighborhood",
    "ResourceBusy",
    "Twin",
    "serve",
]
