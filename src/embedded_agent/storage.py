import json
from pathlib import Path
from uuid import UUID, uuid4
from .domain import Project


class FileProjectStore:
    """Local single-process persistence. Multi-worker deployment needs a transactional store."""
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, project_id):
        # No caller-controlled path segments.
        canonical = str(UUID(project_id))
        if canonical != project_id:
            raise ValueError('project id must be a canonical UUID')
        return self.root / (canonical + '.json')

    def create(self, description):
        if not isinstance(description, str) or not description.strip():
            raise ValueError('description cannot be empty')
        project = Project(str(uuid4()), description.strip())
        self.save(project)
        return project

    def load(self, project_id):
        return Project(**json.loads(self.path(project_id).read_text(encoding='utf-8')))

    def save(self, project):
        path = self.path(project.id)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
