"""Artifact-based scope assessment, independent of board type and model provider."""
import os
from pathlib import Path
from .hardware import serial_modules


def capabilities(app):
    compiler = Path(os.environ.get('EMBEDDED_AGENT_ARMCC', ''))
    compiler_present = compiler.is_absolute() and compiler.is_file()
    uvision = Path(os.environ.get('EMBEDDED_AGENT_UVISION', r'C:\Keil_v5\UV4\UV4.exe'))
    index = app.documents.status()
    model_ready = os.environ.get('EMBEDDED_AGENT_AUTONOMY') == '1' and all(os.environ.get(k, '').strip() for k in ('EMBEDDED_AGENT_ENDPOINT', 'EMBEDDED_AGENT_MODEL', 'EMBEDDED_AGENT_API_KEY'))
    online=getattr(app,'online_research',None)
    serial_ready = serial_modules(app.store.root.parents[1])[0] is not None
    report={'mode': 'analyst_assisted', 'items': [
        {'id': 'planning', 'status': 'available', 'detail': '外部分析者规划，系统校验依赖并记录执行结果'},
        {'id': 'document_search', 'status': 'available' if index.get('ready') and index.get('catalog_current') else 'needs_configuration', 'detail': '本地索引检索，来源与页码可追溯'},
        {'id':'online_documents','status':'configured_unverified' if online and online.settings()['enabled'] else 'not_connected','detail':'受控原厂域名公开RSS搜索及HTTPS下载入库；可用性以实际回执为准，参数仍需审核，不提供实时报价'},
        {'id': 'constraint_check', 'status': 'available', 'detail': '需绑定审核参数；估算与核实事实分开'},
        {'id': 'host_validation', 'status': 'available', 'detail': '可信本地 Python 行为原型编译与单元测试'},
        {'id': 'armcc_build', 'status': 'configured_unverified' if compiler_present else 'needs_configuration', 'detail': '仅检测编译器文件存在；实际调用结果另行记录，当前仅支持已有 ARMCC 适配器'},
        {'id': 'keil_build', 'status': 'configured_unverified' if uvision.is_absolute() and uvision.is_file() else 'needs_configuration', 'detail': '读取可信本地 .uvprojx/.uvproj，构建独立副本，读取源码与哈希后修改再构建；不烧录'},
        {'id': 'autonomous_decision', 'status': 'configured_unverified' if model_ready else 'not_connected', 'detail': '配置并明确启用后可自动决策；配置存在不代表模型服务已联通'},
        {'id': 'shopping_quotes', 'status': 'deferred', 'detail': '尚未接入电商报价，不保证价格与库存'},
        {'id': 'hardware_execution', 'status': 'receive_only_available' if serial_ready else 'needs_configuration', 'detail': '支持设备枚举与用户授权后的只接收串口日志；不支持烧录、发送控制命令或自动判定实机通过'}]}
    if getattr(app,'online_mode',False):
        for item in report['items']:
            if item['id'] in ('host_validation','armcc_build','keil_build','hardware_execution','online_documents'):
                item.update(status='not_connected',detail='此在线部署未连接隔离执行器或使用者本机工具；可生成并下载未验证源码/文档，未执行此项')
    return report


