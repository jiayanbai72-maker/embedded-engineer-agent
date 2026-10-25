"""Scenario power budgets, explicitly distinct from measured hardware verification."""
import hashlib
import json
import math


def numeric(value,name):
    if value is None: return None
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise ValueError(name+'必须为有限非负数或null')
    return value


def text(value,name):
    if not isinstance(value,str) or not value.strip() or len(value)>6000: raise ValueError('需要'+name)


def evaluate_power(model):
    if not isinstance(model,dict): raise ValueError('需要整机功耗估算对象')
    for k in ('analyst','scope','schedule_basis'): text(model.get(k),k)
    if model.get('power_boundary')!='whole_load_bus': raise ValueError('需明确 whole_load_bus：各状态为稳压输出端全部负载，转换损耗另算')
    target=numeric(model.get('target_hours'),'目标时长')
    reserve=numeric(model.get('reserve_fraction'),'储备比例')
    if target is None or target<=0 or reserve is None or not 0<=reserve<1: raise ValueError('目标时长或储备比例不正确')
    battery=model.get('battery')
    if not isinstance(battery,dict): raise ValueError('需要电池估算')
    text(battery.get('basis'),'电池依据')
    states=model.get('states')
    if not isinstance(states,list) or not 1<=len(states)<=30: raise ValueError('需要1至30个互斥工作状态')
    names=set(); missing=[]
    for state in states:
        if not isinstance(state,dict): raise ValueError('状态格式不正确')
        text(state.get('name'),'状态名称'); text(state.get('basis'),'状态功率与工况依据')
        if state['name'] in names: raise ValueError('工作状态名称重复')
        names.add(state['name'])
        if state.get('source_type') not in ('assumption','datasheet_estimate','measurement_estimate'): raise ValueError('需注明状态数值来源类型；均作为设计估算')
        for field in ('duration_s','load_mw'):
            if not isinstance(state.get(field),dict): raise ValueError('每个状态需典型和保守情景')
    results={}
    for scenario in ('typical','conservative'):
        required={}
        def read(container,key,label):
            pair=container.get(key)
            if not isinstance(pair,dict): raise ValueError('缺少情景字段：'+key)
            value=numeric(pair.get(scenario),label)
            if value is None: missing.append(scenario+':'+label)
            return value
        voltage=read(battery,'voltage_v','电池电压')
        capacity=read(battery,'capacity_mah','电池容量')
        usable=read(battery,'usable_fraction','可用容量比例')
        efficiency=read(model,'conversion_efficiency','转换效率')
        overhead=read(model,'battery_overhead_mw','电池侧静态损耗')
        if voltage==0 or capacity==0: raise ValueError('电池电压和容量必须大于0')
        for value in (usable,efficiency):
            if value is not None and not 0<value<=1: raise ValueError('可用比例和转换效率必须在(0,1]')
        remaining=[]; rows=[]; total_seconds=0
        for state in states:
            duration=state['duration_s'].get(scenario)
            if duration=='remaining': remaining.append(len(rows)); seconds=None
            else:
                seconds=numeric(duration,'状态时长')
                if seconds is None: missing.append(scenario+':'+state['name']+'时长')
                else: total_seconds+=seconds
            load=read(state,'load_mw',state['name']+'负载功率')
            rows.append({'name':state['name'],'seconds':seconds,'load_mw':load,'basis':state['basis'],'source_type':state['source_type']})
        if len(remaining)>1: raise ValueError('每个情景最多一个 remaining 状态，不能重复计算时间')
        if total_seconds>target*3600+1e-6: raise ValueError('状态时长超过目标窗口；并行负载应合并在同一状态内')
        if remaining: rows[remaining[0]]['seconds']=target*3600-total_seconds
        elif not any(r['seconds'] is None for r in rows) and abs(total_seconds-target*3600)>1e-6:
            raise ValueError('状态时长必须覆盖整个目标窗口，或使用remaining填补')
        complete=all(v is not None for v in (voltage,capacity,usable,efficiency,overhead)) and all(r['seconds'] is not None and r['load_mw'] is not None for r in rows)
        result={'status':'insufficient_data','states':rows}
        if complete:
            available=voltage*capacity/1000*usable*(1-reserve)
            load_wh=sum(r['load_mw']*r['seconds']/3600000 for r in rows)
            required_wh=load_wh/efficiency+overhead/1000*target
            average=required_wh/target
            if not all(math.isfinite(v) for v in (available,required_wh,average)): raise ValueError('估算数值超出有效范围')
            result.update(status='estimated_meets' if required_wh<=available else 'estimated_shortfall',
                available_wh=round(available,6),required_wh=round(required_wh,6),margin_wh=round(available-required_wh,6),
                average_battery_mw=round(average*1000,6),estimated_hours=round(available/average,3) if average else None,
                runtime_note='按本窗口平均工况外推；实际事件频率变化时需重算' if average else '输入功率为零，不能据此给出有限续航，需复核假设')
        results[scenario]=result
    # Conservative means no lower load, no larger energy supply or conversion efficiency.
    for state in states:
        a,b=state['load_mw'].get('typical'),state['load_mw'].get('conservative')
        if a is not None and b is not None and b<a: raise ValueError('保守状态功率不能小于典型功率')
    for container,keys in ((battery,('voltage_v','capacity_mah','usable_fraction')),(model,('conversion_efficiency',))):
        for key in keys:
            pair=container[key]; a,b=pair.get('typical'),pair.get('conservative')
            if a is not None and b is not None and b>a: raise ValueError('保守电池能量或效率不能高于典型情景')
    overhead=model['battery_overhead_mw']
    if overhead.get('typical') is not None and overhead.get('conservative') is not None and overhead['conservative']<overhead['typical']:
        raise ValueError('保守静态损耗不能小于典型值')
    if results['typical'].get('required_wh') is not None and results['conservative'].get('required_wh') is not None and results['conservative']['required_wh']<results['typical']['required_wh']:
        raise ValueError('保守工况总耗能小于典型工况，请复核状态时长')
    peak=model.get('peak',{})
    if not isinstance(peak,dict): raise ValueError('峰值估算格式不正确')
    text(peak.get('basis'),'峰值估算依据与适用电压轨')
    load=numeric(peak.get('load_peak_ma'),'峰值负载电流'); supply=numeric(peak.get('supply_limit_ma'),'同电压轨供电能力')
    peak_result={'status':'unknown' if load is None or supply is None else 'estimated_meets' if supply>=load else 'estimated_shortfall',
        'load_peak_ma':load,'supply_limit_ma':supply,'basis':peak['basis'],
        'note':'只比较同一电压轨估算电流；未验证瞬态、压降、保护、电池放电能力或堵转持续时间'}
    overall='insufficient_data' if missing else results['conservative']['status']
    return {'status':overall,'scenarios':results,'peak':peak_result,'missing_inputs':missing,
        'target_hours':target,'budget_status':'deferred_pending_quotes','hardware':'not_run','evidence_level':'engineering_estimate',
        'model_sha256':hashlib.sha256(json.dumps(model,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        'limitations':['不是实测认证，资料引用不自动审核估算。','所有状态互斥；各状态功率包含该状态同时工作的全部负载。','容量折减用于温度、老化等可用容量假设；储备比例单独保留；效率只作用于负载能耗。','待核价不等于预算通过；峰值供电检查独立于平均续航。']}
