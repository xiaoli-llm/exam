import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from src.agent import run
from src.core import Tools
from src.models import MockModel, JsonModel

ROOT = Path(__file__).resolve().parents[1]
S18 = '2026-11-01T18:00:00+08:00'
S19 = '2026-11-01T19:00:00+08:00'


def request(**overrides):
    return {'request_id': 'req-1', 'material_id': 'M01', 'channel': 'article',
            'requested_slot': S18, 'candidate_slots': [S18, S19], 'hard_time': True, **overrides}


class ScriptModel:
    mode, name = 'mock', 'adversarial-test-driver'

    def __init__(self, decisions):
        self.decisions = iter(decisions)

    def decide(self, request, history):
        return next(self.decisions)


def action(name, **args):
    return {'action': name, 'arguments': args, 'reason': 'test'}


class AgentTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'work').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'work')
        self.db = Path(self.tmp.name) / 'drafts.sqlite'
        self.data = json.loads((ROOT / 'data/catalog.json').read_text(encoding='utf-8'))
        self.opened = []

    def tearDown(self):
        for tools in self.opened:
            tools.close()
        self.tmp.cleanup()

    def tools(self, req=None, **kw):
        tools = Tools(req or request(), self.data, self.db, **kw)
        self.opened.append(tools)
        return tools

    def test_normal(self):
        out = run(self.tools(), MockModel())
        self.assertEqual(out['result']['status'], 'completed')
        self.assertEqual(out['result']['save_status'], 'saved')
        self.assertEqual(out['result']['publication_status'], 'not_published')
        self.assertEqual([s['action'] for s in out['trace']],
                         ['read_material', 'check_rules', 'query_slots', 'save_draft', 'finish'])

    def test_cli_redirected_output_is_utf8_json(self):
        process = subprocess.run([sys.executable, '-m', 'src.cli', '--input',
                                  'examples/normal.input.json', '--db', str(self.db)],
                                 cwd=ROOT, capture_output=True)
        self.assertEqual(process.returncode, 0)
        result = json.loads(process.stdout.decode('utf-8'))
        self.assertEqual(result['result']['status'], 'completed')
        self.assertEqual(result['trace'][0]['observation']['material']['title'], self.data['materials']['M01']['title'])

    def test_conflict_requires_confirmation(self):
        out = run(self.tools(request(channel='video')), MockModel())
        self.assertEqual(out['result']['status'], 'pending_confirmation')
        self.assertEqual(out['result']['requested_slot'], S18)
        self.assertEqual(out['result']['suggested_slot'], S19)
        self.assertIn('confirm_hard_time_change', out['result']['pending_items'])

    def test_explicit_approval(self):
        out = run(self.tools(request(channel='video', approved_slots=[S19])), MockModel())
        self.assertEqual(out['result']['status'], 'completed')

    def test_soft_time(self):
        out = run(self.tools(request(channel='video', hard_time=False)), MockModel())
        self.assertEqual(out['result']['status'], 'completed')

    def test_missing_and_supplement(self):
        for material, expected in [('M02', 'needs_information'), ('M04', 'completed')]:
            with self.subTest(material=material):
                out = run(self.tools(request(material_id=material)), MockModel())
                self.assertEqual(out['result']['status'], expected)
                self.assertIn('lookup_metadata', [s['action'] for s in out['trace']])

    def test_rule_risk_and_rights(self):
        for material in ['M03', 'M05']:
            with self.subTest(material=material):
                out = run(self.tools(request(material_id=material)), MockModel())
                self.assertEqual(out['result']['status'], 'blocked')
                self.assertEqual(out['result']['save_status'], 'not_saved')

    def test_not_found(self):
        out = run(self.tools(request(material_id='unknown')), MockModel())
        self.assertEqual(out['result']['status'], 'needs_information')

    def test_repeat_and_changed_key(self):
        first = run(self.tools(), MockModel())
        second = run(self.tools(), MockModel())
        self.assertEqual(first['result']['draft_id'], second['result']['draft_id'])
        self.assertEqual(second['result']['save_status'], 'existing')
        third_tools = self.tools(request(hard_time=False))
        third = run(third_tools, MockModel())
        self.assertEqual(third['result']['status'], 'failed')
        self.assertEqual(third_tools.db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 1)

    def test_save_failure(self):
        tools = self.tools(fail_save=True)
        out = run(tools, MockModel())
        self.assertEqual(out['result']['status'], 'failed')
        self.assertEqual(out['result']['save_status'], 'failed')
        self.assertEqual(tools.db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 0)

    def test_limit(self):
        out = run(self.tools(), MockModel(), max_steps=2)
        self.assertEqual(out['result']['status'], 'incomplete')
        self.assertEqual(out['result']['reason'], 'step_limit_reached')
        self.assertEqual(len(out['trace']), 2)

    def test_cannot_forge_success_or_publish(self):
        model = ScriptModel([action('finish', status='completed', reason='pretend'), action('publish')])
        out = run(self.tools(), model, 2)
        self.assertEqual(out['result']['status'], 'incomplete')
        self.assertFalse(out['trace'][0]['observation']['ok'])
        self.assertFalse(out['trace'][1]['observation']['ok'])
        self.assertEqual(out['result']['publication_status'], 'not_published')

    def test_cannot_skip_review(self):
        tools = self.tools(request(material_id='M03'))
        self.assertEqual(tools.execute('save_draft', {'slot': S18})['error'], 'review_not_approved')
        tools.execute('read_material', {})
        tools.execute('check_rules', {})
        tools.execute('query_slots', {})
        self.assertEqual(tools.execute('save_draft', {'slot': S18})['error'], 'review_not_approved')

    def test_cannot_save_unchecked_or_outside_slot(self):
        tools = self.tools()
        tools.execute('read_material', {})
        tools.execute('check_rules', {})
        self.assertFalse(tools.execute('save_draft', {'slot': S18})['ok'])
        tools.execute('query_slots', {})
        self.assertFalse(tools.execute('save_draft', {'slot': '2026-11-02T20:00:00+08:00'})['ok'])

    def test_recheck_conflict_at_commit(self):
        one = self.tools()
        for name in ['read_material', 'check_rules', 'query_slots']:
            one.execute(name, {})
        run(self.tools(request(request_id='req-2')), MockModel())
        self.assertEqual(one.execute('save_draft', {'slot': S18})['error'], 'slot_conflict_at_save')

    def test_changed_occupancy_changes_decision(self):
        before = run(self.tools(request(channel='video')), MockModel())
        self.data['occupied'] = [{'channel': 'video', 'slot': S19}]
        after = run(self.tools(request(channel='video', request_id='req-2')), MockModel())
        self.assertEqual(before['result']['suggested_slot'], S19)
        self.assertEqual(after['result']['suggested_slot'], S18)

    def test_no_slots(self):
        self.data['occupied'] += [{'channel': 'video', 'slot': S19}]
        out = run(self.tools(request(channel='video')), MockModel())
        self.assertEqual(out['result']['status'], 'blocked')
        self.assertEqual(out['result']['save_status'], 'not_saved')

    def test_bad_model_output_and_no_fallback(self):
        out = run(self.tools(), ScriptModel([{'nonsense': True}]))
        self.assertEqual(out['result']['status'], 'failed')
        self.assertEqual(out['result']['save_status'], 'not_saved')

    def test_input_validation(self):
        for override in [{'hard_time': 'false'}, {'requested_slot': '18:00'},
                         {'approved_slots': ['2026-11-03T19:00:00+08:00']}, {'candidate_slots': 'bad'}]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.tools(request(**override))

    def test_same_instant_cannot_bypass_conflict(self):
        out = run(self.tools(request(channel='video', requested_slot='2026-11-01T10:00:00+00:00')), MockModel())
        self.assertEqual(out['result']['status'], 'pending_confirmation')
        self.assertEqual(out['result']['suggested_slot'], S19)

    def test_malformed_finish_and_slot_are_rejected(self):
        out = run(self.tools(), ScriptModel([action('finish', status={}, reason='bad')]), 1)
        self.assertEqual(out['result']['status'], 'incomplete')
        self.assertFalse(out['trace'][0]['observation']['ok'])
        self.assertFalse(self.tools().execute('save_draft', {'slot': []})['ok'])

    def test_live_adapter_round_trip_contract(self):
        # HTTP transport contract only; this is NOT a real model evaluation.
        import io
        decision = action('read_material')
        response = io.BytesIO(json.dumps({'message': {'content': json.dumps(decision)}}).encode())
        with patch.dict('os.environ', {'MODEL_NAME': 'test-local', 'MODEL_BASE_URL': 'http://localhost:11434'}):
            model = JsonModel('ollama')
            with patch('urllib.request.urlopen', return_value=response) as call:
                self.assertEqual(model.decide(request(), []), decision)
                self.assertEqual(call.call_args.args[0].full_url, 'http://localhost:11434/api/chat')


if __name__ == '__main__':
    unittest.main()
