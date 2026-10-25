import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_architecture
from embedded_agent import keil
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController


class KeilTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def imported(self):
        folder = self.root / 'fixture'; folder.mkdir()
        (folder / 'main.c').write_text('int main(void) { return 0 }', encoding='utf-8')
        project = folder / 'example.uvprojx'
        project.write_text('<Project><Targets><Target><TargetName>Debug</TargetName><TargetOption><Device>Example</Device><OutputDirectory>Objects</OutputDirectory></TargetOption><Groups><Group><Files><File><FilePath>main.c</FilePath></File></Files></Group></Groups></Target></Targets></Project>', encoding='utf-8')
        service = EngineeringService(self.root)
        p = service.create('构建可信现有工程')
        p = service.update(p['id'], p['revision'], 'keil_import', {'file': str(project), 'confirmed': True})
        return service, p, folder

    def test_diagnostics_armcc_and_armclang(self):
        rows = keil.diagnostics('User\\main.c(17): error: #65: expected a ";"\nC:\\work\\main.c:8:3: warning: unused variable\nError: L6218E: Undefined symbol foo')
        self.assertEqual([r['line'] for r in rows], [17, 8])
        self.assertEqual(rows[1]['column'], 3)

    def test_copy_hash_edit_and_original_preserved(self):
        service, p, original = self.imported()
        info = p['artifacts']['keil_project']
        source = keil.read_source(self.root, info, 'main.c')
        with self.assertRaises(ValueError): keil.read_source(self.root, info, '../outside.c')
        with self.assertRaises(ValueError): keil.edit_source(self.root, info, [{'file': 'main.c', 'sha256': 'stale', 'content': 'int x;'}], '修改')
        result = keil.edit_source(self.root, info, [{'file': 'main.c', 'sha256': source['sha256'], 'content': 'int main(void) { return 0; }'}], '补齐分号')
        self.assertEqual(len(result['changes']), 1)
        self.assertIn('return 0 }', (original / 'main.c').read_text())

    def test_external_path_and_custom_command_rejected(self):
        service, p, original = self.imported()
        file = original / 'example.uvprojx'
        raw = file.read_text()
        file.write_text(raw.replace('main.c', '../main.c'))
        with self.assertRaises(ValueError): keil.inspect_project(file)
        file.write_text(raw.replace('<Device>', '<RunUserProg1>1</RunUserProg1><Device>'))
        with self.assertRaises(ValueError): keil.inspect_project(file)

    def test_controller_build_failure_read_repair_rebuild(self):
        service, p, original = self.imported()
        control = DecisionController(service); run = control.create(p['id'])
        calls = []
        def fixture_build(command, **kwargs):
            calls.append(command)
            current = keil.read_source(self.root, p['artifacts']['keil_project'], 'main.c')['content']
            failed = 'return 0 }' in current
            Path(command[-1]).write_text('main.c(1): error: #65: expected a ";"\n1 Error(s), 0 Warning(s).' if failed else '0 Error(s), 1 Warning(s).', encoding='utf-8')
            return SimpleNamespace(returncode=2 if failed else 1)
        def act(action, args):
            nonlocal run
            d = {'id': 'D-' + str(run['steps']), 'project_revision': run['project_revision'], 'action': action, 'arguments': args,
                 'rationale': '单元测试夹具', 'expected': '保存真实控制器回执', 'source': 'mock_uvision_not_real_build'}
            control.submit(run['id'], run['revision'], d); run = control.advance(run['id'])
        executable = original / 'UV4.exe'; executable.write_bytes(b'fixture')
        with patch.dict('os.environ', {'EMBEDDED_AGENT_UVISION': str(executable)}), patch('embedded_agent.keil.subprocess.run', side_effect=fixture_build):
            act('keil_build', {})
            self.assertEqual(run['observations'][-1]['tool_result']['diagnostics'][0]['line'], 1)
            self.assertEqual(service.get(p['id'])['status'], 'keil_build_failed')
            act('read_keil_source', {'file': 'main.c'})
            source = run['observations'][-1]['tool_result']['source']
            act('keil_edit', {'changes': [{'file': 'main.c', 'sha256': source['sha256'], 'content': 'int main(void) { return 0; }'}], 'rationale': '补齐分号'})
            self.assertEqual(run['repairs'], 1)
            act('keil_build', {})
        self.assertEqual(service.get(p['id'])['status'], 'ready_delivery')
        self.assertEqual(len(calls), 2)
        self.assertIn('return 0 }', (original / 'main.c').read_text())


if __name__ == '__main__': unittest.main()
