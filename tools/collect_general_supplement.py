"""Resolved official redirects plus cross-platform driver and reference examples."""
import collect_general_knowledge as g

g.OUT=g.ROOT/'knowledge/official/general-v1-supplement'
g.DOMAINS+=('wch.cn','wch-ic.com')
def supplementary_items():
    out=[]
    for part in ['esp32','esp32-c3','esp32-s3','esp32-c6','esp32-h2','esp32-c2','esp32-c5','esp32-p4',
                 'esp32-wroom-32e_esp32-wroom-32ue','esp32-c3-wroom-02','esp32-s3-wroom-1_wroom-1u']:
        out.append(g.base.task('mcu/Espressif', 'https://www.espressif.com/sites/default/files/documentation/'+part+'_datasheet_en.pdf'))
    for category,url,name in [
        ('software/CMSIS','https://arm-software.github.io/CMSIS_6/latest/General/index.html','CMSIS6-overview.html'),
        ('software/CMSIS','https://arm-software.github.io/CMSIS-View/latest/overview.html','CMSIS-view-overview.html'),
        ('protocols/modbus','https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf','Modbus-application.pdf'),
        ('protocols/modbus','https://modbus.org/docs/Modbus_over_serial_line_V1_02.pdf','Modbus-serial.pdf'),
        ('protocols/modbus','https://www.modbus.org/file/secure/modbusprotocolspecification.pdf','Modbus-application-alternative.pdf'),
        ('display/LED','https://www.analog.com/media/en/technical-documentation/data-sheets/MAX7219-MAX7221.pdf','MAX7219-MAX7221.pdf'),
        ('debug/WCH','https://www.wch.cn/uploads/file/20240829/1724894517211808.pdf','WCH-LinkE-manual.pdf'),
        ('mcu/Nordic','https://infocenter.nordicsemi.com/pdf/nRF52840_PS_v1.11.pdf','nRF52840-product-specification.pdf'),
    ]: out.append(g.base.task(category,url,name))
    return out
g.items=supplementary_items
g.REPOS=[('software/drivers/Nordic','NordicSemiconductor/nrfx'),
         ('software/examples/RaspberryPi','raspberrypi/pico-examples'),
         ('software/sdk/Arduino-AVR','arduino/ArduinoCore-avr'),
         ('software/CMSIS','ARM-software/CMSIS_6')]
if __name__=='__main__': g.main()
