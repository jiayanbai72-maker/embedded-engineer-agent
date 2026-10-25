"""Read-only project audit: isolated extra mock tests, no model or project writes."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from embedded_agent.draft_verification import verify, source_hash

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "robot_app.h"
#include "voice_uart.h"
static uint32_t now;
static unsigned pulses,rail,last_us;
static void pwm(axis_id_t axis,uint16_t us){(void)axis;pulses++;last_us=us;}
static void power(uint8_t on){rail=on;}
static uint32_t clock_ms(void){return now;}
static robot_hal_t hal={pwm,power,clock_ms,0};
static void setup(robot_ctx_t *c){
 unsigned i;servo_calib_t cal={1000,1500,1800,1};
 now=0;pulses=0;rail=1;robot_init(c,&hal);
 for(i=0;i<AXIS_COUNT;i++)robot_set_calib(c,(axis_id_t)i,&cal);
}
int main(void){robot_ctx_t c;setup(&c);
'''

CASES = [
    ('repeated_cycles', '连续1000次动作及忙碌拒绝', r'''
 unsigned i;for(i=0;i<1000;i++){
 uint32_t start=now;unsigned previous=pulses;
 assert(robot_handle_cmd(&c,CMD_WAVE)==0);
 assert(robot_handle_cmd(&c,CMD_NOD)==-3);
 now=start+30;robot_tick(&c);assert(pulses==previous+1);
 now=start+430;robot_tick(&c);assert(last_us==1500);
 now=start+730;robot_tick(&c);assert(!rail&&!c.busy);
 }
'''),
    ('idle_park_wrap', '空闲停靠在时钟回绕后断电', r'''
 now=0xfffffff0u;robot_park(&c);assert(rail);
 now=283u;robot_tick(&c);assert(rail);
 now=284u;robot_tick(&c);assert(!rail&&!c.busy);
'''),
    ('missing_clock', '缺少时钟接口时拒绝启动并保持断电', r'''
 hal.millis=0;assert(robot_handle_cmd(&c,CMD_NOD)<0);assert(!rail&&!c.busy);
'''),
    ('missing_pwm', '缺少PWM接口时拒绝启动并保持断电', r'''
 hal.pwm_set_us=0;assert(robot_handle_cmd(&c,CMD_NOD)<0);assert(!rail&&!c.busy);
'''),
    ('missing_power', '缺少电源开关接口时拒绝启动', r'''
 hal.servo_rail_enable=0;assert(robot_handle_cmd(&c,CMD_NOD)<0);assert(!c.busy);
'''),
    ('late_tick', '调度延迟后仍保持实际动作400毫秒', r'''
 assert(robot_handle_cmd(&c,CMD_NOD)==0);
 now=100;robot_tick(&c);assert(pulses==1&&last_us!=1500);
 now=499;robot_tick(&c);assert(pulses==1);
 now=500;robot_tick(&c);assert(pulses==2&&last_us==1500);
 now=800;robot_tick(&c);assert(!rail&&!c.busy);
'''),
    ('repeated_park_timeout', '重复停靠不能无限推迟两秒紧急断电', r'''
 unsigned i;assert(robot_handle_cmd(&c,CMD_NOD)==0);
 now=30;robot_tick(&c);
 for(i=100;i<=1900;i+=100){now=i;robot_park(&c);robot_tick(&c);}
 now=2000;robot_tick(&c);assert(!rail&&!c.busy);
'''),
    ('voice_all_bytes', '所有256种字节及重复命令配置检查', r'''
 voice_proto_t v;unsigned i;voice_proto_init(&v);
 for(i=0;i<256;i++)assert(voice_feed_byte(&v,(uint8_t)i)==CMD_UNKNOWN);
 v.configured=1;v.baudrate=9600;v.cmd_node=1;v.cmd_shake=2;v.cmd_wave=3;
 for(i=0;i<256;i++){
 action_cmd_t want=i==1?CMD_NOD:i==2?CMD_SHAKE:i==3?CMD_WAVE:CMD_NONE;
 assert(voice_feed_byte(&v,(uint8_t)i)==want);
 }
 v.cmd_shake=1;
 for(i=0;i<256;i++)assert(voice_feed_byte(&v,(uint8_t)i)==CMD_UNKNOWN);
'''),
]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    # An ID cannot choose an arbitrary filesystem path.
    import uuid
    uuid.UUID(args.project)
    path=root/'runtime/projects'/(args.project+'.json')
    original=path.read_bytes();project=json.loads(original)
    files=project['artifacts']['engineering_draft']['firmware']['files']
    production={k:v for k,v in files.items() if not k.startswith('test_')}
    folder=root/'runtime/boundary-audit'/datetime.now().strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    report={'project_id':args.project,'project_revision':project['revision'],
            'original_source_sha256':source_hash(files),'model_calls':0,'hardware':'not_run',
            'scope':'additional_mock_boundary_tests_not_full_hardware_acceptance','cases':[]}
    for key,title,body in CASES:
        test=PREFIX+body+'\nputs("PASS boundary case");return 0;}\n'
        candidate=dict(production, **{'test_boundaries.c':test})
        result=verify(root,candidate,'Cortex-M0plus')
        row={'id':key,'title':title,'status':result['status'],
             'test_sha256':hashlib.sha256(test.encode()).hexdigest(),'verification':result}
        report['cases'].append(row)
        print(title+': '+result['status'],flush=True)
        (folder/(key+'.c')).write_text(test,encoding='utf-8')
    assert path.read_bytes()==original, 'Project changed during read-only audit'
    report['project_unchanged']=True
    report['passed']=sum(r['status']=='passed' for r in report['cases'])
    report['failed']=sum(r['status']=='failed' for r in report['cases'])
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'报告.md').write_text('# 扩展边界测试\n\n项目与原测试未修改；未调用模型；未使用硬件。\n\n'+
        '\n'.join('- '+r['title']+'：'+r['status'] for r in report['cases'])+
        '\n\n范围：这是额外的软件安全与时序检查，不表示实物验收。\n',encoding='utf-8')
    print('REPORT '+str(folder),flush=True)

if __name__=='__main__':main()
