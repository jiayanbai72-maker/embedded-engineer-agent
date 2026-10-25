from pathlib import Path
from .adapters import JsonKnowledge, ToolRegistry
from .agents import UnconfiguredAgent
from .domain import STAGES
from .ports import Services
from .storage import FileProjectStore
from .workflow import Workflow
from .analysis import IntakeAgent
from .library import DocumentLibrary, ParameterEvidence


class Application:
    """Shared entry point for CLI and a future HTTP service."""
    def __init__(self, root: Path, model=None):
        self.store = FileProjectStore(root / 'runtime' / 'projects')
        self.knowledge = JsonKnowledge(root / 'knowledge' / 'index.json')
        self.documents = DocumentLibrary(root)
        self.parameters = ParameterEvidence(root, self.documents)
        self.tools = ToolRegistry()
        def validate_search(args):
            if not isinstance(args, dict) or not isinstance(args.get('query'), str) or not args['query'].strip():
                raise ValueError('query required')
        self.tools.register('knowledge.search', lambda args: {'status': 'passed', 'matches': self.knowledge.search(args['query'], scope=args.get('scope', 'general'))}, validate_search)
        self.tools.register('documents.search', lambda args: {'status':'passed','matches':self.documents.search(args['query'],args.get('limit',8),args.get('document_id'))}, validate_search)
        self.tools.register('documents.page', lambda args: {'status':'passed','page':self.documents.page(args['document_id'],args.get('page'),source_view=args.get('source_view','text'))}, lambda args: None)
        self.tools.register('parameters.read', lambda args: {'status':'passed','parameter':self.parameters.get(args['id'])}, lambda args: None)
        agents = {s: UnconfiguredAgent(s) for s in STAGES}
        agents['requirements'] = IntakeAgent()
        self.workflow = Workflow(self.store, agents, Services(self.knowledge, self.tools, model))

    def analyze(self, description):
        project = self.store.create(description)
        return self.workflow.step(project.id)

    def supplement(self, project_id, message):
        if not isinstance(message, str) or not message.strip():
            raise ValueError('补充内容不能为空')
        project = self.store.load(project_id)
        if project.stage != 'requirements' or project.status == 'complete':
            raise ValueError('只能补充当前需求阶段')
        if 'requirements' in project.artifacts:
            project.events.append({'stage': 'requirements', 'action': 'superseded', 'artifact': project.artifacts.pop('requirements')})
        project.description += '\n用户补充：' + message.strip()
        project.status = 'ready'
        project.revision += 1
        self.store.save(project)
        return self.workflow.step(project.id)
