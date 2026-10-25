"""Deterministic constraint calculations. Evidence review remains an explicit external responsibility."""
import math


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def evaluate_selection(proposal, resolver=None):
    if not isinstance(proposal, dict) or not isinstance(proposal.get('checks'), list) or not proposal['checks']:
        raise ValueError('需要非空检查列表')
    evidence = proposal.get('evidence', [])
    if not isinstance(evidence, list):
        raise ValueError('证据必须为列表')
    records = {}
    for record in evidence:
        if not isinstance(record, dict) or not isinstance(record.get('id'), str) or record['id'] in records:
            raise ValueError('证据编号无效或重复')
        records[record['id']] = record
    results, ids = [], set()
    for check in proposal['checks']:
        if not isinstance(check, dict) or not isinstance(check.get('id'), str) or check['id'] in ids:
            raise ValueError('检查编号无效或重复')
        ids.add(check['id'])
        kind = check.get('kind')
        inputs = check.get('inputs')
        refs = check.get('evidence_ids', [])
        if not isinstance(inputs, dict) or not isinstance(refs, list) or any(not isinstance(i, str) or i not in records for i in refs):
            raise ValueError('输入或证据引用不正确')
        missing, detail, outcome = [], {}, 'unknown'
        def get(name):
            value = inputs.get(name)
            if value is None:
                missing.append(name)
                return None
            if not number(value):
                raise ValueError('数值参数必须是有限非负数')
            return value
        if kind == 'budget':
            limit, shipping = get('limit_cny'), get('shipping_cny')
            parts = inputs.get('parts')
            if not isinstance(parts, list) or not parts:
                raise ValueError('预算需要完整材料列表')
            total = shipping or 0
            for part in parts:
                if not isinstance(part, dict) or not isinstance(part.get('model'), str) or type(part.get('quantity')) is not int or part['quantity'] <= 0:
                    raise ValueError('BOM型号或数量不正确')
                price = part.get('unit_price_cny')
                if price is None:
                    missing.append('price:' + part['model'])
                elif not number(price):
                    raise ValueError('价格不正确')
                else:
                    total += price * part['quantity']
            if inputs.get('coverage_complete') is not True:
                missing.append('完整采购范围确认')
            detail = {'known_total_cny': round(total, 4), 'limit_cny': limit}
            if not missing: outcome = 'passed' if total <= limit else 'failed'
        elif kind == 'energy':
            names = ('battery_v', 'capacity_mah', 'usable_fraction', 'reserve_fraction', 'hours', 'idle_mw', 'active_mw', 'active_seconds')
            values = {n: get(n) for n in names}
            if not missing:
                v = values
                if not 0 < v['usable_fraction'] <= 1 or not 0 <= v['reserve_fraction'] < 1 or not v['hours'] > 0 or v['active_seconds'] > v['hours']*3600:
                    raise ValueError('能耗比例或工况不正确')
                available = v['battery_v'] * v['capacity_mah'] / 1000 * v['usable_fraction'] * (1-v['reserve_fraction'])
                active_hours = v['active_seconds']/3600
                required = v['idle_mw']/1000 * (v['hours']-active_hours) + v['active_mw']/1000 * active_hours
                detail = {'available_wh': round(available, 6), 'required_wh': round(required, 6), 'margin_wh': round(available-required, 6)}
                outcome = 'passed' if required <= available else 'failed'
        elif kind == 'voltage':
            v = {n: get(n) for n in ('output_min_v', 'output_max_v', 'input_min_v', 'input_max_v')}
            if not missing:
                if v['output_min_v'] > v['output_max_v'] or v['input_min_v'] > v['input_max_v']:
                    raise ValueError('电压区间倒置')
                outcome = 'passed' if v['input_min_v'] <= v['output_min_v'] and v['output_max_v'] <= v['input_max_v'] else 'failed'
                detail = v
        elif kind == 'resource':
            available, required = get('available'), get('required')
            if not isinstance(inputs.get('resource'), str) or not inputs['resource']:
                raise ValueError('需要资源名称')
            if not missing:
                detail = {'resource': inputs['resource'], 'available': available, 'required': required}
                outcome = 'passed' if available >= required else 'failed'
        else:
            raise ValueError('未知约束类型')
        # A linked URL or model assertion alone is not reviewed engineering evidence.
        reviewed = bool(refs) and all(records[i].get('reviewed') is True and records[i].get('reviewer')
                                     and records[i].get('snapshot_sha256') and records[i].get('section')
                                     and records[i].get('scope_note') for i in refs)
        binding_errors, resolved = [], []
        if resolver is not None:
            # All hardware/quote facts must resolve to locally reviewed immutable records.
            # Other inputs (e.g. target hours, requested PWM count) remain explicit design conditions.
            fields = {'voltage':{'output_min_v':'V','output_max_v':'V','input_min_v':'V','input_max_v':'V'},
                      'resource':{'available':'count'},
                      'energy':{'battery_v':'V','capacity_mah':'mAh','usable_fraction':'fraction','idle_mw':'mW','active_mw':'mW'},
                      'budget':{'shipping_cny':'CNY'}}[kind]
            actual=dict(inputs)
            if kind=='budget':
                for n,part in enumerate(inputs['parts']):
                    path=f'parts.{n}.unit_price_cny'
                    fields[path]='CNY'; actual[path]=part.get('unit_price_cny')
            bindings=check.get('parameter_bindings',{})
            if not isinstance(bindings,dict): raise ValueError('parameter_bindings 必须为对象')
            for field,unit in fields.items():
                binding=bindings.get(field)
                try:
                    if not isinstance(binding,dict): raise ValueError('未绑定审核参数')
                    record=resolver(binding.get('parameter_id'))
                    if record.get('reviewed') is not True: raise ValueError('参数未审核')
                    expected_parameter=(inputs['resource']+'.available') if kind=='resource' else field.split('.')[-1]
                    if record['parameter']!=expected_parameter: raise ValueError('参数含义与输入字段不匹配')
                    if record['unit']!=unit: raise ValueError('单位不匹配，需显式换算并重新审核')
                    if actual.get(field)!=record['value']: raise ValueError('输入值与审核参数不一致')
                    if binding.get('model')!=record['model'] or binding.get('conditions')!=record['conditions']:
                        raise ValueError('型号或工况与审核记录不一致')
                    if kind=='budget' and field.startswith('parts.') and record['model']!=inputs['parts'][int(field.split('.')[1])]['model']:
                        raise ValueError('报价型号与BOM不一致')
                    resolved.append(dict(record,input_field=field))
                except (ValueError,FileNotFoundError,KeyError,TypeError) as exc:
                    binding_errors.append({'field':field,'reason':str(exc)[:180]})
            reviewed=not binding_errors and bool(resolved)
        status = 'needs_evidence' if missing or not reviewed else outcome
        results.append({'id': check['id'], 'kind': kind, 'status': status, 'calculation_status': outcome,
                        'missing_inputs': missing, 'evidence_reviewed': reviewed, 'evidence_ids': refs, 'detail': detail,
                        'binding_errors':binding_errors,'resolved_evidence':resolved})
    status = 'failed' if any(r['status']=='failed' for r in results) else 'needs_evidence' if any(r['status']=='needs_evidence' for r in results) else 'passed'
    return {'status': status, 'checks': results, 'coverage': proposal.get('coverage', []),
            'evidence_mode':'local_parameter_registry' if resolver else 'standalone_declarations_only',
            'limitations': ['只检查提交的约束，不证明未列出的约束满足。', '参数记录区分人工核对与Agent原文核对；Agent记录经过引用/数值/单位检查及模型语义核对，不等于专家或硬件认证。', '需求数量、目标时长、动作时长和储备比例仍为提交者提供的设计条件。', '能耗计算通过不等于48小时实机测试通过。'], 'hardware': 'not_run'}
