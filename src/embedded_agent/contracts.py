"""Discoverable action argument shapes; service validators remain authoritative."""
from copy import deepcopy


def obj(properties, required=None, **extra):
    return dict(type='object', properties=properties, required=list(properties) if required is None else required, **extra)


def arr(item, **extra): return dict(type='array', items=item, **extra)


S = {'type': 'string', 'minLength': 1}
STRINGS = arr(S)
ORIGIN = {'type': 'string', 'enum': ['explicit', 'proposed']}
FILES = {'type': 'object', 'minProperties': 1, 'additionalProperties': S, 'description': '文件名到源码字符串；主机仅单层 .py，MCU仅单层 .c/.h'}
REQ = obj({
    'requirements': arr(obj({'id': S, 'description': S, 'acceptance': S, 'origin': ORIGIN}), minItems=1),
    'constraints': arr(obj({'name': S, 'value': S, 'origin': ORIGIN})),
    'assumptions': STRINGS,
    'questions': arr(obj({'id': S, 'question': S, 'blocking': {'type': 'boolean'}})),
    'search_queries': arr(S, minItems=1, maxItems=8)})
CANDIDATE = obj({'id': S, 'name': S, 'architecture': S, 'covers': arr(S, minItems=1),
                 'tradeoffs': arr(S, minItems=1), 'conditions': arr(S, minItems=1),
                 'risks': arr(S, minItems=1), 'evidence_ids': arr(S, minItems=1),
                 'chip_requirements': arr(S, minItems=1),
                 'chip_options': arr(obj({'family': S, 'status': {'enum': ['unverified', 'verified']}, 'evidence_ids': STRINGS}))})
