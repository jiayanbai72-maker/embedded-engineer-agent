"""ARMCC object-compilation demo; decisions supplied by the current analyst."""
import argparse
import json
from pathlib import Path
from embedded_agent.control import DecisionController
from embedded_agent.service import EngineeringService
from run_full_flow import authored_analysis

HEADER = '''#ifndef BUTTON_H
#define BUTTON_H
#include <stdint.h>
typedef struct {
    uint32_t changed_at;
    uint32_t count;
    uint8_t raw;
    uint8_t stable;
} Button;
int button_sample(Button *b, uint8_t pressed, uint32_t now_ms);
#endif
'''
SOURCE = '''#include "button.h"
int button_sample(Button *b, uint8_t pressed, uint32_t now_ms) {
    pressed = pressed ? 1u : 0u;
    if (pressed != b->raw) {
        b->raw = pressed;
        b->changed_at = now_ms;
    }
    if (b->raw != b->stable && (uint32_t)(now_ms - b->changed_at) >= 20u) {
        b->stable = b->raw;
        if (b->stable) {
            b->count++;
            return 1;
        }
    }
    return 0;
}
'''


def run(root):
    service = EngineeringService(root)
    p = service.create('编译适配演练：将按键状态机C模块编译为Cortex-M3目标文件，不选具体板卡、不链接和烧录。')
    analysis = authored_analysis()
    analysis['decision']['actions'] = ['mcu_compile', 'export_documents']
    analysis['decision']['limitations'] = ['仅做Cortex-M3目标文件编译；未验证C模块运行行为、芯片和板卡。', '语法错误为明确注入的故障演练。']
    analysis['requirements']['constraints'] = [{'name': '交付范围', 'value': 'C模块、编译日志与目标文件；不链接、不运行', 'origin': 'proposed'}]
    for req in analysis['requirements']['requirements']:
        req['acceptance'] += '；本轮仅编译检查，行为测试未执行。'
    p = service.update(p['id'], p['revision'], 'analysis', analysis)
    p = service.update(p['id'], p['revision'], 'confirm', {'confirmed': True})
    p = service.update(p['id'], p['revision'], 'select', {'candidate_id': 'PLAN-1'})
    controller = DecisionController(service)
    state = controller.create(p['id'])
    def act(action, arguments=None, rationale='依据当前工具结果执行下一步'):
        nonlocal state
        decision = {'id': f'DEC-{state["steps"]}', 'project_revision': state['project_revision'], 'action': action,
                    'arguments': arguments or {}, 'rationale': rationale, 'expected': '获得真实工具结果或产物',
                    'source': '本次对话中的Codex，显式编写的演练决策'}
        controller.submit(state['id'], state['revision'], decision)
        state = controller.tick(state['id'])
        return service.get(p['id'])
    args = {'cpu': 'Cortex-M3', 'files': {'button.h': HEADER, 'button.c': SOURCE.replace('return 0;', 'return 0')}, 'rationale': '故意省略分号以验证诊断链路'}
    act('mcu_implementation', args)
    p = act('mcu_build')
    failure = p['artifacts']['mcu_build']
    if failure['status'] != 'failed' or not failure.get('commands'):
        raise RuntimeError('没有得到预期的语法诊断；请检查编译器配置')
    args['files']['button.c'] = SOURCE
    args['rationale'] = '编译器报告缺少分号，恢复语句终止符后重新编译'
    act('mcu_implementation', args)
    p = act('mcu_build')
    if p['artifacts']['mcu_build']['status'] != 'passed':
        raise RuntimeError('真实MCU编译失败，请查看项目诊断')
    act('execute')
    act('finish')
    output = root / 'runtime' / 'mcu-demo'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'MCU目标文件-演练交付.zip').write_bytes(service.download(p['id']))
    (output / '编译验收记录.json').write_text(json.dumps({'run': state, 'injected_failure': failure, 'project': service.get(p['id'])}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': state['status'], 'compile': 'passed', 'firmware_link': 'not_run', 'hardware': 'not_run', 'archive': str(output / 'MCU目标文件-演练交付.zip')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).absolute().parents[1])
    print(json.dumps(run(parser.parse_args().root), ensure_ascii=False, indent=2))
