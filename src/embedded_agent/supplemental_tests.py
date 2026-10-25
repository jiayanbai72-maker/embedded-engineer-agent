"""Compose frozen independent mock suites into one isolated C test entry."""
import re

ALIASES = ('main', 'now', 'pulses', 'rail', 'last_us', 'pwm', 'power', 'clock_ms', 'hal', 'setup', 'cal')

def combine(files, cases):
    originals = [n for n in files if n.startswith('test_') and n.endswith('.c')]
    if len(originals) != 1:
        raise ValueError('One original test entry is required')
    original = files[originals[0]]
    if len(re.findall(r'\bint\s+main\s*\(', original)) != 1:
        raise ValueError('Original test main must be unambiguous')
    sections = ['#define main frozen_original_main\n' + original + '\n#undef main\n']
    calls = ['frozen_original_main']
    for index, (name, source) in enumerate(sorted(cases.items())):
        if len(re.findall(r'\bint\s+main\s*\(', source)) != 1:
            raise ValueError('Supplemental test main must be unambiguous: ' + name)
        prefix = 'audit_' + str(index) + '_'
        sections.append('\n'.join('#define ' + token + ' ' + prefix + token for token in ALIASES))
        if not re.fullmatch(r'[A-Za-z0-9_]+', name):
            raise ValueError('Unsafe supplemental test name')
        sections.append('#line 1 "boundary_' + name + '.c"\n' + source)
        sections.append('\n'.join('#undef ' + token for token in ALIASES))
        calls.append(prefix + 'main')
    sections.append('int main(void){\n' + ''.join('if(' + name + '()!=0)return 1;\n' for name in calls) + 'return 0;\n}\n')
    result = {n: b for n, b in files.items() if n.endswith(('.c', '.h')) and n not in originals}
    result['test_combined.c'] = '\n'.join(sections)
    return result
