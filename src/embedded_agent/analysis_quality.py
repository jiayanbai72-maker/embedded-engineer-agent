"""Bounded deterministic checks, not a general natural-language proof engine.

Only unambiguous supported source patterns become machine-checked references.
Unknown quantities remain unknown. Model prose is never executable code.
"""
from decimal import Decimal, InvalidOperation
import re

UNITS = {
    'B': (1, (1, 0, 0)), 'kB': (1000, (1, 0, 0)),
    'MB': (10**6, (1, 0, 0)), 'GB': (10**9, (1, 0, 0)),
    'MiB': (2**20, (1, 0, 0)), 'GiB': (2**30, (1, 0, 0)),
    'bit': (Decimal('0.125'), (1, 0, 0)),
    's': (1, (0, 1, 0)), 'ms': (Decimal('.001'), (0, 1, 0)),
    'h': (3600, (0, 1, 0)), 'day': (86400, (0, 1, 0)),
    'B/s': (1, (1, -1, 0)), 'kB/s': (1000, (1, -1, 0)),
    'MB/s': (10**6, (1, -1, 0)),
    'mAh': (Decimal('3.6'), (0, 1, 1)),
    'mA': (Decimal('.001'), (0, 0, 1)),
    'count': (1, (0, 0, 0)),
}


def number(value):
    if isinstance(value, bool):
        raise ValueError('计算值不能是布尔值')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('计算值必须是有限数字') from exc
    if not result.is_finite() or abs(result) > Decimal('1e30'):
        raise ValueError('计算值必须有限且不超过1e30')
    return result


def calculate(terms, output_unit):
    """Multiply/divide dimensioned quantities; no expressions or eval."""
    if not isinstance(terms, list) or not 1 <= len(terms) <= 12:
        raise ValueError('计算需要1至12项')
    value, dimension = Decimal(1), [0, 0, 0]
    for term in terms:
        if term.get('unit') not in UNITS or term.get('op', 'multiply') not in ('multiply', 'divide'):
            raise ValueError('不支持的单位或运算')
        scale, powers = UNITS[term['unit']]
        operand = number(term['value']) * Decimal(scale)
        sign = -1 if term.get('op') == 'divide' else 1
        if sign == -1 and operand == 0:
            raise ValueError('不能除以零')
        value = value * operand if sign == 1 else value / operand
        dimension = [a + sign*b for a, b in zip(dimension, powers)]
        if abs(value) > Decimal('1e60'):
            raise ValueError('计算结果超出范围')
    if output_unit not in UNITS or tuple(dimension) != UNITS[output_unit][1]:
        raise ValueError('结果量纲与输出单位不符')
    return float(value / Decimal(UNITS[output_unit][0]))


def reference(description):
    """Supported intake: channels, per-channel rate, bit width, duration/storage.

    Require one unique value per field; ambiguous/changed input is not guessed.
    """
    patterns = {
        'channels': r'(\d+)\s*通道',
        'rate': r'(?:每通道每秒|每通道采样率)\s*(\d+)\s*(?:样本|SPS)',
        'bits': r'每样本\s*(\d+)\s*位',
        'days': r'连续保存\s*(\d+)\s*天',
        'storage': r'(?:仅|只有)\s*(\d+)\s*(MiB|MB)\s*存储',
    }
    values, quotes = {}, []
    for key, pattern in patterns.items():
        matches = list(re.finditer(pattern, description))
        unique = {m.groups() for m in matches}
        if len(unique) != 1:
            return {'status': 'not_applicable', 'scope': 'unsupported_or_ambiguous_source_pattern', 'checks': []}
        match = matches[0]
        values[key] = match.groups()
        quotes.append(match.group(0))
    channels, rate, bits, days = [int(values[k][0]) for k in ('channels', 'rate', 'bits', 'days')]
    if not all(0 < v <= 10**9 for v in (channels, rate, bits, days)):
        return {'status': 'not_applicable', 'scope': 'invalid_source_quantity', 'checks': []}
    data_rate = calculate([{'value': channels, 'unit': 'count'}, {'value': rate, 'unit': 'count'}, {'value': bits, 'unit': 'bit'}, {'value': 1, 'unit': 's', 'op': 'divide'}], 'B/s')
    capacity = calculate([{'value': data_rate, 'unit': 'B/s'}, {'value': days, 'unit': 'day'}], 'B')
    storage = calculate([{'value': values['storage'][0], 'unit': values['storage'][1]}], 'B')
    seconds = calculate([{'value': days, 'unit': 'day'}], 's')
    return {'status': 'computed', 'source_quotes': quotes,
            'channels': channels, 'rate_per_channel': rate, 'bits_per_sample': bits,
            'data_rate_B_s': data_rate, 'capacity_B': capacity,
            'capacity_GB': capacity/10**9, 'capacity_GiB': capacity/2**30,
            'storage_B': storage, 'duration_s': seconds,
            'allowed_B_s': storage/seconds, 'storage_seconds': storage/data_rate,
            'capacity_ratio': capacity/storage if storage else None,
            'storage_conflict': capacity > storage,
            'scope': 'raw_samples_only_excludes_headers_and_metadata; no power_or_price_claims'}


