"""Real local HTTP walkthrough with analyst-authored decisions, host code and injected defect."""
import argparse
import json
from pathlib import Path
import threading
import urllib.request
from embedded_agent.server import make_server

SOURCE = '''class Button:
    def __init__(self, debounce_ms=20):
        self.debounce_ms = debounce_ms
        self.raw = False
        self.stable = False
        self.changed_at = 0
        self.last_time = -1
        self.count = 0

    def sample(self, pressed, now_ms):
        if now_ms < self.last_time:
            raise ValueError("time must be monotonic")
        self.last_time = now_ms
        if pressed != self.raw:
            self.raw = pressed
            self.changed_at = now_ms
        if self.raw != self.stable and now_ms - self.changed_at > self.debounce_ms:
            self.stable = self.raw
            if self.stable:
                self.count += 1
                return {"event": "pressed", "count": self.count, "time_ms": now_ms}
        return None
'''

TESTS = '''import unittest
from button import Button

class ButtonTests(unittest.TestCase):
    def test_exact_boundary(self):
        b = Button()
        self.assertIsNone(b.sample(True, 0))
        self.assertIsNone(b.sample(True, 19))
        self.assertEqual(b.sample(True, 20)["count"], 1)

    def test_bounce_not_an_event(self):
        b = Button()
        b.sample(True, 0)
        b.sample(False, 5)
        b.sample(True, 10)
        b.sample(False, 15)
        self.assertIsNone(b.sample(False, 100))
        self.assertEqual(b.count, 0)

    def test_hold_does_not_repeat_and_release_rearms(self):
        b = Button()
        b.sample(True, 0)
        b.sample(True, 21)
        self.assertIsNone(b.sample(True, 1000))
        b.sample(False, 1001)
        b.sample(False, 1022)
        b.sample(True, 1030)
        self.assertEqual(b.sample(True, 1051)["count"], 2)

    def test_backwards_time_rejected(self):
        b = Button()
        b.sample(False, 10)
        with self.assertRaises(ValueError):
            b.sample(False, 9)
'''


def authored_analysis():
    requirements = {
        'requirements': [
            {'id': 'REQ-1', 'description': '稳定20毫秒后确认按键状态', 'acceptance': '19ms不触发，20ms触发；主机测试验证', 'origin': 'proposed'},
            {'id': 'REQ-2', 'description': '按下一次产生一个计数事件，长按不重复，释放后可重触发', 'acceptance': '长按只计一次，释放后再次按下计数加一', 'origin': 'proposed'},
            {'id': 'REQ-3', 'description': '过滤短暂抖动，拒绝倒退时间输入', 'acceptance': '短暂切换计数为零；倒退时间抛出错误', 'origin': 'proposed'}],
        'constraints': [{'name': '执行环境', 'value': '主机行为仿真，不连接硬件，不交付MCU固件', 'origin': 'proposed'}],
        'assumptions': ['参数和范围由分析者为全流程演练选定，非真实硬件指标。'],
        'questions': [], 'search_queries': ['需求', '模块', '接口', '测试', '调试']}
    candidates = []
    for name, architecture, tradeoff, condition in (
        ('事件驱动状态机', '输入采样→去抖状态机→按下事件→计数记录', '依赖调用方定期采样；结构简单便于验证', '当前只有单一输入与无阻塞逻辑'),
        ('RTOS任务方案', '采样任务→事件队列→记录任务', '可隔离复杂并发，但增加任务与同步开销', '后续增加多个独立阻塞任务才考虑')):
        candidates.append({'id': f'PLAN-{len(candidates)+1}', 'name': name, 'architecture': architecture,
                           'covers': ['REQ-1', 'REQ-2', 'REQ-3'], 'tradeoffs': [tradeoff], 'conditions': [condition],
                           'risks': ['实际输入电平、采样频率和时钟回绕须在硬件适配时核对'],
                           'evidence_ids': ['GEN-ARCH-001', 'GEN-TEST-001'],
                           'chip_requirements': ['GPIO输入、可靠时基；当前主机仿真不选芯片'], 'chip_options': []})
    return {'analyst': '本次对话中的 Codex；分析者编写的演练方案', 'requirements': requirements,
            'comparison': {'candidates': candidates, 'recommendation': {'candidate_id': 'PLAN-1', 'reason': '单输入与短处理路径不需要RTOS，状态机方便边界测试和后续GPIO适配'}},
            'decision': {'rationale': '选用可测试的确定性状态机；区分原始和稳定状态。将采样时间注入接口以重放抖动序列，使用边界、长按、释放和非法时间测试验证行为。',
                         'limitations': ['仅验证主机行为模型，不代表器件、电气、实时性或实机验证通过。', '首次源码故意注入大于/大于等于边界错误，用于明确标注的故障演练。'],
                         'actions': ['host_prototype', 'export_documents']}}


def run(root):
    timeline = []
    def start():
        server = make_server(root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread
    server, thread = start()
    def request(path, payload=None):
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + path,
                                     data=None if payload is None else json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
        if path.endswith('/download'):
            return raw
        result = json.loads(raw)
        timeline.append({'path': path, 'revision': result.get('revision'), 'status': result.get('status')})
        return result
    try:
        project = request('/projects', {'description': '全流程演练：按键事件记录器，20ms去抖、一次按下一个事件、释放后重触发；只运行主机行为原型。'})
        base = '/projects/' + project['id']
        def update(action, **payload):
            nonlocal project
            project = request(base + '/' + action, dict(payload, revision=project['revision']))
        update('analysis', **authored_analysis())
        update('confirm', confirmed=True)
        update('select', candidate_id='PLAN-1')
        update('implementation', files={'button.py': SOURCE, 'test_button.py': TESTS}, rationale='初版包含显式注入的边界错误，用于故障演练。')
        update('build')
        update('test')
        if project['status'] != 'test_failed':
            raise RuntimeError('预期边界故障未被检测，不能继续宣布调试成功')
        failure = project['artifacts']['verification']
        server.shutdown(); server.server_close(); thread.join()
        server, thread = start()
        project = request(base)
        if project['status'] != 'test_failed':
            raise RuntimeError('重启恢复失败')
        fixed = SOURCE.replace('> self.debounce_ms', '>= self.debounce_ms')
        update('implementation', files={'button.py': fixed, 'test_button.py': TESTS},
               rationale='20ms边界测试失败，状态转换条件使用严格大于导致恰好20ms不触发。最小修复为大于等于，保留原测试并重新执行。')
        update('build')
        update('test')
        if project['status'] != 'ready_delivery':
            raise RuntimeError('复测未通过')
        update('execute')
        archive = request(base + '/download')
        output = root / 'runtime' / 'full-flow'
        output.mkdir(parents=True, exist_ok=True)
        (output / '按键记录器-全流程交付.zip').write_bytes(archive)
        (output / '验收记录.json').write_text(json.dumps({'project': project, 'timeline': timeline, 'injected_failure': failure,
                                                        'restart_restored': True, 'mode': 'analyst_assisted_host_prototype'}, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'project_id': project['id'], 'status': project['status'], 'archive': str(output / '按键记录器-全流程交付.zip'),
                'host_tests': project['verification']['host_tests'], 'hardware': 'not_run'}
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).absolute().parents[1])
    print(json.dumps(run(parser.parse_args().root), ensure_ascii=False, indent=2))
