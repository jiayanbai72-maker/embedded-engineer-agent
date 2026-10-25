"""Frozen mock-register tests; they do not emulate real peripheral timing."""
import json
from pathlib import Path
import re
import subprocess

TEST = r'''#include <assert.h>
#include <string.h>
#include "stm32l031xx.h"
#include "board.h"
RCC_TypeDef fake_rcc;
GPIO_TypeDef fake_gpio;
TIM_TypeDef fake_tim;
USART_TypeDef fake_usart;
uint32_t SystemCoreClock=16000000u;
static uint32_t reload;
void SystemCoreClockUpdate(void){}
uint32_t SysTick_Config(uint32_t ticks){reload=ticks;return 0;}
void SysTick_Handler(void);
int main(void){
 const robot_hal_t *h; uint8_t byte=99;
 board_init();h=board_hal();assert(reload==16000u);assert(h);
 assert(h->millis()==0);SysTick_Handler();assert(h->millis()==1);
#if BOARD_ARMED
 assert(fake_tim.PSC==15u && fake_tim.ARR==19999u);
 assert((fake_gpio.AFR[0] & (15u<<20))==(5u<<20));
 assert((fake_gpio.AFR[0] & (15u<<8))==(2u<<8));
 assert((fake_gpio.AFR[0] & (15u<<12))==(2u<<12));
 h->pwm_set_us(AXIS_HEAD_YAW,1500);assert(fake_tim.CCR1==1500);
 h->pwm_set_us(AXIS_HEAD_PITCH,1600);assert(fake_tim.CCR3==1600);
 h->pwm_set_us(AXIS_ARM_WAVE,1700);assert(fake_tim.CCR4==1700);
 assert(fake_tim.CCR2==0 && !(fake_tim.CCER & TIM_CCER_CC2E));
 h->pwm_set_us(AXIS_HEAD_YAW,999);assert(fake_tim.CCR1==1500);
 h->pwm_set_us(AXIS_HEAD_YAW,2001);assert(fake_tim.CCR1==1500);
 h->servo_rail_enable(0);
 assert(fake_tim.CCR1==0 && fake_tim.CCR3==0 && fake_tim.CCR4==0);
 assert(!(fake_tim.CCER & (TIM_CCER_CC1E|TIM_CCER_CC3E|TIM_CCER_CC4E)));
 fake_usart.ISR=USART_ISR_FE|USART_ISR_RXNE;fake_usart.RDR=42;
 assert(board_uart_read(&byte)==0 && byte==99);
 fake_usart.ISR=USART_ISR_RXNE;
 assert(board_uart_read(&byte)==1 && byte==42);
 assert(!board_uart_read(0));
 /* Reinitializing at unsuitable MSI frequency must not preserve ready flags. */
 h->pwm_set_us(AXIS_HEAD_YAW,1500);assert(fake_tim.CCER & TIM_CCER_CC1E);
 SystemCoreClock=2097152u;
 board_init();h->pwm_set_us(AXIS_HEAD_YAW,1500);assert(fake_tim.CCER==0);
#else
 h->pwm_set_us(AXIS_HEAD_YAW,1500);h->servo_rail_enable(1);h->servo_rail_enable(0);
 assert(!board_uart_read(&byte) && byte==99);
 assert(fake_rcc.IOPENR==0 && fake_rcc.APB1ENR==0);
 assert(fake_gpio.MODER==0 && fake_tim.CR1==0 && fake_tim.CCER==0 && fake_usart.CR1==0);
#endif
 return 0;
}
'''


def run(port):
    header=(port/'vendor/device/stm32l031xx.h').read_text(encoding='utf-8')
    board=(port/'app/board.c').read_text(encoding='utf-8')
    defines={m[1]:m[0] for m in re.finditer(r'^#define\s+([A-Za-z_]\w*)[^\r\n]*',header,re.M)}
    needed=set(re.findall(r'\b(?:RCC|USART|TIM)_[A-Z][A-Za-z0-9_]*',board+TEST))
    while True:
        more=set(re.findall(r'\b[A-Za-z_]\w*', '\n'.join(defines.get(n,'') for n in needed))) & defines.keys()
        if more<=needed:break
        needed|=more
    stub='''#include <stdint.h>
#include "board_config.h"
typedef struct {volatile uint32_t IOPENR,APB1ENR,CFGR;} RCC_TypeDef;
typedef struct {volatile uint32_t MODER,OTYPER,OSPEEDR,PUPDR,AFR[2];} GPIO_TypeDef;
typedef struct {volatile uint32_t CR1,PSC,ARR,CCR1,CCR2,CCR3,CCR4,CCMR1,CCMR2,CCER,EGR;} TIM_TypeDef;
typedef struct {volatile uint32_t CR1,CR2,CR3,BRR,ISR,ICR,RDR,RQR;} USART_TypeDef;
extern RCC_TypeDef fake_rcc;extern GPIO_TypeDef fake_gpio;extern TIM_TypeDef fake_tim;extern USART_TypeDef fake_usart;
extern uint32_t SystemCoreClock;
void SystemCoreClockUpdate(void);uint32_t SysTick_Config(uint32_t);
#define RCC (&fake_rcc)
#define GPIOA (&fake_gpio)
#define TIM2 (&fake_tim)
#define USART2 (&fake_usart)
'''+ '\n'.join(defines[n] for n in sorted(needed) if n in defines and n not in ('RCC','GPIOA','TIM2','USART2'))
    results=[]
    for armed in (0,1):
        folder=port/'host-validation'/str(armed);folder.mkdir(parents=True,exist_ok=True)
        for name in ('board.c','board.h','robot_app.h'):(folder/name).write_bytes((port/'app'/name).read_bytes())
        (folder/'board_config.h').write_text(f'#define BOARD_ARMED {armed}\n#define BOARD_VOICE_BAUD 1000000u\n#define BOARD_PWM_HZ 50u\n')
        (folder/'stm32l031xx.h').write_text(stub,encoding='utf-8')
        (folder/'test_board.c').write_text(TEST,encoding='utf-8')
        vcvars='C:/Program Files (x86)/Microsoft Visual Studio/18/BuildTools/VC/Auxiliary/Build/vcvars64.bat'
        script=f'@echo off\ncall "{vcvars}" >nul\nif errorlevel 1 exit /b 1\ncl /nologo /W3 /utf-8 /UNDEBUG /TC board.c test_board.c /Fe:board_test.exe\nif errorlevel 1 exit /b 1\nboard_test.exe\n'
        (folder/'run.cmd').write_text(script,encoding='utf-8')
        from embedded_agent.draft_verification import run_local
        result=run_local(['cmd','/c','run.cmd'],cwd=folder,capture_output=True,timeout=40)
        results.append({'armed_synthetic_mode':armed,'status':'passed' if result.returncode==0 else 'failed','returncode':result.returncode,'log':(result.stdout+result.stderr).decode('utf-8',errors='replace')})
    (port/'host-validation/report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return results
