"""Two-pass requirement intake and conditional architecture comparison."""
from .domain import StageResult

REQUIREMENTS_PROMPT = '''你是通用嵌入式需求工程师。先提取需求，不预设芯片。
输出 JSON：requirements（非空列表，每项 id、description、acceptance、origin，其中 origin 为 explicit 或 proposed）、
constraints（每项 name、value、origin，其中 origin 为 explicit 或 proposed）、
assumptions（字符串列表）、questions（每项 id、question、blocking 布尔值）、
search_queries（1至8个简短关键词字符串）。
显式需求来自用户，新增指标标为 proposed 并说明假设；未知数值不得补成用户要求。
问题按对方案影响排序。search_queries 用于检索通用方法，包含如需求、功耗、接口、并发、测试等词。
不要输出 confirmed 或芯片定案。'''

COMPARISON_PROMPT = '''根据需求和已提供知识卡片比较至少两种不同的系统方案，不默认使用桌宠、ESP32、STM32或RTOS。
只输出 JSON：candidates（2至4项），每项包含 id、name、architecture、
covers（需求id列表）、tradeoffs（字符串列表）、conditions（字符串列表）、
risks（字符串列表）、evidence_ids（引用卡片id列表）、
chip_requirements（字符串列表）、chip_options（列表，每项 family、status、evidence_ids），
以及 recommendation（candidate_id 为候选id或 null、reason 字符串）。
至少一个 tradeoff、condition、risk、evidence_id、chip_requirement。
architecture 描述模块和数据流。列出满足约束的条件，未确认需求只能给条件式建议。
通用方法不证明芯片电气参数。仅在 device 层资料足够时标记 chip_options 的 status 为 verified；
其他芯片建议必须标记 unverified，缺乏资料时留空。推荐方案不是最终选型。'''


def text(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value, nonempty=False):
    return isinstance(value, list) and (bool(value) or not nonempty) and all(text(x) for x in value)


def validate_budget_scope(requirements,description):
    """Reject invented explicit cost exclusions; never silently expand scope."""
    import re
    for kind,rows in [('requirements',requirements.get('requirements',[])),('constraints',requirements.get('constraints',[]))]:
        for i,row in enumerate(rows):
            body=' '.join(str(row.get(k,'')) for k in ('description','acceptance','name','value'))
            if row.get('origin')!='explicit' or not any(word in body for word in ('预算','成本','物料','材料','费用')):continue
            qualifiers=re.findall(r'(?:不含|不包括|不计入|仅计|只计)[^，。；）)\n]{1,40}|核心器件',body)
            if any(q.strip() not in description for q in qualifiers):
                raise ValueError(kind+'['+str(i)+']: 预算统计范围新增排除项或缩小范围，不能标explicit；保留用户原范围，未明确项标待确认建议')


def validate_requirements(result):
    if not isinstance(result, dict):
        raise ValueError('需求结果必须为对象')
    reqs = result.get('requirements')
    if not isinstance(reqs, list) or not reqs:
        raise ValueError('需要至少一项需求')
    ids = set()
    for req in reqs:
        if not isinstance(req, dict) or any(not text(req.get(k)) for k in ('id', 'description', 'acceptance')) or req.get('origin') not in ('explicit', 'proposed'):
            raise ValueError('需求缺少编号、描述、验收或来源')
        if req['id'] in ids:
            raise ValueError('需求编号重复')
        ids.add(req['id'])
    if not isinstance(result.get('constraints'), list):
        raise ValueError('约束必须为列表')
    for constraint in result['constraints']:
        if not isinstance(constraint, dict) or not text(constraint.get('name')) or not text(constraint.get('value')) or constraint.get('origin') not in ('explicit', 'proposed'):
            raise ValueError('约束格式不正确')
    if not strings(result.get('assumptions')) or not isinstance(result.get('questions'), list):
        raise ValueError('假设或问题格式不正确')
    question_ids = set()
    for question in result['questions']:
        if not isinstance(question, dict) or not text(question.get('id')) or not text(question.get('question')) or type(question.get('blocking')) is not bool or question['id'] in question_ids:
            raise ValueError('问题格式不正确或编号重复')
        question_ids.add(question['id'])
    if not strings(result.get('search_queries'), True) or len(result['search_queries']) > 8 or any(len(q) > 80 for q in result['search_queries']):
        raise ValueError('检索关键词格式不正确')
    return {k: result[k] for k in ('requirements', 'constraints', 'assumptions', 'questions', 'search_queries')}


