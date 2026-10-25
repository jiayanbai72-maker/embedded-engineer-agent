from datetime import datetime, timezone
from .domain import STAGES


class Workflow:
    def __init__(self, store, agents, services):
        self.store, self.agents, self.services = store, agents, services

    def step(self, project_id):
        project = self.store.load(project_id)
        if project.stage == 'complete':
            return project
        # Prevent repeating a suspended operation without new user input/configuration.
        if project.status != 'ready':
            return project
        stage = project.stage
        agent = self.agents[stage]
        try:
            result = agent.run(project, self.services)
            if result.outcome not in ('passed', 'needs_input', 'unsupported', 'failed'):
                raise ValueError('invalid outcome')
            if result.outcome == 'passed' and not result.artifact:
                raise ValueError('passed stage must provide an artifact')
            if result.artifact:
                project.artifacts[stage] = result.artifact
            project.events.append({'stage': stage, 'outcome': result.outcome,
                                   'message': result.message,
                                   'at': datetime.now(timezone.utc).isoformat()})
            if result.outcome == 'passed':
                project.stage_index += 1
                project.status = 'complete' if project.stage_index == len(STAGES) else 'ready'
            else:
                project.status = result.outcome
        except Exception:
            project.status = 'failed'
            project.events.append({'stage': stage, 'outcome': 'failed', 'message': '阶段执行失败；保留当前阶段。'})
        project.revision += 1
        self.store.save(project)
        return project

    def retry(self, project_id):
        project = self.store.load(project_id)
        if project.status not in ('failed', 'unsupported'):
            raise ValueError('only failed or unsupported runs can be retried')
        project.status = 'ready'
        project.revision += 1
        project.events.append({'stage': project.stage, 'action': 'retry'})
        self.store.save(project)
        return project
