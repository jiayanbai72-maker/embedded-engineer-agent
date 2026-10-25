"""Board-free curriculum; tool regression is not a model competence certificate."""
import hashlib
import json

STAGES=[
 ('requirements','需求与接口契约',['test_intake','test_contracts','test_runtime_protocol_v2']),
 ('evidence','本地资料、引用与假设',['test_library','test_retrieval_improvements','test_reference_aliases','test_selection','test_power','test_online_research','test_autonomous_evidence']),
 ('artifacts','方案、图纸和源码草案',['test_design','test_draft_workflow']),
 ('repair','诊断、修复与复验',['test_assertion_diagnostics','test_repair_coach','test_draft_verify','test_draft_regression','test_validation_repair','test_test_suites','test_supplemental_tests']),
 ('execution','调度、恢复与进度',['test_control','test_planning','test_completed_plan','test_research_dispatch','test_research_orchestration','test_live_progress']),
 ('delivery_budget','交付边界与费用保护',['test_readiness','test_model_context','test_local_model','test_prompt_layout'])]


def fingerprint(root):
    paths=sorted((root/'src/embedded_agent').rglob('*.py'))+sorted((root/'tests').glob('test_*.py'))+sorted((root/'tools').glob('*.py'))
    h=hashlib.sha256()
    for path in paths:h.update(str(path.relative_to(root)).encode());h.update(path.read_bytes())
    return h.hexdigest()


def status(root):
    path=root/'runtime/offline-training/latest.json'
    if path.exists():
        report=json.loads(path.read_text(encoding='utf-8'))
        report['current_code']=report.get('code_sha256')==fingerprint(root)
    else:report={'stages':[],'current_code':False,'status':'not_run'}
    report.update(scope='board_free_software_training',hardware='not_run',model_independence_proven=False,
                  note='这里只记录离线软件回归；不把工具测试通过当作模型独立排错或硬件通过。')
    model_path=root/'runtime/draft-validation/repair-model-holdout.json'
    if model_path.exists():
        m=json.loads(model_path.read_text(encoding='utf-8'))
        report['model_holdout']={k:m.get(k) for k in ('model','passed','model_calls','cost_delta_cny','tests_unchanged')}
        report['model_holdout']['scope']='仅历史单个合成迁移案例，不是通用能力证明'
    return report
