"""Collect a reproducible, bounded cross-vendor reference library; no installation."""
import concurrent.futures as cf
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from pypdf import PdfReader
import collect_official_knowledge as base

ROOT = base.ROOT
OUT = ROOT / 'knowledge/official/general-v1'
DOMAINS = ('ti.com', 'st.com', 'espressif.com', 'espressif.com.cn', 'raspberrypi.com', 'raspberrypi.org',
 'nxp.com', 'nordicsemi.com', 'bosch-sensortec.com', 'sensirion.com', 'analog.com',
 'microchip.com', 'ww1.microchip.com', 'freertos.org', 'zephyrproject.org',
 'arm.com', 'github.com', 'githubusercontent.com', 'codeload.github.com',
 'micropython.org', 'docs.lvgl.io', 'lvgl.io', 'littlefs-project.github.io',
 'modbus.org', 'oasis-open.org', 'rfc-editor.org', 'onlinedocs.microchip.com',
 'docs.arduino.cc', 'docs.platformio.org', 'openocd.org', 'sourceware.org',
 'cmake.org', 'gcc.gnu.org', 'mbed-tls.readthedocs.io', 'docs.mcuboot.com', 'arm-software.github.io')

def allowed(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme == 'https' and any(p.hostname == d or (p.hostname or '').endswith('.'+d) for d in DOMAINS)

def fetch(url):
    if not allowed(url): raise ValueError('outside explicit official-source domains')
    url = urllib.parse.quote(url, safe=':/?=&%+@,;')
    for attempt in range(2):
        try:
            with urllib.request.build_opener(base.SafeRedirect()).open(
                urllib.request.Request(url, headers=base.HEADERS), timeout=25) as response:
                if int(response.headers.get('Content-Length','0')) > base.MAX_BYTES:
                    raise ValueError('file exceeds collection size cap')
                data=response.read(base.MAX_BYTES+1)
                if len(data)>base.MAX_BYTES: raise ValueError('file exceeds collection size cap')
                expected=int(response.headers.get('Content-Length','0'))
                if expected and len(data)!=expected: raise ValueError('incomplete HTTP response body')
                content_range=response.headers.get('Content-Range')
                if content_range: raise ValueError('partial HTTP response is not a complete document: '+content_range)
                return data,response.geturl(),response.headers.get('Content-Type','')
        except Exception:
            if attempt: raise
            time.sleep(0.5)

def items():
    out=[]
    def add(cat,url,name=None): out.append(base.task(cat,url,name,note='Reference only; exact variant, revision and operating conditions require review.'))
    # TI's stable product datasheet endpoints, across independent engineering domains.
    ti={
      'sensors/temperature':['tmp117','tmp102','lm35'],
      'sensors/light':['opt3001'], 'sensors/current':['ina219','ina226','ina180'],
      'sensors/hall':['drv5032'], 'analog/adc':['ads1115','ads1015','ads1220','ads1256'],
      'analog/dac':['dac80501','dac7571'], 'analog/opamp':['opa333','opa320','lm358'],
      'power/ldo':['tps7a02','tps7a20','tlv755p','lp5907'],
      'power/buck':['tps62160','tps62840','tps5430','lm2596'],
      'power/boost':['tps61023','tps61291'], 'power/buck-boost':['tps63070','tps63031'],
      'power/battery-charger':['bq24074','bq25185','bq25895'],
      'power/battery-gauge':['bq27441-g1'], 'power/battery-protection':['bq2970'],
      'power/load-switch':['tps22918'], 'power/supervisor':['tps3839'],
      'actuators/dc-motor':['drv8833','drv8871'], 'actuators/stepper':['drv8825','drv8424'],
      'actuators/solenoid':['drv110'], 'interfaces/rs485':['thvd1450','sn65hvd3082e'],
      'interfaces/can':['tcan1042h','tcan332'], 'interfaces/rs232':['max3232'],
      'interfaces/level-shifting':['txs0108e','txb0108','sn74lvc1t45'],
      'interfaces/i2c':['tca9548a','tca9535'], 'interfaces/usb-power':['tusb320'],
      'audio/amplifier':['tpa2016d2','tpa3116d2'], 'audio/codec':['tlv320aic3104'],
      'protection/esd':['t pd2eusb30'.replace(' ','')],
    }
    for cat,parts in ti.items():
        for part in parts: add(cat,'https://www.ti.com/lit/ds/symlink/'+part+'.pdf',part+'.pdf')
    for part in ['stm32f103c8','stm32f411ce','stm32g071rb','stm32g431cb','stm32l476rg','stm32u575zi','stm32h743zi','stm32wb55rg','stm32wl55jc']:
        add('mcu/ST/'+part,'https://www.st.com/resource/en/datasheet/'+part+'.pdf')
    for part in ['esp32','esp32-c3','esp32-s3','esp32-c6','esp32-h2','esp32-c2','esp32-c5','esp32-p4']:
        add('mcu/Espressif/'+part,'https://www.espressif.com/sites/default/files/documentation/'+part+'_datasheet_en.pdf')
    for part in ['esp32-wroom-32e_esp32-wroom-32ue','esp32-c3-wroom-02','esp32-s3-wroom-1_wroom-1u']:
        add('wireless/modules','https://www.espressif.com/sites/default/files/documentation/'+part+'_datasheet_en.pdf')
    fixed=[
      ('mcu/RaspberryPi/RP2040','https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf'),
      ('mcu/RaspberryPi/RP2350','https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf'),
      ('hardware/reference-design','https://datasheets.raspberrypi.com/rp2040/hardware-design-with-rp2040.pdf'),
      ('boards/RaspberryPi','https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf'),
      ('boards/RaspberryPi','https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf'),
      ('sensors/environment','https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf'),
      ('sensors/environment','https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp390-ds002.pdf'),
      ('sensors/imu','https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf'),
      ('sensors/imu','https://www.st.com/resource/en/datasheet/lsm6dsox.pdf'),
      ('sensors/accelerometer','https://www.st.com/resource/en/datasheet/lis3dh.pdf'),
      ('sensors/distance','https://www.st.com/resource/en/datasheet/vl53l1x.pdf'),
      ('sensors/humidity','https://sensirion.com/resource/datasheet/sht4x','SHT4x-datasheet.pdf'),
      ('sensors/co2','https://sensirion.com/resource/datasheet/scd4x','SCD4x-datasheet.pdf'),
      ('sensors/air-quality','https://sensirion.com/resource/datasheet/sgp40','SGP40-datasheet.pdf'),
      ('sensors/particulate','https://sensirion.com/resource/datasheet/sps30','SPS30-datasheet.pdf'),
      ('memory/eeprom','https://www.st.com/resource/en/datasheet/m24c64-w.pdf'),
      ('interfaces/pwm','https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf'),
      ('protocols/i2c','https://www.nxp.com/docs/en/user-guide/UM10204.pdf'),
      ('protocols/modbus','https://www.modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf'),
      ('protocols/modbus','https://www.modbus.org/docs/Modbus_over_serial_line_V1_02.pdf'),
      ('protocols/mqtt','https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.pdf'),
      ('protocols/coap','https://www.rfc-editor.org/rfc/rfc7252.txt'),
      ('protocols/tls','https://www.rfc-editor.org/rfc/rfc8446.txt'),
      ('protocols/http','https://www.rfc-editor.org/rfc/rfc9110.txt'),
      ('protocols/cbor','https://www.rfc-editor.org/rfc/rfc8949.txt'),
      ('protocols/json','https://www.rfc-editor.org/rfc/rfc8259.txt'),
      ('hardware/layout','https://www.ti.com/lit/an/szza009/szza009.pdf'),
      ('hardware/rs485-design','https://www.ti.com/lit/an/slla272d/slla272d.pdf'),
      ('hardware/i2c-design','https://www.ti.com/lit/an/slva704/slva704.pdf'),
      ('hardware/opamp-design','https://www.ti.com/lit/an/sboa092b/sboa092b.pdf'),
      ('hardware/decoupling','https://www.analog.com/media/en/training-seminars/tutorials/MT-101.pdf'),
      ('hardware/grounding','https://www.analog.com/media/en/training-seminars/tutorials/MT-031.pdf'),
      ('analog/temperature','https://www.analog.com/media/en/technical-documentation/data-sheets/DS18B20.pdf'),
      ('time/rtc','https://www.analog.com/media/en/technical-documentation/data-sheets/DS3231.pdf'),
      ('interfaces/spi-uart','https://www.nxp.com/docs/en/data-sheet/SC16IS752_SC16IS762.pdf'),
      ('interfaces/nfc','https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf'),
    ]
    for entry in fixed: add(*entry)
    pages=[
      ('software/rtos/FreeRTOS','https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/01-Tasks-and-co-routines/01-Tasks-overview'),
      ('software/rtos/Zephyr','https://docs.zephyrproject.org/latest/introduction/index.html'),
      ('software/rtos/Zephyr','https://docs.zephyrproject.org/latest/kernel/services/threads/index.html'),
      ('software/rtos/Zephyr','https://docs.zephyrproject.org/latest/build/dts/intro-syntax-structure.html'),
      ('software/rtos/Zephyr','https://docs.zephyrproject.org/latest/hardware/porting/board_porting.html'),
      ('software/sdk/ESP-IDF','https://docs.espressif.com/projects/esp-idf/en/stable/esp32/get-started/index.html'),
      ('software/sdk/ESP-IDF','https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/sleep_modes.html'),
      ('software/sdk/ESP-IDF','https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/ota.html'),
      ('software/sdk/ESP-IDF','https://docs.espressif.com/projects/esp-idf/en/stable/esp32/security/secure-boot-v2.html'),
      ('software/sdk/ESP-IDF','https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/i2c.html'),
      ('software/sdk/ESP-IDF','https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html'),
      ('software/MicroPython','https://docs.micropython.org/en/latest/reference/index.html'),
      ('software/MicroPython','https://docs.micropython.org/en/latest/library/machine.html'),
      ('software/gui/LVGL','https://docs.lvgl.io/master/intro/introduction/index.html'),
      ('software/build/CMake','https://cmake.org/cmake/help/latest/manual/cmake-toolchains.7.html'),
      ('software/build/PlatformIO','https://docs.platformio.org/en/latest/projectconf/index.html'),
      ('software/debug/OpenOCD','https://openocd.org/doc/html/General-Commands.html'),
      ('software/debug/GDB','https://sourceware.org/gdb/current/onlinedocs/gdb.html/Remote-Debugging.html'),
      ('software/compiler/GCC','https://gcc.gnu.org/onlinedocs/gcc/Warning-Options.html'),
      ('software/security/MCUboot','https://docs.mcuboot.com/design.html'),
      ('software/security/MbedTLS','https://mbed-tls.readthedocs.io/en/latest/kb/how-to/mbedtls-tutorial/'),
      ('software/architecture/CMSIS','https://arm-software.github.io/CMSIS_6/latest/General/index.html'),
      ('software/testing/CMSIS','https://arm-software.github.io/CMSIS-View/latest/overview.html'),
      ('wireless/BLE/Nordic','https://docs.nordicsemi.com/bundle/ncs-latest/page/nrf/index.html'),
      ('mcu/NXP','https://www.nxp.com/docs/en/data-sheet/LPC55S6x.pdf'),
      ('mcu/NXP','https://www.nxp.com/docs/en/data-sheet/IMXRT1060CEC.pdf'),
    ]
    for cat,url in pages:
        name=('reference-'+hashlib.sha256(url.encode()).hexdigest()[:8]+'.html') if not url.endswith('.pdf') else None
        add(cat,url,name)
    return out

REPOS=[
 ('software/rtos/FreeRTOS','FreeRTOS/FreeRTOS-Kernel'),
 ('software/storage/littlefs','littlefs-project/littlefs'),
 ('software/network/lwIP','lwip-tcpip/lwip'),
 ('software/network/MQTT','FreeRTOS/coreMQTT'),
 ('software/testing/Unity','ThrowTheSwitch/Unity'),
 ('software/testing/CMock','ThrowTheSwitch/CMock'),
 ('software/drivers/Bosch','boschsensortec/BME280_SensorAPI'),
 ('software/drivers/Bosch','boschsensortec/BMI270_SensorAPI'),
 ('software/drivers/Sensirion','Sensirion/embedded-i2c-sht4x'),
 ('software/drivers/Sensirion','Sensirion/embedded-i2c-scd4x'),
 ('software/serialization','DaveGamble/cJSON'),
 ('software/security/MCUboot','mcu-tools/mcuboot'),
]

class PlainText(HTMLParser):
    def __init__(self): super().__init__(); self.hidden=0; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.hidden+=1
        if tag in ('p','div','h1','h2','h3','li','tr','br'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)

def extract(entry):
    result={k:entry[k] for k in ('url','local_path')}
    try:
        path=ROOT/entry['local_path']
        if path.suffix.lower()=='.pdf':
            reader=PdfReader(path); texts=[]; pages=[]; offset=0
            for n,page in enumerate(reader.pages,1):
                value=(page.extract_text() or '')+'\n\f\n'
                pages.append({'page':n,'start':offset,'end':offset+len(value)})
                offset+=len(value); texts.append(value)
            txt=''.join(texts)
            idx=path.with_suffix('.pages.json'); idx.write_text(json.dumps(pages),encoding='utf-8')
            result.update(pages=len(pages),page_index=idx.relative_to(ROOT).as_posix())
        elif path.suffix.lower()=='.html':
            parser=PlainText(); parser.feed(path.read_text(encoding='utf-8',errors='replace'))
            txt=re.sub(r'\n[ \t\n]+','\n',''.join(parser.parts))
        else: return result
        target=path.with_suffix('.txt'); target.write_text(txt,encoding='utf-8')
        result.update(text_path=target.relative_to(ROOT).as_posix(),text_characters=len(txt),
                      extraction_status='text_available' if len(txt.strip())>100 else 'needs_review_or_ocr')
    except Exception as exc: result.update(extraction_status='failed',extraction_error=str(exc)[:250])
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    base.OUT=OUT; base.allowed=allowed; base.fetch=fetch; base.MAX_BYTES=48*1024*1024
    manifest_path=OUT/'manifest.json'
    m=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
       'scope':'cross-vendor reference library, not validated selection evidence',
       'collected_at_utc':datetime.now(timezone.utc).isoformat(),'sources':[],'repository_pins':[],'discovery_errors':[]}
    def checkpoint(): manifest_path.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
    pending=items()
    for cat,repo in REPOS:
        try:
            existing=next((p for p in m['repository_pins'] if p['repository']==repo),None)
            if existing: sha=existing['commit']
            else:
                meta=json.loads(fetch('https://api.github.com/repos/'+repo+'/commits?per_page=1')[0])
                sha=meta[0]['sha']
                m['repository_pins'].append({'repository':repo,'commit':sha,'collected_at_utc':datetime.now(timezone.utc).isoformat(),
                    'note':'Repository snapshot only; nested submodules and build dependencies are not installed or guaranteed present. Preserve upstream licenses.'})
            pending.append(base.task(cat,'https://codeload.github.com/'+repo+'/zip/'+sha,repo.split('/')[-1]+'-'+sha[:12]+'.zip'))
        except Exception as exc:
            m['discovery_errors'].append({'source':repo,'error':str(exc)[:250]})
        checkpoint()
    known={s['url'] for s in m['sources'] if s['status']=='downloaded'}
    unique={x['url']:x for x in pending if x['url'] not in known}
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        for result in pool.map(base.save,unique.values()):
            m['sources']=[s for s in m['sources'] if s['url']!=result['url']]+[result]
            checkpoint()
    targets=[s for s in m['sources'] if s['status']=='downloaded' and s['name'].endswith(('.pdf','.html')) and not s.get('text_path')]
    with cf.ProcessPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(extract,s):s for s in targets}
        for future in cf.as_completed(futures):
            entry=futures[future]; entry.update(future.result()); checkpoint()
            print(json.dumps({'indexed':entry['name'],'pages':entry.get('pages'),'characters':entry.get('text_characters'),'status':entry.get('extraction_status')},ensure_ascii=False),flush=True)
    docs=[]
    for s in m['sources']:
        if s['status']!='downloaded': continue
        docs.append({'id':'DOC-'+s['sha256'][:16], 'category':s['category'],'title':s['name'],
           'source_url':s['url'],'final_url':s['final_url'],'sha256':s['sha256'],
           'file':s['local_path'],'text':s.get('text_path'),'page_index':s.get('page_index'),
           'pages':s.get('pages'),'reviewed':False,'scope':'reference_not_selection_evidence'})
    (OUT/'document-index.json').write_text(json.dumps({'schema_version':1,'documents':docs},ensure_ascii=False,indent=2),encoding='utf-8')
    groups={}
    for s in m['sources']:
        if s['status']=='downloaded': groups.setdefault(s['category'],[]).append(s)
    ok=[s for s in m['sources'] if s['status']=='downloaded']; failed=[s for s in m['sources'] if s['status']!='downloaded']
    lines=['# 通用嵌入式官方资料库（第一轮扩展）','',f'成功 {len(ok)} 项；失败 {len(failed)} 项；分类 {len(groups)} 项；原始文件 {sum(s["size_bytes"] for s in ok)/1024**2:.2f} MiB。',
      '', '本轮按器件与工程主题扩展，非全行业穷尽。网页为单页快照，不是整站离线镜像。SDK/驱动为带提交号的源码归档，不是完整依赖安装。',
      '', '资料未经逐项参数审核（reviewed=false），尚未接入运行中 Agent 的知识搜索。PDF 提取不保证表格和图示语义完整，选型证据需核对原文与条件。归档内代码和程序未执行。',
      '', '## 覆盖目录','']
    for cat,entries in sorted(groups.items()):
        lines += ['### '+cat,'']
        lines += ['- ['+e['name']+']('+Path(e['local_path']).relative_to(OUT.relative_to(ROOT)).as_posix()+')' for e in entries]
        lines+=['']
    lines+=['## 失败与需补充','']
    lines += ['- '+e['url']+'：'+e.get('error','unknown') for e in failed]
    lines += ['- '+str(e) for e in m['discovery_errors']]
    lines+=['','## 下一轮重点','',
      '国产 MCU（GD32、CH32、AT32、HC32）、蜂窝/GNSS/LoRa 模块、显示屏控制器、摄像头、存储器、电池与电源完整参考设计、EMC/ESD 和可靠性验证仍需按具体厂家继续扩展。',
      '付费标准、需登录授权资源、采购报价、仿制模块参数和实测数据不包含在本轮公开资料中。不得用类似型号参数替代实际器件。']
    (OUT/'收集结果.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'downloaded':len(ok),'failed':len(failed),'categories':len(groups),
       'pdfs':sum(s['name'].endswith('.pdf') for s in ok),'indexed':sum(bool(s.get('text_path')) for s in ok)},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
