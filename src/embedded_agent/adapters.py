import json
from pathlib import Path


class JsonKnowledge:
    """Read existing knowledge-card index without coupling it to a project."""
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema_version') != 1:
            raise ValueError('unsupported knowledge index')
        self.cards = data['cards']

    def search(self, query, *, scope='general'):
        if scope not in ('general', 'ecosystem', 'device', 'case', 'all'):
            raise ValueError('unknown scope')
        terms = query.lower().split()
        if not terms:
            return []
        results = []
        for card in self.cards:
            if scope != 'all' and card['scope'] != scope:
                continue
            text = (card['title'] + ' ' + card['content']).lower()
            score = sum(text.count(term) for term in terms)
            if score:
                results.append(dict(card, score=score))
        return sorted(results, key=lambda item: (-item['score'], item['id']))


class ToolRegistry:
    """Only explicitly registered callable tools; no arbitrary shell execution."""
    def __init__(self):
        self._tools = {}
        self.events = []

    def register(self, name, handler, validator):
        if name in self._tools:
            raise ValueError('duplicate tool')
        self._tools[name] = (handler, validator)

    def capabilities(self):
        return sorted(self._tools)

    def execute(self, name, arguments):
        from .local_model import BudgetPaused
        if name not in self._tools:
            return {'status': 'unsupported', 'tool': name}
        handler, validator = self._tools[name]
        # Store only tool name and status, not credentials or raw user arguments.
        try:
            validator(arguments)
            result = handler(arguments)
            if not isinstance(result, dict) or result.get('status') not in ('passed', 'failed', 'unsupported', 'needs_input'):
                raise ValueError('invalid tool result')
        except BudgetPaused:
            raise
        except Exception as exc:
            from .research_orchestration import EvidenceError
            result = {'status': 'failed', 'message': '工具执行或参数校验失败','failure_code':'argument_validation'}
            if isinstance(exc,EvidenceError):
                result.update(message=str(exc),failure_code=exc.code)
                if exc.field:result['field']=exc.field
        if result['status']=='failed' and name in ('parameters.auto_review','facts.auto_review'):
            from .research_orchestration import failure_code
            result['action']='record_parameter' if name=='parameters.auto_review' else 'record_fact'
            result.setdefault('attempted_fields',{k:arguments[k] for k in ('document_id','page','source_view','quote_id','model','parameter','value','unit','subject','predicate','object','conditions') if k in arguments})
            result['failure_code']=failure_code(result)
        self.events.append({'tool': name, 'status': result['status']})
        return result