CONTRACTS = {
    'conclude_research':obj({'model':S,'package':S,'summary':S,'mappings':arr(obj({'pin':S,'af':S,'signal':S,'fact_id':S,'package_fact_id':{'type':['string','null']}}),maxItems=3),'voice_pins':arr(obj({'pin':S,'af':S,'signal':S,'fact_id':S,'package_fact_id':{'type':['string','null']}},['pin','af','signal','fact_id']),maxItems=4),'unresolved':STRINGS,'deferred':STRINGS},['model','package','summary','mappings','voice_pins','unresolved']),
    'draft_patch': obj({'file':S,'sha256':S,'replacements':arr(obj({'old':S,'new':{'type':'string'}}),minItems=1,maxItems=6),'rationale':S}),
    'draft_edit': obj({'changes':arr(obj({'file':S,'sha256':S,'content':S}),minItems=1,maxItems=3),'rationale':S}),
    'draft_verify': obj({'cpu':{'enum':['Cortex-M0','Cortex-M0plus','Cortex-M3','Cortex-M4']}}),
    'draft_artifacts': obj({'stage': {'enum':['interfaces','circuit','firmware'], 'description':'按顺序保存：interfaces含Markdown接口/引脚表，未知引脚TBD；circuit含connections.json，格式{connections:[{from,to,signal,status:proposed或unverified}]}，程序生成SVG连接草图（不是PCB图）；firmware含实际.c/.h及README，未知硬件用显式适配接口，不声称可烧录；每阶段只交本阶段文件'}, 'files': {'type':'object','minProperties':1,'additionalProperties':S}, 'rationale':S, 'assumptions':STRINGS, 'open_items':STRINGS}),
    'discover_hardware': obj({}),
    'hardware_capture': obj({'seconds': {'type': 'integer', 'minimum': 1, 'maximum': 10}}, []),
    'keil_build': obj({}),
    'read_keil_source': obj({'file': S}),
    'keil_edit': obj({'changes': arr(obj({'file': S, 'sha256': S, 'content': S}), minItems=1, maxItems=10), 'rationale': S}),
    'analysis': obj({'analyst': S, 'requirements': REQ,
        'comparison': obj({'candidates': arr(CANDIDATE, minItems=2, maxItems=4),
                           'recommendation': obj({'candidate_id': {'type': ['string', 'null']}, 'reason': S})}),
        'decision': obj({'actions': {'enum': [['export_documents'], ['host_prototype', 'export_documents'], ['mcu_compile', 'export_documents'], ['firmware_build', 'export_documents']]},
                         'rationale': S, 'limitations': arr(S, minItems=1)})}),
    'implementation': obj({'files': FILES, 'rationale': S}),
    'mcu_implementation': obj({'files': FILES, 'cpu': {'enum': ['Cortex-M0', 'Cortex-M0plus', 'Cortex-M3', 'Cortex-M4']}, 'rationale': S}),
    'firmware_implementation': obj({'files': FILES, 'rationale': S, 'profile': obj({
        'cpu': {'enum': ['Cortex-M3']}, 'mode': {'enum': ['demonstration_only']},
        **{k: {'type': 'integer', 'minimum': 0, 'multipleOf': 8} for k in ('flash_base', 'flash_size', 'ram_base', 'ram_size', 'stack_size')}})}),
    'search_documents': obj({'query': S, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}, 'document_id': S}, ['query']),
    'research_documents': obj({'query':{'type':'string','minLength':1,'maxLength':200},'missing_field':{'type':'string','minLength':1,'maxLength':100}},['query']),
    'fetch_document': obj({'url':{'type':'string','minLength':1,'maxLength':3000}}),
    'record_parameter': obj({'document_id':S,'page':{'type':['integer','null'],'minimum':1},'model':S,'parameter':S,
        'value':{'type':'number'},'unit':S,'conditions':S,'quote':{'type':'string','minLength':8,'maxLength':4000},'quote_id':S,'rationale':S},['document_id','page','model','parameter','value','unit','conditions','rationale']),
    'read_document_page': obj({'document_id': S, 'page': {'type': ['integer','null'], 'minimum': 1},'source_view':{'enum':['text','layout']}},['document_id']),
    'read_parameter': obj({'id': S}),
    'record_fact': obj({'document_id':S,'page':{'type':['integer','null'],'minimum':1},'quote_id':S,'model':S,'subject':S,'predicate':S,'object':S,'conditions':S,'rationale':S,'source_view':{'enum':['text','layout']}},['document_id','page','quote_id','model','subject','predicate','object','conditions','rationale']),
    'ask': obj({'question': S}),
    'design_research': obj({'task_id': S}),
    'design_recommend': obj({'candidate_id': S, 'rationale': S, 'observation_ids': arr(S, minItems=1)}),
    'selection_check': obj({'proposal': obj({'checks': arr(obj({'id': S, 'kind': {'enum': ['budget', 'energy', 'voltage', 'resource']},
              'inputs': {'type': 'object'}, 'parameter_bindings': {'type': 'object'}}, ['id', 'kind', 'inputs']), minItems=1)})}),
    'power_estimate': obj({'candidate_id': S, 'model': {'type': 'object', 'description': '完整字段见 engineering_guides.power；不是单个芯片典型电流'}}),
    'design_plan': obj({'plan': {'type': 'object', 'description': '完整字段见 design_contract 与 engineering_guides.design'}}),
}
CHECK = obj({'id': S, 'objective_id': S, 'kind': {'enum': ['budget', 'energy', 'voltage', 'resource']},
             'inputs': {'type': 'object'}, 'parameter_bindings': {'type': 'object'}}, ['id', 'objective_id', 'kind', 'inputs'])
NUMBER = {'type': ['number', 'null'], 'minimum': 0}
PAIR = obj({'typical': NUMBER, 'conservative': NUMBER})
DURATION = obj({'typical': {'type': ['number', 'string', 'null'], 'description': '秒数、null或remaining'},
                'conservative': {'type': ['number', 'string', 'null'], 'description': '秒数、null或remaining'}})
