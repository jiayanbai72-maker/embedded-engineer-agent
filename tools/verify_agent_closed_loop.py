"""Isolated HTTP acceptance matrix. Fixture decisions are NOT model reasoning."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zipfile import ZipFile
from embedded_agent.server import make_server

CASES = [
    {'id': 'environment', 'title': '环境监测告警行为原型', 'description': '温度达到30度时告警；拒绝无效测量。先做主机原型，不指定芯片。',
     'source': 'import math\ndef process(value):\n    if not math.isfinite(value): raise ValueError("invalid reading")\n    return value >= 30\n',
     'broken': 'import math\ndef process(value):\n    if not math.isfinite(value): raise ValueError("invalid reading")\n    return value > 30\n',
     'test': 'self.assertFalse(process(29.9))\n        self.assertTrue(process(30))\n        self.assertTrue(process(31))\n        with self.assertRaises(ValueError): process(float("nan"))', 'failure': 'test_failed'},
    {'id': 'actuator', 'title': '执行器限位行为原型', 'description': '执行器指令限制在0到90度；仅验证主机控制逻辑，不驱动真实电机。',
     'source': 'def process(value):\n    return min(90, max(0, value))\n',
     'broken': 'def process(value)\n    return min(90, max(0, value))\n',
     'test': 'self.assertEqual(process(-1), 0)\n        self.assertEqual(process(45), 45)\n        self.assertEqual(process(91), 90)', 'failure': 'build_failed'},
    {'id': 'logger', 'title': '低功耗记录设备的缓存行为原型', 'description': '记录设备缓存仅保留最近3条数据；先验证缓存逻辑，功耗与唤醒时序留待硬件验证。',
     'source': 'def process(value):\n    return list(value)[-3:]\n', 'broken': None,
     'test': 'self.assertEqual(process([]), [])\n        self.assertEqual(process([1, 2]), [1, 2])\n        self.assertEqual(process([1, 2, 3, 4]), [2, 3, 4])', 'failure': None}
]


def analysis(case):
    reqs = [{'id': 'REQ-1', 'description': case['description'], 'acceptance': '运行对应主机边界测试；不代表实机通过', 'origin': 'explicit'}]
    candidates = []
    for id, name, arch in [('PLAN-1', '确定性独立逻辑', '输入→纯逻辑函数→结果'), ('PLAN-2', '事件队列适配', '输入→事件队列→处理函数→结果')]:
        candidates.append({'id': id, 'name': name, 'architecture': arch, 'covers': ['REQ-1'],
            'tradeoffs': ['独立函数容易测试，复杂并发需要进一步设计'], 'conditions': ['当前仅验证主机行为模型'],
            'risks': ['未验证硬件、电气、实时性与功耗'], 'evidence_ids': ['GEN-ARCH-001', 'GEN-TEST-001'],
            'chip_requirements': ['未选择具体芯片'], 'chip_options': []})
    return {'analyst': 'acceptance_fixture_not_a_model', 'requirements': {'requirements': reqs,
        'constraints': [{'name': '范围', 'value': '仅主机行为原型与文档', 'origin': 'explicit'}],
        'assumptions': ['验收由固定测试决策者驱动，不评估模型思考'], 'questions': [], 'search_queries': ['需求', '测试']},
        'comparison': {'candidates': candidates, 'recommendation': {'candidate_id': 'PLAN-1', 'reason': '当前原型使用独立函数便于验证'}},
        'decision': {'actions': ['host_prototype', 'export_documents'], 'rationale': '离线验证逻辑，构建和测试后导出',
                     'limitations': ['参数、器件选型和实机未验证；没有推断记录设备的真实低功耗性能']}}


def task_plan(refs=None):
    tasks = []
    for id, action, depends, completion in [
        ('code', 'implementation', [], {'status': 'executed', 'project_status': 'ready_build'}),
        ('build', 'build', ['code'], {'status': 'executed', 'tool_result.status': 'passed'}),
        ('test', 'test', ['build'], {'status': 'executed', 'tool_result.status': 'passed'}),
        ('export', 'execute', ['test'], {'status': 'executed', 'project_status': 'documents_delivered'})]:
        tasks.append({'id': id, 'title': id, 'action': action, 'depends_on': depends, 'completion': completion})
    return dict(goal='以真实构建与测试回执完成离线交付', rationale='故障后依据失败回执重新验证全部依赖' if refs else '按实现、构建、验证、导出顺序验证系统',
                source='acceptance_fixture_not_a_model', tasks=tasks, **({'response_to': refs} if refs else {}))


class FixtureDecider:
    """Deliberately deterministic fixture, isolated from production startup."""
    def __init__(self, case): self.case = case

    def decide(self, context):
        run, project = context['run'], context['project']
        observations = run['observations']
        def decision(action, arguments=None, task_id=None):
            return {'kind': 'decision', 'action': action, 'arguments': arguments or {}, 'task_id': task_id,
                    'rationale': '显式测试夹具根据真实状态选择下一步；不代表自主推理', 'expected': '记录真实执行回执并检查下一阶段'}
        if not run.get('user_messages'): return decision('ask', {'question': '确认本次只做离线主机行为原型吗？'})
        if project['status'] == 'awaiting_analysis': return decision('analysis', analysis(self.case))
        if project['status'] == 'awaiting_implementation' and not any(o['action'] == 'search_documents' for o in observations):
            return decision('search_documents', {'query': '不存在的资料-acceptance-no-library'})
        progress = context.get('task_progress')
        if not progress: return {'kind': 'plan', 'plan': task_plan()}
        if any(t['status'] == 'needs_review' for t in progress['tasks']):
            return {'kind': 'plan', 'plan': task_plan([list(run['receipts'])[-1]])}
        if project['status'] in ('awaiting_implementation', 'build_failed', 'test_failed'):
            failed = any(o.get('project_status') in ('build_failed', 'test_failed') for o in observations)
            source = self.case['source'] if failed or not self.case['broken'] else self.case['broken']
            tests = 'import unittest\nfrom logic import process\nclass BehaviorTests(unittest.TestCase):\n    def test_behavior(self):\n        ' + self.case['test'] + '\n'
            return decision('implementation', {'files': {'logic.py': source, 'test_logic.py': tests}, 'rationale': '显式故障修复夹具' if failed else '显式初版夹具'}, 'code')
        return decision({'ready_build': 'build', 'ready_test': 'test', 'ready_delivery': 'execute', 'documents_delivered': 'finish'}[project['status']],
                        task_id={'ready_build': 'build', 'ready_test': 'test', 'ready_delivery': 'export'}.get(project['status']))


def verify_case(root, case):
    root.mkdir(parents=True)
    (root / 'knowledge').mkdir()
    source_root = Path(__file__).resolve().parents[1]
    (root / 'knowledge/index.json').write_bytes((source_root / 'knowledge/index.json').read_bytes())
    provider = FixtureDecider(case)
    timeline, confirmations, restarts = [], [], 0
    def start():
        server = make_server(root, 0, decision_provider=provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        return server, thread
    server, thread = start()
    def request(path, payload=None):
        req = Request(f'http://127.0.0.1:{server.server_port}' + path,
                      data=None if payload is None else json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=30) as response: raw = response.read()
        return raw if path.endswith('/download') else json.loads(raw)
    try:
        project = request('/projects', {'description': case['description']})
        pid = project['id']; run = request('/runs', {'project_id': pid, 'max_steps': 30})
        rid = run['id']
        for _ in range(45):
            result = request('/runs/' + rid + '/auto', {})
            c = result['context']; run, project = c['run'], c['project']
            timeline.append({'runner_status': result['status'], 'project_status': project['status'], 'run_status': run['status'], 'steps': run['steps'], 'plan_version': c.get('task_progress', {}).get('version') if c.get('task_progress') else None})
            if run['status'] == 'waiting_input':
                request('/runs/' + rid + '/reply', {'revision': run['revision'], 'message': '确认，只验证离线行为模型，不接硬件。'})
                confirmations.append('自然语言回答测试范围')
            elif project['status'] == 'needs_input':
                request('/projects/' + pid + '/confirm', {'revision': project['revision'], 'confirmed': True})
                confirmations.append('用户确认需求')
            elif project['status'] == 'awaiting_selection':
                request('/projects/' + pid + '/select', {'revision': project['revision'], 'candidate_id': 'PLAN-1'})
                confirmations.append('用户选择方案')
            elif project['status'] == case['failure'] and restarts == 0:
                expected_steps = run['steps']
                server.shutdown(); server.server_close(); thread.join()
                server, thread = start(); restarts += 1
                restored = request('/runs/' + rid)
                assert restored['run']['steps'] == expected_steps, '重启未恢复运行'
                assert restored['project']['status'] == case['failure'], '重启未恢复失败记录'
            elif run['status'] == 'complete': break
            elif result['status'] != 'continue': raise AssertionError('意外暂停：' + result['message'])
        else: raise AssertionError('闭环未在预算内完成')
        archive = request('/projects/' + pid + '/download')
        assert archive == request('/projects/' + pid + '/download'), '重复下载内容变化'
        with ZipFile(io.BytesIO(archive)) as z:
            required = {'requirements.json', 'selected-plan.json', 'delivery-assessment.json', 'host-test-result.json', 'host-prototype/logic.py', 'host-prototype/test_logic.py'}
            assert required <= set(z.namelist()), '交付文件缺失'
            assert json.loads(z.read('host-test-result.json'))['status'] == 'passed', '导出失败测试结果'
            assert json.loads(z.read('delivery-assessment.json'))['hardware_verified'] is False, '误报实机验证'
        context = request('/runs/' + rid)
        assert context['task_progress']['completed'] == 4, '任务进度没有完成'
        assert any(o['action'] == 'search_documents' and o['status'] == 'rejected' for o in context['run']['observations']), '缺资料场景未覆盖'
        if case['failure']: assert restarts == 1 and context['run']['repairs'] == 1, '未验证失败恢复'
        implementation_count = sum(o['action'] == 'implementation' for o in context['run']['observations'])
        assert implementation_count == (2 if case['failure'] else 1), '恢复后重复提交实现'
        changed = request('/projects/' + pid + '/supplement', {'revision': project['revision'], 'message': '增加后续需求，需要重新分析，旧交付不再有效。'})
        assert changed['status'] == 'awaiting_analysis' and not changed['artifacts'], '需求变更未失效旧产物'
        try:
            request('/projects/' + pid + '/download')
        except HTTPError as exc:
            assert exc.code == 400, '旧交付拒绝状态异常'
        else:
            raise AssertionError('需求改变后仍可下载旧交付')
        return {'id': case['id'], 'title': case['title'], 'status': 'passed', 'mode': 'deterministic_fixture_not_model_reasoning',
                'project_id': pid, 'run_id': rid, 'steps': run['steps'], 'restarts': restarts, 'confirmations': confirmations,
                'hardware': 'not_run', 'missing_documents_observed': True, 'requirements_change_invalidated_delivery': True,
                'archive_sha256': hashlib.sha256(archive).hexdigest(), 'timeline': timeline}, archive
    finally:
        server.shutdown(); server.server_close(); thread.join()


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='embedded-agent-acceptance-') as workspace:
        for case in CASES:
            result, archive = verify_case(Path(workspace) / case['id'], case)
            (output / (case['id'] + '.zip')).write_bytes(archive)
            results.append(result)
    report = {'scope': '离线控制器与HTTP服务闭环验收；不评估真实模型或硬件', 'status': 'passed', 'cases': results}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 跨项目闭环验收报告', '', report['scope'], '', '| 场景 | 结果 | 执行步数 | 失败后重启 |', '|---|---|---:|---:|']
    lines += [f"| {r['title']} | 通过 | {r['steps']} | {r['restarts']} |" for r in results]
    lines += ['', '三个场景均覆盖：自然语言回答、用户确认需求与方案、任务依赖、真实主机构建与测试、缺资料反馈、打包下载、需求变化使旧结果失效。', '', '前两例显式注入边界错误和语法错误，再由固定测试决策者依据失败状态提交预设修复；没有检验模型能否自行定位或编写修复。第三例只验证记录缓存，不验证真实低功耗。', '', '测试在临时目录启动独立随机端口服务，不改动工作台项目、不连接模型、不访问外网、不连接开发板。临时运行数据已清理，交付ZIP和JSON时间线保存在本目录。']
    (output / '报告.md').write_text('\n'.join(lines), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'runtime/acceptance')
    args = parser.parse_args()
    report = main(args.output)
    print(json.dumps({'status': report['status'], 'cases': len(report['cases']), 'output': str(args.output)}, ensure_ascii=False))
