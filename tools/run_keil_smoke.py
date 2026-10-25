"""Rebuild a managed copy of the existing local Keil project; never flash."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from embedded_agent import keil


def main():
    previous = json.loads((ROOT / 'runtime/keil-verification-import.json').read_text(encoding='utf-8'))
    source = Path(previous['original'])
    before = {str(p.relative_to(source.parent)): keil.sha(p)
              for p in source.parent.rglob('*') if p.is_file()}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    imported = keil.import_project(ROOT, 'smoke-' + stamp, source, previous['target'])
    result = keil.build(ROOT, imported)
    after = {str(p.relative_to(source.parent)): keil.sha(p)
             for p in source.parent.rglob('*') if p.is_file()}
    folder = ROOT / imported['workspace']
    outputs = [{'file': str(p.relative_to(folder)), 'bytes': p.stat().st_size, 'sha256': keil.sha(p)}
               for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.axf', '.hex', '.map')]
    report = dict(result, imported=imported, original_unchanged=before == after, outputs=outputs,
                  model_calls=0, scope='existing_STM32F103C8_example_project_not_robot_STM32L031',
                  note='Actual uVision rebuild only; no autonomous repair exercised and no hardware connection.')
    (folder / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'verification.log').write_text(result.get('log', result.get('reason', '')), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'scope', 'original_unchanged', 'outputs', 'model_calls')}, ensure_ascii=False))
    print(result.get('log', result.get('reason', '')))
    print(str(folder / 'verification.json'))
    if result['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
