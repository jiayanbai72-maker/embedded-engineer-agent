from typing import Protocol
from .domain import Project, StageResult


class ModelProvider(Protocol):
    def generate(self, *, role: str, instruction: str, context: dict) -> dict: ...


class KnowledgePort(Protocol):
    def search(self, query: str, *, scope: str = 'general') -> list[dict]: ...


class ToolPort(Protocol):
    def execute(self, name: str, arguments: dict) -> dict: ...
    def capabilities(self) -> list[str]: ...


class StageAgent(Protocol):
    def run(self, project: Project, services: 'Services') -> StageResult: ...


class Services:
    def __init__(self, knowledge: KnowledgePort, tools: ToolPort, model: ModelProvider | None = None):
        self.knowledge = knowledge
        self.tools = tools
        self.model = model