def validate_comparison(result, requirements, evidence):
    candidates = result.get('candidates') if isinstance(result, dict) else None
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 4:
        raise ValueError('需要两到四个候选方案')
    known_reqs = {r['id'] for r in requirements['requirements']}
    known_evidence = {e['id']: e for e in evidence}
    ids = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or any(not text(candidate.get(k)) for k in ('id', 'name', 'architecture')):
            raise ValueError('方案描述不完整')
        if candidate['id'] in ids:
            raise ValueError('方案编号重复')
        ids.add(candidate['id'])
        for key in ('covers', 'tradeoffs', 'conditions', 'risks', 'evidence_ids', 'chip_requirements'):
            if not strings(candidate.get(key), True):
                raise ValueError('方案列表字段不完整')
        if not set(candidate['covers']).issubset(known_reqs):
            raise ValueError('candidate.covers引用不存在的需求；有效编号：'+','.join(sorted(known_reqs)))
        if not set(candidate['evidence_ids']).issubset(known_evidence):
            raise ValueError('candidate.evidence_ids引用不存在的证据；有效编号：'+','.join(sorted(known_evidence)))
        options = candidate.get('chip_options')
        if not isinstance(options, list):
            raise ValueError('芯片建议必须为列表')
        for option in options:
            if not isinstance(option, dict) or not text(option.get('family')) or option.get('status') not in ('unverified', 'verified') or not strings(option.get('evidence_ids')):
                raise ValueError('芯片建议格式不正确')
            if not set(option['evidence_ids']).issubset(known_evidence):
                raise ValueError('芯片引用不存在的证据')
            # General or ecosystem references cannot validate a specific chip.
            if option['status'] == 'verified' and (not option['evidence_ids'] or any(known_evidence[i]['scope'] != 'device' for i in option['evidence_ids'])):
                raise ValueError('芯片验证缺少专属证据')
    recommendation = result.get('recommendation')
    if not isinstance(recommendation, dict) or recommendation.get('candidate_id') not in ids | {None} or not text(recommendation.get('reason')):
        raise ValueError('推荐格式不正确')
    return {'candidates': candidates, 'recommendation': recommendation, 'status': 'conditional', 'chip_selection': 'not_finalized'}


class IntakeAgent:
    def run(self, project, services):
        if services.model is None:
            return StageResult('unsupported', message='模型未配置；原始语言需求已保存，未执行分析。')
        seed = services.knowledge.search('需求', scope='general')[:3]
        requirements = validate_requirements(services.model.generate(
            role='requirements', instruction=REQUIREMENTS_PROMPT,
            context={'description': project.description, 'references': seed}))
        artifact = dict(requirements, status='draft', evidence=[], comparison_status='pending')
        references = {r['id']: r for r in seed}
        for query in requirements['search_queries']:
            for card in services.knowledge.search(query, scope='general')[:3]:
                references[card['id']] = card
        evidence = list(references.values())[:12]
        artifact['evidence'] = evidence
        artifact['evidence_ids'] = [c['id'] for c in evidence]
        try:
            comparison = services.model.generate(role='comparison', instruction=COMPARISON_PROMPT,
                                                context={'description': project.description, 'requirements': requirements,
                                                         'references': evidence, 'tool_capabilities': services.tools.capabilities()})
            artifact['comparison'] = validate_comparison(comparison, requirements, evidence)
            from .analysis_quality import validate as validate_analysis_quality
            artifact['analysis_quality'] = validate_analysis_quality(project.description, requirements, artifact['comparison'])
            artifact['comparison_status'] = 'completed'
        except Exception:
            artifact['comparison_status'] = 'failed'
            artifact['comparison_error'] = '候选方案比较失败或未通过契约校验；已保留需求草稿。'
        message = ('需求草稿与候选方案已保存；需补充或确认，芯片尚未定案。'
                   if artifact['comparison_status'] == 'completed'
                   else '需求草稿已保存，但候选方案比较失败；芯片尚未定案。')
        return StageResult('needs_input', artifact, message)
