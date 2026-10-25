"""User-attached frozen boundary tests and source-bound delivery gate."""
import hashlib
import json
import re
from copy import deepcopy

def digest(cases):
    return hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def validate(suite):
    cases = suite.get('cases') if isinstance(suite, dict) else None
    if not isinstance(cases, dict) or not 1 <= len(cases) <= 16:
        raise ValueError('扩展用例需包含1至16项')
    if any(not re.fullmatch(r'[A-Za-z0-9_]{1,70}', name) or not isinstance(body, str) or not body.strip()
           for name, body in cases.items()):
        raise ValueError('扩展用例名称或内容无效')
    if len(json.dumps(cases).encode()) > 160_000 or suite.get('sha256') != digest(cases):
        raise ValueError('冻结扩展测试哈希不匹配或内容过大')
    return cases

def load_audit(root, project_id, suite_id):
    if not isinstance(suite_id, str) or not re.fullmatch(r'\d{8}-\d{6}', suite_id):
        raise ValueError('扩展测试集编号无效')
    folder = root / 'runtime/boundary-audit' / suite_id
    if not folder.resolve().is_relative_to((root / 'runtime/boundary-audit').resolve()):
        raise ValueError('扩展测试路径越界')
    audit = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    if audit.get('project_id') != project_id:
        raise ValueError('不能关联其他项目的扩展测试')
    cases = {}
    for row in audit['cases']:
        name = row['id']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,70}', name) or name in cases:
            raise ValueError('扩展用例编号无效或重复')
        path = folder / (name + '.c')
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError('扩展测试文件路径越界')
        body = path.read_text(encoding='utf-8')
        if hashlib.sha256(body.encode()).hexdigest() != row['test_sha256']:
            raise ValueError('已有扩展用例文件被改动，拒绝导入')
        cases[name] = body
    suite = {'id': suite_id, 'cases': cases, 'sha256': digest(cases), 'origin': 'user_attached_boundary_audit'}
    validate(suite)
    return suite

def available(root, project_id):
    rows = []; seen = set()
    for folder in sorted((root / 'runtime/boundary-audit').glob('*'), reverse=True):
        try:
            suite = load_audit(root, project_id, folder.name)
            if suite['sha256'] in seen: continue
            seen.add(suite['sha256'])
            rows.append({'id': suite['id'], 'count': len(suite['cases']), 'sha256': suite['sha256']})
        except (ValueError, OSError, KeyError, TypeError):
            continue
    return rows

def current(report, files, suite=None):
    from .draft_verification import source_hash
    if report.get('status') != 'passed' or report.get('source_sha256') != source_hash(files): return False
    if suite:
        validate(suite)
        extra = report.get('supplemental_tests', {})
        return extra.get('status') == 'passed' and extra.get('suite_sha256') == suite['sha256']
    return True

def verify_all(root, files, cpu, suite=None):
    from .draft_verification import verify
    from .supplemental_tests import combine
    report = verify(root, files, cpu)
    if not suite: return report
    cases = validate(suite)
    report['original_host_tests'] = deepcopy(report['host_tests'])
    # Avoid a second compile when the original suite already fails.
    if report['status'] != 'passed':
        report['supplemental_tests'] = {'status': 'not_run', 'suite_sha256': suite['sha256'],
                                         'reason': '先修复原测试或编译失败', 'case_count': len(cases)}
        return report
    extra = verify(root, combine(files, cases), cpu)
    extra.update(suite_sha256=suite['sha256'], case_count=len(cases))
    report['supplemental_tests'] = extra
    report['status'] = extra['status']
    if extra['status'] != 'passed':
        # Existing diagnostic readers must see the real active failure.
        report['host_tests'] = deepcopy(extra['host_tests'])
        report['active_failure_suite'] = 'supplemental'
    return report
