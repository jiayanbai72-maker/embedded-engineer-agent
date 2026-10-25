"""Task dependencies and completion evaluated against actual controller receipts."""
from copy import deepcopy
from .contracts import PLAN_SCHEMA, validate_shape


def field(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def validate(plan, actions):
    validate_shape(PLAN_SCHEMA, plan, 'plan')
    if not isinstance(plan, dict) or not all(isinstance(plan.get(k), str) and plan[k].strip() for k in ('goal', 'rationale', 'source')):
        raise ValueError('计划需要目标、依据和分析者来源')
    tasks = plan.get('tasks')
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 40:
        raise ValueError('计划需要1至40项任务')
    ids = set()
    for task in tasks:
        if not isinstance(task, dict) or not all(isinstance(task.get(k), str) and task[k].strip() for k in ('id', 'title', 'action')):
            raise ValueError('任务需要编号、名称和动作')
        if task['id'] in ids or task['action'] not in actions | {'user_input'}:
            raise ValueError('任务编号重复或能力未实现')
        ids.add(task['id'])
        if not isinstance(task.get('depends_on'), list) or not all(isinstance(x, str) for x in task['depends_on']):
            raise ValueError('任务依赖必须为编号列表')
        criteria = task.get('completion')
        if not isinstance(criteria, dict) or not criteria or len(criteria) > 12:
            raise ValueError('任务需要基于执行回执的完成条件')
        if criteria.get('status') != 'executed':
            raise ValueError('完成条件必须要求实际执行成功')
        if not all(isinstance(k, str) and k and isinstance(v, (str, int, float, bool, type(None))) for k, v in criteria.items()):
            raise ValueError('完成条件须为回执字段路径与期望值')
    remaining = {t['id']: set(t['depends_on']) for t in tasks}
    if any(not deps <= ids for deps in remaining.values()):
        raise ValueError('依赖编号不存在')
    while remaining:
        ready = {k for k, deps in remaining.items() if not deps}
        if not ready:
            raise ValueError('任务依赖存在环路')
        remaining = {k: deps - ready for k, deps in remaining.items() if k not in ready}
    return deepcopy(plan)


def progress(run, allowed, project_revision):
    plan = run.get('task_plan')
    if not plan:
        return None
    rows, completed = [], set()
    pending = list(plan['tasks'])
    stale = project_revision != run['project_revision']
    while pending:
        for task in list(pending):
            if any(dep not in {r['id'] for r in rows} for dep in task['depends_on']):
                continue
            receipts = [(key, r) for key, r in run['receipts'].items()
                        if r.get('task_id') == task['id'] and r.get('plan_version') == plan['version']]
            last = receipts[-1] if receipts else None
            unmet = [d for d in task['depends_on'] if d not in completed]
            if stale:
                status, reason = 'stale', '项目已变化，需刷新并重新规划'
            elif unmet:
                status, reason = 'blocked', '等待依赖：' + '、'.join(unmet)
            elif last and all(field(last[1], k) == v for k, v in task['completion'].items()):
                status, reason = 'completed', '实际回执满足完成条件'
                completed.add(task['id'])
            elif task['action'] == 'user_input':
                status, reason = 'needs_input', task['title']
            elif last:
                status, reason = 'needs_review', '执行结果未满足完成条件，需分析或调整计划'
            elif task['action'] not in allowed:
                status, reason = 'blocked', '当前工程阶段尚未允许该动作'
            else:
                status, reason = 'ready', '依赖满足，等待分析者提交执行决策'
            rows.append(dict(task, status=status, reason=reason, receipt_id=last[0] if last else None))
            pending.remove(task)
    return {'version': plan['version'], 'goal': plan['goal'], 'tasks': rows,
            'completed': len(completed), 'total': len(rows), 'autonomous_provider': False}
