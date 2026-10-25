"""Live Agent C implementations against frozen independent contracts; no board required."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from embedded_agent.local_model import LocalSettings, BudgetPaused
from embedded_agent.draft_verification import verify
from run_expanded_tests import Metered

CASES={
'remote_replay_watchdog': (
'''#include <stdint.h>
void reset(void);
int step(uint32_t now,int has_frame,uint8_t seq,int command,int estop,int clear);
''',
'''遥控移动机器人纯C状态机。step返回电机是否运行。初始停机。command=1运行、0停止。每次先处理estop：锁存停车，帧不得解除；仅clear且estop为0解除锁存，但该次帧必须忽略。其他clear无效果。所有完整停止帧即使重复/旧序号也立即停车，但只有新序号可更新接收序号和心跳。首帧为新帧；以后uint8模差1..127为新，0或128..255为旧，旧运行帧不能启动或续心跳。有效运行帧在未锁存时可启动/刷新心跳。先处理500ms看门狗到期停车，再处理本次新帧（可显式重新启动）；旧帧不得复活。uint32时间回绕，间隔小于2^31。reset清除全部。''',
'''#include <assert.h>
#include "contract.h"
int main(void){uint32_t now=0,seed=943u,last=0;unsigned i;int on=0,have=0,latch=0;uint8_t prev=0;
reset();assert(!step(0,0,0,0,0,0));assert(step(10,1,254,1,0,0));assert(step(509,1,254,1,0,0));assert(!step(510,1,254,1,0,0));assert(step(511,1,255,1,0,0));assert(step(512,1,0,1,0,0));assert(!step(513,1,200,0,0,0));assert(!step(514,1,0,1,0,0));assert(step(515,1,1,1,0,0));assert(!step(516,1,2,1,1,0));assert(!step(517,1,3,1,0,0));assert(!step(518,1,4,1,0,1));assert(step(519,1,5,1,0,0));
reset();assert(step(0xfffffff0u,1,1,1,0,0));assert(step(483,0,0,0,0,0));assert(!step(484,0,0,0,0,0));
reset();for(i=0;i<12000;i++){int frame,cmd,fault,clear,result;uint8_t seq,d;seed=seed*1664525u+1013904223u;now+=(seed>>24)+1u;frame=(int)(seed&1u);cmd=(int)((seed>>1)&1u);fault=(seed%97u)==0;clear=(seed%53u)==0;seq=(uint8_t)(seed>>9);d=(uint8_t)(seq-prev);
if(fault){latch=1;on=0;}else if(latch){on=0;if(clear)latch=0;}else{if(on&&(uint32_t)(now-last)>=500u)on=0;if(frame){int fresh=!have||(d>0&&d<128);if(!cmd)on=0;if(fresh){have=1;prev=seq;last=now;on=cmd;}}}
result=step(now,frame,seq,cmd,fault,clear);assert(result==on);}
return 0;}
'''),
'multi_zone_interlock': (
'''#include <stdint.h>
void reset(void);
unsigned step(uint32_t now,unsigned request,unsigned healthy,int emergency);
''',
'''三分区浇水控制器，request与healthy低3位各对应区0..2，返回实际阀门位掩码。最多一个阀门开。初始无冷却，可立即选择请求且健康的最低编号区。一旦运行，其他区不能抢占；当前区请求撤销、不健康、紧停或本次连续运行满1000ms立即停。任何停止后所有区至少冷却100ms，达到边界可选新区；停止当次不允许重新选择。紧停时不得启动；若本已停且紧停，不重复重置冷却。健康恢复不得跳过冷却。uint32模差。reset回初始。''',
'''#include <assert.h>
#include "contract.h"
int main(void){unsigned k,active=0;uint32_t since=0,stopped=0,now=0,r=87;int cooling=0;
reset();assert(step(0,7,7,0)==1);assert(step(999,7,7,0)==1);assert(!step(1000,7,7,0));assert(!step(1099,7,7,0));assert(step(1100,6,7,0)==2);assert(!step(1101,6,5,0));assert(!step(1200,7,7,0));assert(step(1201,4,7,0)==4);assert(!step(1202,7,7,1));assert(!step(1302,7,7,1));assert(step(1303,7,7,0)==1);
reset();assert(step(0xffffff00u,1,7,0)==1);assert(!step(744,1,7,0));assert(!step(843,1,7,0));assert(step(844,2,7,0)==2);
reset();for(k=0;k<15000;k++){unsigned req,health,actual;int emergency;r=r*1664525u+1013904223u;now+=(r>>27)+1;req=(r>>7)&7u;health=(r>>15)&7u;emergency=r%89u==0;
if(active){if(emergency||!(active&req&health)||(uint32_t)(now-since)>=1000u){active=0;cooling=1;stopped=now;}}
else if(!emergency&&(!cooling||(uint32_t)(now-stopped)>=100u)){unsigned eligible=req&health;active=eligible&(~eligible+1u);if(active)since=now;}
actual=step(now,req,health,emergency);assert(actual==active);assert(!(actual&(actual-1u)));}
return 0;}
'''),
'atomic_config_recovery': (
'''#include <stdint.h>
typedef struct {uint16_t sequence;uint16_t brightness;uint16_t timeout;uint16_t checksum;uint16_t committed;} Record;
int recover(const Record slots[2],uint16_t *brightness,uint16_t *timeout);
''',
'''双槽掉电配置恢复，不读写硬件。recover选择有效最新记录，返回槽0或1；无有效返回-1并输出亮度50/延时30。有效要求committed==0xA55A，brightness<=100，timeout为1..3600，checksum==(sequence XOR brightness XOR timeout XOR 0x6D39)低16位。两有效时uint16模差(slot1.seq-slot0.seq)为1..32767选1，其他含相等或半范围32768选0。只读输入，输出指针有效。覆盖写入新槽过程中每个字段写入前以及提交前掉电均不得覆盖旧的有效配置；最终提交完整后选新。注意序号回绕。''',
'''#include <assert.h>
#include <string.h>
#include "contract.h"
static Record make(uint16_t seq,uint16_t b,uint16_t t){Record r;r.sequence=seq;r.brightness=b;r.timeout=t;r.checksum=(uint16_t)(seq^b^t^0x6d39u);r.committed=0xa55a;return r;}
int main(void){Record a[2],copy[2];uint16_t b,t;unsigned i,j;
memset(a,0,sizeof(a));assert(recover(a,&b,&t)==-1&&b==50&&t==30);a[0]=make(65535,20,60);a[1]=make(0,80,120);assert(recover(a,&b,&t)==1&&b==80&&t==120);a[1]=make(32767,80,120);assert(recover(a,&b,&t)==0);a[1]=make(65535,80,120);assert(recover(a,&b,&t)==0);
for(i=0;i<300;i++){Record fresh;uint16_t seq=(uint16_t)(65500u+i);a[0]=make(seq,20,60);fresh=make((uint16_t)(seq+1u),80,120);memset(&a[1],0,sizeof(Record));
for(j=0;j<5;j++){if(j==1)a[1].sequence=fresh.sequence;if(j==2)a[1].brightness=fresh.brightness;if(j==3)a[1].timeout=fresh.timeout;if(j==4)a[1].checksum=fresh.checksum;assert(recover(a,&b,&t)==0&&b==20&&t==60);}
a[1].committed=fresh.committed;memcpy(copy,a,sizeof(a));assert(recover(a,&b,&t)==1&&b==80&&t==120);assert(memcmp(copy,a,sizeof(a))==0);
a[1].checksum^=1;assert(recover(a,&b,&t)==0);a[1]=make((uint16_t)(seq+1u),101,120);assert(recover(a,&b,&t)==0);a[1]=make((uint16_t)(seq+1u),80,0);assert(recover(a,&b,&t)==0);a[1]=make((uint16_t)(seq+1u),80,3601);assert(recover(a,&b,&t)==0);}
return 0;}
''')}

def main():
    if '--live' not in sys.argv:raise SystemExit('Use --live for paid configured Agent calls')
    model=Metered(LocalSettings(ROOT).model())
    folder=ROOT/'runtime/hard-c-tests'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder.mkdir(parents=True);rows=[]
    for name,(header,contract,test) in CASES.items():
        history=[];files=None;start=len(model.calls)
        for attempt in range(3):
            try:
                answer=model.generate(role='c_contract_writer',instruction='按冻结契约实现C99纯逻辑模块，只返回files={"implementation.c":完整源码}和rationale。include contract.h；不得修改头文件、测试、断言，禁止文件/网络/进程/内联汇编等外部操作。不要写main。不使用动态内存。失败时自主依据实际编译和断言日志修复。',context={'contract':contract,'contract.h':header,'test_contract.c':test,'current_source':files,'last_result':history[-1] if history else None})
                files=answer.get('files',{})
                if set(files)!={'implementation.c'}:raise ValueError('Only implementation.c is allowed')
                source=files['implementation.c']
                # This is a restricted test harness, not a security sandbox.
                import re
                if re.search(r'\b(system|fopen|freopen|remove|rename|exit|abort|assert|__asm)\s*\(|#\s*(define\s+(assert|NDEBUG)|include\s*[<"](?:stdio|stdlib|windows|process))',source):raise ValueError('Source violates isolated exercise scope')
                result=verify(ROOT,dict(files,**{'contract.h':header,'test_contract.c':test}),'Cortex-M3')
                history.append({'status':result['status'],'files':files,'result':result})
            except BudgetPaused:raise
            except Exception as exc:history.append({'status':'failed','error':str(exc)[:1600],'files':files})
            (folder/(name+'.json')).write_text(json.dumps({'contract':contract,'header':header,'tests':test,'history':history,'calls':model.calls[start:]},ensure_ascii=False,indent=2),encoding='utf-8')
            print(name,attempt+1,history[-1]['status'],flush=True)
            if history[-1]['status']=='passed':break
        rows.append({'case':name,'passed':history[-1]['status']=='passed','attempts':len(history),'tests_sha256':hashlib.sha256(test.encode()).hexdigest()})
    hit=sum(c.get('cache_hit_tokens') or 0 for c in model.calls);miss=sum(c.get('cache_miss_tokens') or 0 for c in model.calls)
    report={'cases':rows,'calls':model.calls,'cost_cny':sum(c['accounted_cny'] for c in model.calls),'cache_hit_tokens':hit,'cache_miss_tokens':miss,'cache_hit_ratio':hit/(hit+miss) if hit+miss else None,'hardware':'not_run','scope':'C host assertions and Cortex-M3 object compilation; no firmware linking or real peripheral validation'}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='calls'},ensure_ascii=False),flush=True);print(folder,flush=True)

if __name__=='__main__':main()
