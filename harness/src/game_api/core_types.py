"""Compatibility names for generated API models and local startup metadata.

The HTTP contract is generated from Rust; no HTTP fields are maintained here.
Startup is a local subprocess protocol, separate from the versioned HTTP API.
"""

from pydantic import Field, field_validator

from .generated import (
    DeploymentView as Deployment,
)
from .generated import (
    WireModel,
)


class Startup(WireModel):
    api_url: str
    rpc_url: str
    deployment: Deployment
    participant_ids: list[str] = Field(min_length=1)

    @field_validator("participant_ids")
    @classmethod
    def validate_participant_roster(cls, ids: list[str]) -> list[str]:
        if len(ids) != len(set(ids)) or any(
            actor == "operator" or not actor or any(not 0x21 <= ord(char) <= 0x7E for char in actor)
            for actor in ids
        ):
            raise ValueError("Local participant IDs must be unique, visible and exclude operator")
        return ids
