import base64
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_architecture
from embedded_agent import hardware
from embedded_agent.service import EngineeringService
from embedded_agent.control import DecisionController


def port(name='COM7'):
    return SimpleNamespace(device=name, description='USB Serial (fixture)', hwid='USB VID:PID=0000:0000',
                           vid=0, pid=0, serial_number='fixture', manufacturer='fixture', product='Serial bridge', location='fixture')


class HardwareTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_discovery_metadata_does_not_invent_board(self):
        library = SimpleNamespace(comports=lambda: [port()])
        with patch.object(hardware, 'serial_modules', return_value=(object(), library)):
            report = hardware.discover(self.root)
        self.assertFalse(report['opened_device'])
        self.assertIsNone(report['ports'][0]['mcu'])
        self.assertIsNone(report['ports'][0]['board_model'])
        self.assertFalse(report['board_catalog']['complete'])

    def test_binding_requires_user_and_live_identity(self):
        record = hardware.identity(port())
        with patch.object(hardware, 'discover', return_value={'status': 'passed', 'ports': [record]}):
            with self.assertRaises(ValueError): hardware.bind(self.root, {'port': 'COM7', 'baudrate': 115200})
            with self.assertRaises(ValueError): hardware.bind(self.root, {'port': 'COM7', 'baudrate': 115200, 'confirmed': True, 'fingerprint': 'stale'})
            binding = hardware.bind(self.root, {'port': 'COM7', 'baudrate': 115200, 'confirmed': True, 'fingerprint': record['fingerprint']})
        with patch.object(hardware, 'discover', return_value={'status': 'passed', 'ports': []}):
            with self.assertRaises(ValueError): hardware.capture(self.root, binding)

    def test_capture_raw_evidence_and_no_transmit(self):
        record = hardware.identity(port())
        binding = {'id': 'fixture', 'permission': 'user_confirmed', 'scope': 'serial_receive_only', 'port': record, 'baudrate': 115200}
        class Receiver:
            is_open = False
            def open(self): self.is_open = True
            def close(self): self.is_open = False
            def read(self, length): return b'boot ready\n\xff'
            def write(self, *args): raise AssertionError('must never send')
        receiver = Receiver()
        library = SimpleNamespace(Serial=lambda **kwargs: receiver, SerialException=OSError)
        with patch.object(hardware, 'discover', return_value={'status': 'passed', 'ports': [record]}), patch.object(hardware, 'serial_modules', return_value=(library, None)), patch.object(hardware.time, 'monotonic', side_effect=[0, 0, 2]):
            captured = hardware.capture(self.root, binding, 1)
        self.assertEqual(captured['status'], 'captured')
        self.assertEqual(base64.b64decode(captured['raw_base64']), b'boot ready\n\xff')
        self.assertEqual(captured['hardware_test'], 'not_run')
        self.assertFalse(captured['commands_sent'])
        self.assertFalse(receiver.is_open)
        self.assertFalse(receiver.dtr)

    def test_controller_cannot_bind_and_captures_are_persisted(self):
        service = EngineeringService(self.root); p = service.create('验证连接日志')
        control = DecisionController(service); run = control.create(p['id'])
        self.assertNotIn('hardware_capture', control.context(run['id'])['allowed_actions'])
        with self.assertRaises(ValueError): control.submit(run['id'], run['revision'], {'id': 'bad', 'action': 'hardware_bind', 'arguments': {}, 'source': 'test', 'expected': 'none', 'rationale': 'none', 'project_revision': p['revision']})
        record = hardware.identity(port())
        with patch.object(hardware, 'discover', return_value={'status': 'passed', 'ports': [record]}):
            p = service.update(p['id'], p['revision'], 'hardware_bind', {'port': 'COM7', 'baudrate': 115200, 'confirmed': True, 'fingerprint': record['fingerprint']})
        evidence = {'id': 'fixture', 'status': 'no_data', 'hardware_test': 'not_run'}
        with patch.object(hardware, 'capture', return_value=evidence):
            p = service.update(p['id'], p['revision'], 'hardware_capture', {'seconds': 1})
        restored = EngineeringService(self.root).get(p['id'])
        self.assertEqual(restored['artifacts']['hardware_captures'][-1]['status'], 'no_data')
        self.assertEqual(restored['verification']['hardware'], 'not_run')
        self.assertEqual(restored['status'], 'awaiting_analysis')


if __name__ == '__main__': unittest.main()