CONTRACTS['power_estimate'] = obj({'candidate_id': S, 'model': obj({
    'analyst': S, 'scope': S, 'schedule_basis': S, 'power_boundary': {'enum': ['whole_load_bus']},
    'target_hours': {'type': 'number', 'minimum': 0}, 'reserve_fraction': {'type': 'number', 'minimum': 0, 'maximum': .999999},
    'battery': obj({'voltage_v': PAIR, 'capacity_mah': PAIR, 'usable_fraction': PAIR, 'basis': S}),
    'conversion_efficiency': PAIR, 'battery_overhead_mw': PAIR,
    'states': arr(obj({'name': S, 'duration_s': DURATION, 'load_mw': PAIR,
                       'source_type': {'enum': ['assumption', 'datasheet_estimate', 'measurement_estimate']},
                       'basis': S}), minItems=1, maxItems=30),
    'peak': obj({'load_peak_ma': NUMBER, 'supply_limit_ma': NUMBER, 'basis': S}),
})})
CONTRACTS['design_plan'] = obj({'plan': obj({
    'analyst': S, 'scope': S, 'rationale': S,
    'objectives': arr(obj({'id': S, 'description': S, 'kind': {'enum': ['budget', 'energy', 'voltage', 'resource']},
                           'requirement_ids': arr(S, minItems=1),
                           'fixed_inputs': {'type': 'object', 'description': 'budget含limit_cny；energy含hours；resource含required/resource。后续轮次必须与上一轮objectives完全相同。'}}), minItems=1, maxItems=12),
    'candidates': arr(obj({'id': S, 'name': S, 'architecture': S, 'covers': arr(S, minItems=1),
                          'tradeoffs': arr(S, minItems=1), 'risks': arr(S, minItems=1), 'assumptions': arr(S, minItems=1),
                          'components': arr(obj({'role': S, 'model': {'type': ['string', 'null']}}, ['role']), minItems=1),
                          'proposal': obj({'checks': arr(CHECK, minItems=1, maxItems=24)})}), minItems=2, maxItems=6),
    'tasks': arr(obj({'id': S, 'question': S, 'query': dict(S, maxLength=300), 'why': S,
                     'candidate_ids': arr(S, minItems=1)}), minItems=1, maxItems=12),
    'response_to': arr(S, minItems=1, description='已有方案调整时必填，引用本轮研究/检查的observation_id，不是决策回执ID'),
    'changes': arr(obj({'candidate_id': S, 'reason': S, 'observation_ids': arr(S, minItems=1)}), minItems=1),
}, ['analyst', 'scope', 'rationale', 'objectives', 'candidates', 'tasks'])})
for name in ('build', 'test', 'mcu_build', 'mcu_test', 'firmware_build', 'design_evaluate', 'execute', 'finish'):
    CONTRACTS[name] = obj({})


def describe(actions):
    return {name: {'arguments_schema': deepcopy(CONTRACTS[name]),
                   'validation': 'shape_and_service_semantics',
                   'authority': '仅当前允许的动作；用户确认不会自动授权'}
            for name in actions if name in CONTRACTS}


PLAN_SCHEMA = obj({'goal': S, 'rationale': S, 'source': S,
    'tasks': arr(obj({'id': S, 'title': S, 'action': S, 'depends_on': arr(S),
                      'completion': obj({'status': {'enum': ['executed']}}, additionalProperties={'type':['string','number','boolean','null']})}), minItems=1, maxItems=40),
    'response_to': arr(S, minItems=1)}, ['goal','rationale','source','tasks'])


def validate_shape(schema, value, path='arguments'):
    types = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list),
             'number': lambda x: type(x) in (int, float),
             'string': lambda x: isinstance(x, str), 'integer': lambda x: type(x) is int,
             'boolean': lambda x: type(x) is bool, 'null': lambda x: x is None}
    wanted = schema.get('type')
    if wanted and not any(types[t](value) for t in (wanted if isinstance(wanted, list) else [wanted])):
        raise ValueError(path + ': 字段类型不正确')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ': 值不在允许范围')
    if isinstance(value, dict):
        if len(value) < schema.get('minProperties', 0): raise ValueError(path + ': 对象不能为空')
        for key in schema.get('required', []):
            if key not in value: raise ValueError(path + '.' + key + ': 缺少必填字段')
        for key, item in value.items():
            child = schema.get('properties', {}).get(key, schema.get('additionalProperties'))
            if isinstance(child, dict): validate_shape(child, item, path + '.' + key)
    if isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 100000):
            raise ValueError(path + ': 列表长度不正确')
        if 'items' in schema:
            for index, item in enumerate(value): validate_shape(schema['items'], item, path + '[' + str(index) + ']')
    if isinstance(value, str) and len(value.strip()) < schema.get('minLength', 0): raise ValueError(path + ': 内容不能为空')
    if isinstance(value, str) and len(value) > schema.get('maxLength', len(value)): raise ValueError(path + ': 内容超出长度限制')
    if type(value) in (int, float):
        if value < schema.get('minimum', value) or value > schema.get('maximum', value): raise ValueError(path + ': 数值超出范围')
        if 'multipleOf' in schema and value % schema['multipleOf']: raise ValueError(path + ': 数值未对齐')
