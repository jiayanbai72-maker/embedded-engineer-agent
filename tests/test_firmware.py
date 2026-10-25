import importlib.util
import os
import struct
import sys
from types import SimpleNamespace
import unittest
from uuid import uuid4
import test_architecture
from embedded_agent.firmware import validate_profile, check_images, build_firmware

PROFILE = {'cpu': 'Cortex-M3', 'mode': 'demonstration_only', 'flash_base': 0, 'flash_size': 65536,
           'ram_base': 0x20000000, 'ram_size': 20480, 'stack_size': 1024}


def hex_image(binary):
    lines = []
    for offset in range(0, len(binary), 16):
        payload = binary[offset:offset+16]
        row = bytes([len(payload)]) + offset.to_bytes(2, 'big') + b'\x00' + payload
        lines.append(':' + (row + bytes([-sum(row) % 256])).hex().upper())
    return ('\n'.join(lines) + '\n:00000001FF\n').encode()


class FirmwareTests(unittest.TestCase):
    setUp = test_architecture.ArchitectureTests.setUp
    tearDown = test_architecture.ArchitectureTests.tearDown

    def test_memory_profile_boundaries(self):
        validate_profile(PROFILE)
        for change in ({'ram_base': 0}, {'stack_size': 8}, {'flash_base': 8}, {'mode': 'actual_board'}, {'ram_size': True}):
            with self.assertRaises(ValueError): validate_profile(dict(PROFILE, **change))

    def test_vector_and_hex_validation(self):
        binary = struct.pack('<II', 0x20000400, 65) + b'\x00' * 72
        self.assertEqual(check_images(binary, hex_image(binary), PROFILE)['status'], 'passed')
        with self.assertRaises(ValueError): check_images(struct.pack('<II', 0, 65) + binary[8:], hex_image(binary), PROFILE)
        with self.assertRaises(ValueError): check_images(struct.pack('<II', 0x20000400, 64) + binary[8:], hex_image(binary), PROFILE)
        wrong = hex_image(binary).replace(b':00000001FF', b':0000000100')
        with self.assertRaises(ValueError): check_images(binary, wrong, PROFILE)
        with self.assertRaises(ValueError): check_images(binary, hex_image(binary[:-1]), PROFILE | {'flash_size': 64})

    @unittest.skipUnless(os.environ.get('EMBEDDED_AGENT_ARMCC'), 'real toolchain not configured')
    def test_real_firmware_build_and_link_failure(self):
        example = test_architecture.ROOT / 'examples'
        sys.path.insert(0, str(example))
        try:
            spec = importlib.util.spec_from_file_location('firmware_demo', example / 'run_firmware_build.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.run(self.root)
            self.assertEqual(result['firmware_build'], 'passed')
            self.assertEqual(result['hardware'], 'not_run')
            project = SimpleNamespace(id=str(uuid4()), artifacts={'firmware_implementation': {
                'profile': dict(PROFILE, flash_size=64), 'files': {'main.c': module.MAIN, 'button.c': module.SOURCE, 'button.h': module.HEADER}}})
            failure = build_firmware(self.root, project)
            self.assertEqual(failure['status'], 'failed')
            self.assertEqual(failure['images'], {})
            self.assertEqual(failure['firmware_link'], 'not_run')
            self.assertTrue(any(c['returncode'] != 0 for c in failure['commands']))
        finally:
            sys.path.pop(0)
