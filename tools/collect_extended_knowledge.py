"""Additional official Chinese MCU, radio, storage, display and network references."""
import hashlib
from pathlib import Path
import collect_general_knowledge as g

g.OUT=g.ROOT/'knowledge/official/general-v1-extension'
g.DOMAINS+=('gd32mcu.com','wch.cn','wch-ic.com','quectel.com','semtech.com','u-blox.com','wiznet.io','rt-thread.org')

def extra_items():
    data=[
      ('mcu/GigaDevice','https://www.gd32mcu.com/data/documents/userManual/GD32F30x_User_Manual_Rev3.0_CN.pdf'),
      ('mcu/WCH','https://www.wch.cn/products/CH32V003.html'),
      ('debug/WCH','https://www.wch.cn/uploads/file/20240829/1724894517211808.pdf','WCH-LinkE-manual.pdf'),
      ('wireless/cellular/Quectel','https://quectel.com/content/uploads/2024/02/Quectel_BG95_Series_Hardware_Design_V1.3-2.pdf'),
      ('wireless/cellular/Quectel','https://www.quectel.com/product/lpwa-bg95-cat-m1-cat-nb2-egprs-series/'),
      ('wireless/GNSS/u-blox','https://content.u-blox.com/sites/default/files/MAX-M10S_DataSheet_UBX-20035208.pdf'),
      ('wireless/GNSS/u-blox','https://content.u-blox.com/sites/default/files/MAX-M10S_IntegrationManual_UBX-20053088.pdf'),
      ('wireless/LoRa/Semtech','https://www.semtech.com/products/wireless-rf/lora-connect/sx1262'),
      ('wireless/LoRa/Semtech','https://www.semtech.com/uploads/documents/DS_SX1261-2_V2.1.pdf'),
      ('display/LED','https://www.analog.com/media/en/technical-documentation/data-sheets/MAX7219-MAX7221.pdf'),
      ('display/LED','https://www.st.com/resource/en/datasheet/stp16cpc26.pdf'),
      ('memory/FRAM','https://www.ti.com/lit/ds/symlink/msp430fr2433.pdf'),
      ('memory/eeprom','https://www.st.com/resource/en/datasheet/m95m02-dr.pdf'),
      ('memory/flash','https://www.st.com/resource/en/datasheet/m25p16.pdf'),
      ('ethernet/PHY','https://www.ti.com/lit/ds/symlink/dp83825i.pdf'),
      ('ethernet/PHY','https://www.ti.com/lit/ds/symlink/dp83848c.pdf'),
      ('ethernet/WIZnet','https://docs.wiznet.io/Product/Chip/Ethernet/W5500/overview'),
      ('ethernet/WIZnet','https://docs.wiznet.io/img/products/w5500/W5500_ds_v110e.pdf'),
      ('hardware/isolation','https://www.ti.com/lit/ds/symlink/iso7741.pdf'),
      ('hardware/gate-driver','https://www.ti.com/lit/ds/symlink/ucc27511.pdf'),
      ('power/usb-pd','https://www.ti.com/lit/ds/symlink/tps25750.pdf'),
      ('sensors/touch','https://www.ti.com/lit/ds/symlink/fdc1004.pdf'),
      ('sensors/inductive','https://www.ti.com/lit/ds/symlink/ldc1612.pdf'),
      ('sensors/force-adc','https://www.ti.com/lit/ds/symlink/ads1232.pdf'),
      ('sensors/thermal','https://www.ti.com/lit/ds/symlink/tmp007.pdf'),
      ('software/rtos/RT-Thread','https://www.rt-thread.org/document/site/'),
      ('software/storage/littlefs','https://raw.githubusercontent.com/littlefs-project/littlefs/master/DESIGN.md'),
      ('software/gui/u8g2','https://raw.githubusercontent.com/olikraus/u8g2/master/README.md'),
      ('software/gui/LVGL','https://docs.lvgl.io/master/details/integration/overview.html'),
    ]
    out=[]
    for record in data:
        cat,url,*names=record
        name=names[0] if names else None
        if not name and not Path(url).suffix:
            name='reference-'+hashlib.sha256(url.encode()).hexdigest()[:8]+'.html'
        out.append(g.base.task(cat,url,name,note='Official/upstream reference; verify exact version and conditions before selection. Mutable branch URLs are hashed snapshots, not version tags.'))
    return out

g.items=extra_items
g.REPOS=[('mcu/WCH','openwch/ch32v003'),('mcu/WCH','openwch/ch32v20x'),
         ('wireless/LoRa/Semtech','Lora-net/sx126x_driver'),
         ('ethernet/WIZnet','Wiznet/ioLibrary_Driver'),
         ('software/rtos/RT-Thread','RT-Thread/rtthread-nano'),
         ('software/camera/Espressif','espressif/esp32-camera')]
if __name__=='__main__': g.main()
