"""Generate actual offline executions and test report, without touching live evidence."""
import json
import subprocess
import sys
import tempfile
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agent import run
from src.core import Tools
from src.models import MockModel, JsonModel, load_config

S18, S19 = '2026-11-01T18:00:00+08:00', '2026-11-01T19:00:00+08:00'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['mock', 'ollama', 'compatible'], default='mock')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    load_config(args.config)
    model = MockModel() if args.model == 'mock' else JsonModel(args.model)
    folder = ROOT / 'examples' if args.model == 'mock' else ROOT / 'examples/live'
    folder.mkdir(parents=True, exist_ok=True)
    (ROOT / 'work').mkdir(exist_ok=True)
    data = json.loads((ROOT / 'data/catalog.json').read_text(encoding='utf-8'))
    cases = [
        ('normal', {}, 'completed', False, 12),
        ('missing', {'material_id': 'M02'}, 'needs_information', False, 12),
        ('risk', {'material_id': 'M03'}, 'blocked', False, 12),
        ('conflict', {'channel': 'video'}, 'pending_confirmation', False, 12),
        ('repeat', {}, 'completed', False, 12),
        ('save_failure', {}, 'failed', True, 12),
        ('supplement', {'material_id': 'M04'}, 'completed', False, 12),
        ('limit', {}, 'incomplete', False, 2),
        ('approved', {'channel': 'video', 'approved_slots': [S19]}, 'completed', False, 12),
        ('occupancy_changed', {'channel': 'video'}, 'completed', False, 12),
    ]
    summary = []
    with tempfile.TemporaryDirectory(dir=ROOT / 'work') as temp:
        for name, overrides, expected, fail, limit in cases:
            req = {'request_id': name, 'material_id': 'M01', 'channel': 'article',
                   'requested_slot': S18, 'candidate_slots': [S18, S19], 'hard_time': True, **overrides}
            (folder / f'{name}.input.json').write_text(json.dumps(req, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            case_data = json.loads(json.dumps(data))
            if name == 'occupancy_changed':
                case_data['occupied'] = [{'channel': 'video', 'slot': S19}]
                (folder / 'occupancy_changed.data.json').write_text(json.dumps(case_data, ensure_ascii=False, indent=2), encoding='utf-8')
            tools = Tools(req, case_data, Path(temp) / f'{name}.sqlite', fail)
            try:
                if name == 'repeat':
                    first = run(tools, model, limit)
                    (folder / 'repeat.first.json').write_text(json.dumps(first, ensure_ascii=False, indent=2), encoding='utf-8')
                    tools.close()
                    tools = Tools(req, case_data, Path(temp) / f'{name}.sqlite', fail)
                out = run(tools, model, limit)
                count = tools.db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]
            finally:
                tools.close()
            (folder / f'{name}.output.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            passed = out['result']['status'] == expected
            if name == 'repeat':
                passed = passed and count == 1 and out['result']['save_status'] == 'existing'
            if fail:
                passed = passed and count == 0 and out['result']['save_status'] == 'failed'
            summary.append({'case': name, 'expected': expected, 'actual': out['result']['status'],
                            'draft_count': count, 'passed': passed,
                            'input': f'{name}.input.json', 'trace_and_output': f'{name}.output.json'})
    tests = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                           cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace')
    (folder / 'test-results.txt').write_text(tests.stdout + tests.stderr, encoding='utf-8')
    result = {'generated_at': datetime.now(timezone.utc).isoformat(), 'mode': args.model,
              'evidence_boundary': 'flow_only_not_real_model_decisions' if args.model == 'mock' else 'live_model',
              'cases': summary, 'tests_exit_code': tests.returncode}
    (folder / 'evaluation-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if tests.returncode == 0 and all(x['passed'] for x in summary) else 1


if __name__ == '__main__':
    sys.exit(main())