def leaves(value, path='analysis'):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, path+'.'+str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from leaves(item, path+'['+str(i)+']')


def validate(description, requirements, comparison):
    """Reject high-confidence mismatches with explicit field-level feedback.

    Passing these checks does NOT certify every natural-language constraint.
    """
    ref = reference(description)
    errors = []
    for path, body in leaves({'requirements': requirements, 'comparison': comparison}):
        if ref['status'] == 'computed':
            # Unit-conversion claims about the computed total; exclude unrelated
            # candidates such as a proposed 512GB card by requiring a label.
            for m in re.finditer(r'(?:约|≈|折合|计约)\s*([\d,.]+)\s*(GiB|GB)', body):
                actual = float(m[1].replace(',', ''))
                expected = ref['capacity_GiB' if m[2] == 'GiB' else 'capacity_GB']
                # Only total-capacity discussions, not a different sensor option.
                alternative_channels = any(int(n) != ref['channels'] for n in re.findall(r'(\d+)\s*通道', body))
                labels = (str(int(ref['duration_s']/86400))+'天', '原始容量', '所需', '需求', '按MiB', '按GiB')
                if not alternative_channels and any(x in body for x in labels) and abs(actual-expected) > max(.01, expected*.005):
                    errors.append(f'{path}: 容量换算{actual}{m[2]}不符；按用户原始数据计算应为{expected:.6g}{m[2]}，不得改原指标')
            for m in re.finditer(r'(?:可持续数据率(?:上限)?|等效平均)[^。；\n]{0,70}?(?:≈|约|≤|=)\s*([\d.]+)\s*(kB/s|B/s)', body):
                actual = float(m[1]) * (1000 if m[2] == 'kB/s' else 1)
                if abs(actual-ref['allowed_B_s']) > max(.01, ref['allowed_B_s']*.005):
                    errors.append(f'{path}: 可持续数据率计算错误，应为可用字节/总秒数={ref["allowed_B_s"]:.6g} B/s')
        source_timeout = re.search(r'超过\s*(\d+)\s*秒无新数据', description)
        if source_timeout and any(x in body for x in ('超时', '无数据计数', '判定')):
            for m in re.finditer(r'(?:无数据计数|超时(?:时间|余量|阈值)?(?:为|取|设为)?)[^。；\n]{0,12}?(\d+(?:\.\d+)?)\s*(?:s|秒)', body):
                if float(m[1]) > float(source_timeout[1]):
                    errors.append(f'{path}: 超时建议{m[1]}秒放宽了原要求{source_timeout[1]}秒；不得作为实施条件')
        if re.search(r'两次.{0,8}至少间隔\s*\d+秒', description) and re.search(r'相邻两次启动间隔|启动到启动', body):
            errors.append(f'{path}: 停止后间隔不能改成启动到启动；请保留起算点或明确提出歧义')
        if re.search(r'(?:只能一个阀开启|最多.{0,5}一个.{0,4}阀)', description) and re.search(r'三路同时为开.{0,8}(?:为0|为零)', body):
            errors.append(f'{path}: 排除三个阀全开不能证明单阀互斥；验收必须检查任意时刻开启数量<=1')
    if '同步' not in description:
        for i, req in enumerate(requirements.get('requirements', [])):
            if req.get('origin') == 'explicit' and re.search(r'同步采样|同步采集|同步振动采集|通道间同步偏差|同一时基对齐', req.get('description', '')+' '+req.get('acceptance', '')):
                errors.append(f'analysis.requirements.requirements[{i}]: 用户未要求同步采样；同步指标应单独标proposed，不能混入explicit验收')
    if re.search(r'重放.{0,8}(?:不能续命|不.{0,3}刷新)', description):
        for i, q in enumerate(requirements.get('questions', [])):
            if q.get('blocking') and re.search(r'还是.{0,35}(?:任何|重放|重复)', q['question']) and any(x in q['question'] for x in ('时刻', '刷新', '起算')):
                errors.append(f'analysis.requirements.questions[{i}]: 用户已明确重放不续命，不应再次阻塞询问是否由重放帧刷新超时')
            elif q.get('blocking') and re.search(r'是否从.{0,35}新序号.{0,20}(?:起算|计时)', q['question']):
                errors.append(f'analysis.requirements.questions[{i}]: 用户已明确有效新序号超时和重放不续命，不能再次阻塞确认已给定的计时起点')
    if errors:
        raise ValueError('独立分析检查未通过：'+'；'.join(errors[:6]))
    return {'status': 'passed_supported_checks', 'numeric_reference': ref,
            'semantic_coverage': 'bounded_patterns_only; other constraints still require review',
            'hardware': 'not_run'}
