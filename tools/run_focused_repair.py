"""Configured model repairs production files; controller validates every edit."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4
from embedded_agent.local_model import LocalSettings, BudgetPaused

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-paid', action='store_true')
    parser.add_argument('--project', required=True)
    parser.add_argument('--attempts', type=int, default=12)
    parser.add_argument('--boundary-dir', type=Path)
    args = parser.parse_args()
    if not args.run_paid:
        raise SystemExit('Explicit paid execution flag required')
    root = Path(__file__).resolve().parents[1]
    settings = LocalSettings(root)
    before = settings.budget.status()
    if before['paused']:
        raise SystemExit('Daily budget paused; unchanged')
    model = settings.model()
    if model is None:
        raise SystemExit('No enabled model')
    folder = root / 'runtime/focused-repair' / datetime.now().strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    def save(name, data):
        (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    def api(path, data=None):
        req = Request('http://127.0.0.1:8765' + path,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=180) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ValueError(exc.read().decode('utf-8')) from None
    run = None
    def action(name, arguments, reason):
        nonlocal run
        if run is None or run['repairs'] >= run['max_repairs'] or run['steps'] >= run['max_steps']:
            run = api('/runs', {'project_id': args.project, 'max_steps': 20, 'max_repairs': 3})
        run = api('/runs/' + run['id'])['run']
        decision = {'id': str(uuid4()), 'project_revision': run['project_revision'], 'action': name, 'arguments': arguments,
                    'rationale': reason, 'expected': 'Preserve original tests and verify actual result',
                    'source': 'configured_model_focused_repair'}
        api('/runs/' + run['id'] + '/decisions', {'revision': run['revision'], 'decision': decision})
        run = api('/runs/' + run['id'] + '/tick', {})
        receipt = run['observations'][-1]
        if receipt['status'] not in ('executed', 'finished'):
            raise ValueError(receipt.get('message') or json.dumps(receipt.get('tool_result'), ensure_ascii=False))
    project = api('/projects/' + args.project)
    save('initial.json', project)
    boundary_cases = {}
    boundary_report = None
    if args.boundary_dir:
        audit = json.loads((args.boundary_dir / 'report.json').read_text(encoding='utf-8'))
        if audit['project_id'] != args.project:
            raise ValueError('Boundary tests belong to a different project')
        for row in audit['cases']:
            content = (args.boundary_dir / (row['id'] + '.c')).read_text(encoding='utf-8')
            if hashlib.sha256(content.encode()).hexdigest() != row['test_sha256']:
                raise ValueError('Frozen boundary test hash changed')
            boundary_cases[row['id']] = content
        if project['status'] == 'documents_delivered':
            project = api('/projects/' + args.project + '/start_draft',
                          {'revision': project['revision'], 'confirmed': True})
        from embedded_agent.supplemental_tests import combine
        from embedded_agent.draft_verification import verify
        def boundary_check(current):
            return verify(root, combine(current['artifacts']['engineering_draft']['firmware']['files'], boundary_cases), 'Cortex-M0plus')
        boundary_report = boundary_check(project)
        save('boundary-initial.json', boundary_report)
    frozen = {k: v for k, v in project['artifacts']['engineering_draft']['firmware']['files'].items()
              if Path(k).name.startswith('test_')}
    feedback = ''
    instruction = ('你是嵌入式软件修复执行者。根据源码和真实原测试自行诊断修复。只输出repair_contract格式单个JSON。'
                   '只改现有生产C/H文件，不能修改测试、删除断言、硬编码测试时刻。patches最多3个文件，每文件最多6处唯一原文替换。'
                   '务必逐条审查全部测试，保留已通过行为。保持接口，32位无符号时差支持回绕；到期动作应在同次tick执行。'
                   '每次仅输出必要的小补丁，old必须逐字匹配当前源码，sha256必须使用当前哈希。')
    for attempt in range(args.attempts):
        project = api('/projects/' + args.project)
        if project['status'] == 'documents_delivered':
            break
        if project['status'] == 'draft_verified' and (not boundary_cases or boundary_report['status'] == 'passed'):
            action('execute', {}, 'Original tests and actual MCU object compilation passed; package verified sources')
            break
        files = project['artifacts']['engineering_draft']['firmware']['files']
        assert all(files.get(k) == v for k, v in frozen.items()), 'Original tests changed'
        sources = {k: v for k, v in files.items() if k.endswith(('.c', '.h'))}
        report = project['artifacts'].get('draft_verification', {})
        host = report.get('host_tests', {})
        context = {'files': sources, 'sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()},
                   'verification': {'status': report.get('status'), 'host_log': host.get('log'),
                                    'mcu_status': report.get('mcu_compile', {}).get('status')},
                   'previous_error': feedback,
                   'requirements': 'Single calibrated axis; 30ms rail wait, then 400ms offset, 300ms center hold, '
                   '2000ms emergency cutoff. Busy park must center then hold 300ms. Voice configuration must reject ambiguous IDs.'}
        if boundary_cases:
            context['additional_frozen_tests'] = boundary_cases
            context['boundary_failure'] = boundary_report['host_tests'].get('log')
            context['requirements'] += (' Missing millis/PWM/power callbacks must reject motion before powering on; '
                                        'hold 400ms from actual offset output; repeated park must never extend the absolute 2000ms safety cutoff. '
                                        'Update interface comments to match behavior. Preserve all original and additional tests.')
            context['diagnostic_hint'] = ('核对时间字段的所有写入：动作接受时写action_start_ms，SETTLE输出时又改写它，'
                                          '因此它不再是绝对总起点。原测试要求回绕，新增测试要求实际阶段保持和绝对超时，'
                                          '需分别维护总动作与阶段时间，不能只改注释。重复park测试会在第一次断电后继续调用park；'
                                          '必须同时审查busy路径和idle路径中rail_off_pending及deadline是否被重设。'
                                          '不要重写整文件或修改测试；只输出唯一原文的有效补丁，修复后以真实测试结果为准。')
        try:
            answer = model.generate(role='focused_repair', instruction=instruction, context=context)
            save(str(attempt + 1) + '-model.json', answer)
            if isinstance(answer.get('repair_contract'), dict):
                answer = answer['repair_contract']
            patches = answer.get('patches')
            if not isinstance(patches, list) or not 1 <= len(patches) <= 3:
                raise ValueError('patches must contain 1 to 3 production file patches')
            reason = answer.get('rationale') or 'Model repair based on original tests'
            for patch in patches:
                action('draft_patch', dict(patch, rationale=reason), reason)
            action('draft_verify', {'cpu': 'Cortex-M0plus'}, 'Run original immutable tests and actual MCU compiler')
            project = api('/projects/' + args.project)
            if boundary_cases:
                boundary_report = boundary_check(project)
                save(str(attempt + 1) + '-boundary.json', boundary_report)
            save(str(attempt + 1) + '-result.json', project)
            feedback = ''
            print(json.dumps({'attempt': attempt + 1, 'status': project['status'],
                              'cost_cny': settings.budget.status()['accounted_cny'] - before['accounted_cny']}, ensure_ascii=False), flush=True)
        except BudgetPaused:
            raise
        except (ValueError, KeyError) as exc:
            feedback = str(exc)
            save(str(attempt + 1) + '-error.json', {'error': feedback})
            print('Repair feedback: ' + feedback[:400], flush=True)
    project = api('/projects/' + args.project)
    if project['status'] == 'draft_verified' and (not boundary_cases or boundary_report['status'] == 'passed'):
        action('execute', {}, 'Original tests and actual MCU compiler passed')
        project = api('/projects/' + args.project)
    save('final.json', {'status': project['status'], 'before': before, 'after': settings.budget.status()})
    if project['status'] == 'documents_delivered':
        if run is not None:
            action('finish', {}, 'Verified software draft delivered; hardware remains not_run')
        with urlopen('http://127.0.0.1:8765/projects/' + args.project + '/download') as response:
            (folder / 'agent-verified.zip').write_bytes(response.read())
    print('FINAL ' + project['status'] + ' ' + str(folder), flush=True)

if __name__ == '__main__':
    main()
