from .domain import StageResult


class UnconfiguredAgent:
    """Honest placeholder: never fabricates reasoning or execution results."""
    def __init__(self, stage):
        self.stage = stage

    def run(self, project, services):
        return StageResult('unsupported', message=f'{self.stage} 阶段尚未配置执行器；不会自动标记通过。')