def assess(project):
    a = project['artifacts']
    rows = []
    imported_keil = bool(a.get('keil_project'))
    engineering_draft=a.get('engineering_draft')
    draft_report=a.get('draft_verification',{})
    from .draft_verification import source_hash
    draft_current=bool(engineering_draft and draft_report.get('source_sha256')==source_hash(engineering_draft.get('firmware',{}).get('files',{})))

    def add(key, title, status, why, next_step, required=False):
        rows.append({'id': key, 'title': title, 'status': status, 'reason': why,
                     'next_step': next_step, 'required_for_current_scope': required})

    confirmed = a.get('requirements', {}).get('status') == 'confirmed'
    selected = bool(a.get('selected_plan'))
    add('requirements', '需求确认', 'passed' if confirmed else 'pending',
        '按已保存需求状态判断；导入现有工程的构建范围不要求重做需求', '补齐需求并由用户确认' if not confirmed else '需求变化后重新分析', not imported_keil)
    add('design', '方案确定', 'passed' if selected else 'pending',
        '存在已选方案' if selected else '尚未记录已选方案', '比较候选并记录选择依据', not imported_keil)
    if imported_keil:
        add('keil_build', '已导入 Keil 工程构建', a.get('keil_build', {}).get('status', 'not_run'),
            '只针对已选 Target 与导入副本，不代表实机运行', '按错误位置读取源码、修改并重新构建', True)
    selection = a.get('selection_check', {}).get('status', 'not_run')
    module_files=a.get('mcu_implementation',{}).get('files',{})
    if any(n.startswith('test_') and n.endswith('.c') for n in module_files):
        tests=a.get('mcu_behavior_tests',{})
        fresh=tests.get('source_sha256')==source_hash(module_files)
        add('mcu_test','C模块行为测试',tests.get('status','not_run') if fresh else 'not_run',
            '按当前源码绑定的实际主机断言与目标编译结果判断，不代表硬件', '执行mcu_test逐个运行测试入口',True)
    add('constraints', '器件约束检查', selection, '只反映已提交检查，不代表完整电路正确', '检索原文、审核参数并补齐约束检查')
    for key, title in [('build', '主机编译'), ('verification', '主机测试'), ('mcu_build', 'MCU 目标文件编译'), ('firmware_build', '演练固件构建')]:
        action = {'build': 'host_prototype', 'verification': 'host_prototype', 'mcu_build': 'mcu_compile', 'firmware_build': 'firmware_build'}[key]
        required = not imported_keil and not engineering_draft and action in a.get('decision', {}).get('actions', [])
        status = a.get(key, {}).get('status', 'not_run')
        add(key, title, status, '以保存的实际工具结果为准；固件构建不代表可在任意板卡运行',
            '根据执行结果构建、测试或修复' if required else '当前交付范围未要求该能力', required)
    if engineering_draft:
        if a.get('draft_test_suite'):
            from .test_suites import current
            suite_ok=current(draft_report,engineering_draft.get('firmware',{}).get('files',{}),a['draft_test_suite'])
            add('draft_supplemental','冻结扩展边界测试','passed' if suite_ok else 'not_run' if not draft_current else draft_report.get('supplemental_tests',{}).get('status','not_run'),
                '必须同时绑定当前源码和冻结测试集哈希','在工作台执行原测试及扩展测试；失败让智能体修复',True)
        for stage,title in [('interfaces','接口与引脚草案'),('circuit','连接图草案'),('firmware','C源码草案')]:
            present=bool(engineering_draft.get(stage,{}).get('files'))
            add('draft_'+stage,title,'passed' if present else 'not_run','只确认文件已保存，不代表电气、引脚或程序行为已验证','补齐对应草案文件',True)
        for key,title in [('mcu_compile','草案MCU目标编译'),('host_tests','草案C主机行为测试')]:
            status=draft_report.get(key,{}).get('status','not_run') if draft_current else 'not_run'
            add('draft_'+key,title,status,'当前源码哈希绑定的实际工具结果；不包含实机验证' if draft_current else '尚无当前源码对应的验证结果，旧结果不能复用','智能体执行编译、测试，失败后按日志修复再验',True)
    estimates = a.get('power_estimates', {})
    add('power', '整机功耗', 'estimated' if estimates else 'not_run',
        '已有估算，仍需检查保守情景和峰值缺口' if estimates else '尚无整机功耗估算', '设计阶段估算，拿到硬件后测量')
    add('quotes', '采购报价', 'deferred', '电商接入暂缓，已有预算计算也不构成实时报价', '后续补采购渠道、规格、时间与运费')
    captures = a.get('hardware_captures', [])
    add('hardware', '开发板与实机验证', 'logs_collected_unverified' if any(c.get('status') == 'captured' for c in captures) else 'deferred',
        '已有串口原始日志，但未核对功能验收' if captures else '尚无串口采集；烧录与控制命令适配器未实现', '对照验收标准分析日志，后续补烧录与测量证据')
    blockers = [r['id'] for r in rows if r['required_for_current_scope'] and r['status'] != 'passed']
    preliminary = bool(a.get('preliminary_acceptance'))
    return {'schema_version': 1, 'project_revision': project['revision'],
            'scope': 'preliminary_design' if preliminary else 'offline_engineering',
            'offline_status': 'needs_work' if blockers else 'ready_for_scoped_delivery',
            'complete_agent': False, 'hardware_verified': False,
            'scope_blockers': blockers, 'checks': rows,
            'statement': '离线交付可继续；未覆盖项、估算、演练构建和实机验证分别记录。此报告不认证参数来源或整机性能。'}
