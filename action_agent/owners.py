"""
Owner resolution from owners.yaml (docs/action-agent-scope.md §4, D8).

The recipient of notify_owner / create_control alerts is always resolved here,
deterministically, from (dataset_id, dimension, segment) -- never chosen by the
LLM. A proposal can't redirect a message to an arbitrary address because no
param for one exists.
"""

from pathlib import Path
from typing import Dict, Optional

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

DEFAULT_OWNERS_PATH = Path(__file__).parent / 'owners.yaml'
WILDCARD = '*'


class Person(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    email: str


class OwnersConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    default_owner: str
    people: Dict[str, Person]
    # dataset_id -> dimension -> segment (or '*') -> person id
    segments: Dict[str, Dict[str, Dict[str, str]]] = {}

    @model_validator(mode='after')
    def _ids_defined(self) -> 'OwnersConfig':
        referenced = {self.default_owner}
        for dims in self.segments.values():
            for segs in dims.values():
                referenced.update(segs.values())
        missing = sorted(referenced - set(self.people))
        if missing:
            raise ValueError(f"owner ids not defined under people: {', '.join(missing)}")
        return self


def load_owners(path: Path = DEFAULT_OWNERS_PATH) -> OwnersConfig:
    with open(path) as f:
        return OwnersConfig.model_validate(yaml.safe_load(f))


def resolve_owner(
    owners: OwnersConfig, dataset_id: str, dimension: Optional[str], segment: Optional[str],
) -> Dict[str, str]:
    """Returns {'id', 'name', 'email', 'matched'} where matched is
    'segment' | 'dimension' | 'default'."""
    dims = owners.segments.get(dataset_id, {})
    segs = dims.get(dimension, {}) if dimension else {}

    if segment is not None and segment in segs and segment != WILDCARD:
        owner_id, matched = segs[segment], 'segment'
    elif WILDCARD in segs:
        owner_id, matched = segs[WILDCARD], 'dimension'
    else:
        owner_id, matched = owners.default_owner, 'default'

    person = owners.people[owner_id]
    return {'id': owner_id, 'name': person.name, 'email': person.email, 'matched': matched}
