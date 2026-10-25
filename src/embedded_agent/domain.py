from dataclasses import dataclass, field, asdict
from typing import Any

STAGES = ('requirements', 'design', 'selection', 'implementation', 'build', 'debug', 'verification', 'delivery')


@dataclass
class Project:
    id: str
    description: str
    revision: int = 0
    stage_index: int = 0
    status: str = 'ready'
    artifacts: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def stage(self):
        return STAGES[self.stage_index] if self.stage_index < len(STAGES) else 'complete'

    def to_dict(self):
        return asdict(self)


@dataclass
class StageResult:
    outcome: str  # passed, needs_input, unsupported, failed
    artifact: dict[str, Any] = field(default_factory=dict)
    message: str = ''
