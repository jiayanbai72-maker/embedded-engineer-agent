# MCU构建适配模块

通用编译端口 MCUCompiler 与当前 ARMCC 实现分离。后续增加其他编译器不需要把具体芯片写进需求分析核心。
当前只做 C 源码到 MCU 目标文件的编译，不做链接、固件运行、烧录或实机测试。

## 配置与执行

在本机设置 EMBEDDED_AGENT_ARMCC 为可信 ARMCC 可执行文件的绝对路径。客户端不能指定任意工具或命令行参数。
本次检测的安装为 ARMCC 5.06 update 4 build 422；资料工程配置 update 5 build 528，不能等同处理。
处理器配置目前限 Cortex-M0、Cortex-M0plus、Cortex-M3、Cortex-M4；这只是编译目标，不是芯片兼容性验证。

分析动作声明为 mcu_compile、export_documents。用户确认需求并选方案后进入 awaiting_mcu_implementation。
POST 项目 mcu_implementation 接收 revision、files、cpu、rationale；mcu_build 执行真实编译。
控制器也已加入同名白名单动作和修复次数控制。
每次使用独立构建目录，记录编译器版本、命令、退出状态、源码哈希、日志、目标文件及其哈希。
编译失败保持 mcu_build_failed；成功后允许交付源码、目标文件和构建记录。
失败时没有链接固件，成功时同样没有链接固件，硬件验证始终未执行。

示例：设置 PYTHONPATH 为 src 后运行 `python examples/run_mcu_compile.py`。
该例包含明确注入的分号错误、真实编译器诊断、最小修复、重新编译、控制器反馈和交付下载。
分析者已写出的判断由演练脚本重放，不能把它作为自主推理效果证明。

## 后续

新增启动代码、链接脚本/Scatter 文件、目标板内存布局与依赖配置后，再实现固件链接及 HEX/BIN 导出。
这些配置须来自匹配板卡资料，不能从 Cortex-M3 名称推断。随后接入烧录与实机验证。

命令参数依据官方 ARMCC 文档：
https://www.keil.com/support/man/docs/armcc/
