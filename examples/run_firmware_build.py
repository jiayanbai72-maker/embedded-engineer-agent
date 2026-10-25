"""Demonstration-only Cortex-M3 image build, no hardware or peripherals."""
import argparse
import json
from pathlib import Path
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController
from run_mcu_compile import SOURCE, HEADER
from run_full_flow import authored_analysis

PROFILE = {'name': 'generic-cortex-m3-build-demo', 'mode': 'demonstration_only', 'cpu': 'Cortex-M3',
           'flash_base': 0, 'flash_size': 65536, 'ram_base': 0x20000000, 'ram_size': 20480, 'stack_size': 1024}
MAIN = '''#include "button.h"
static Button button;
volatile uint32_t event_count;
int main(void) {
    uint32_t tick = 0;
    for (;;) {
        uint8_t pressed = ((tick / 100u) & 1u) != 0u;
        button_sample(&button, pressed, tick);
        event_count = button.count;
        tick++;
    }
}
'''


def run(root):
    service = EngineeringService(root)
    p = service.create('完整固件构建演练：采用演练内存配置，包含向量表、运行库初始化、按键C模块和合成输入主循环；不代表真实按键采样，不烧录。')
    analysis = authored_analysis()
    analysis['decision']['actions'] = ['firmware_build', 'export_documents']
    analysis['decision']['limitations'] = ['只验证构建与文件一致性，不验证芯片、时钟、外设或运行行为。', '程序使用合成输入和非真实时基，禁止当作实际按键应用。']
    analysis['requirements']['constraints'] = [{'name': '交付', 'value': '演练配置的AXF/BIN/HEX/Map与源码，不烧录', 'origin': 'proposed'}]
    for req in analysis['requirements']['requirements']:
        req['acceptance'] += '；本轮固件运行行为未测试。'
    p = service.update(p['id'], p['revision'], 'analysis', analysis)
    p = service.update(p['id'], p['revision'], 'confirm', {'confirmed': True})
    p = service.update(p['id'], p['revision'], 'select', {'candidate_id': 'PLAN-1'})
    controller = DecisionController(service)
    state = controller.create(p['id'])
    def act(action, arguments=None):
        nonlocal state
        d = {'id': f'DEC-{state["steps"]}', 'project_revision': state['project_revision'], 'action': action,
             'arguments': arguments or {}, 'rationale': '按演练范围补齐启动和内存布局，再依据真实工具结果检查产物',
             'expected': '真实构建或交付结果，不声称实机通过', 'source': '本次对话中的Codex'}
        controller.submit(state['id'], state['revision'], d)
        state = controller.tick(state['id'])
        return service.get(p['id'])
    act('firmware_implementation', {'profile': PROFILE, 'files': {'button.h': HEADER, 'button.c': SOURCE, 'main.c': MAIN}, 'rationale': '用向量表、__main运行库初始化和明确内存布局形成完整演练映像'})
    p = act('firmware_build')
    if p['artifacts']['firmware_build']['status'] != 'passed':
        print(json.dumps(p['artifacts']['firmware_build'], ensure_ascii=False, indent=2))
        raise RuntimeError('固件构建失败，未宣布完成')
    act('execute'); act('finish')
    output = root / 'runtime' / 'firmware-demo'
    output.mkdir(parents=True, exist_ok=True)
    (output / '完整固件构建-演练交付.zip').write_bytes(service.download(p['id']))
    (output / '构建验收记录.json').write_text(json.dumps({'run': state, 'project': service.get(p['id'])}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': state['status'], 'firmware_build': 'passed', 'hardware': 'not_run', 'archive': str(output / '完整固件构建-演练交付.zip')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).absolute().parents[1])
    print(json.dumps(run(parser.parse_args().root), ensure_ascii=False, indent=2))
