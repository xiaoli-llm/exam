"""Verify committed outputs against business invariants, not just model words."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    for folder in (ROOT, ROOT / 'live'):
        if not (folder / 'evaluation-summary.json').exists():
            continue
        summary = json.loads((folder / 'evaluation-summary.json').read_text(encoding='utf-8'))
        assert summary['tests_exit_code'] == 0
        for case in summary['cases']:
            output = json.loads((folder / case['trace_and_output']).read_text(encoding='utf-8'))
            request = json.loads((folder / case['input']).read_text(encoding='utf-8'))
            result = output['result']
            assert result['status'] == case['expected'], case['case']
            assert result['publication_status'] == 'not_published'
            assert result['requested_slot'] == request['requested_slot']
            assert len(output['trace']) <= output['max_steps']
            assert output['tool_calls'] <= output['max_steps']
            if result['status'] in ('completed', 'pending_confirmation'):
                assert result['review']['status'] == 'approved'
                assert result['save_status'] in ('saved', 'existing') and result['draft_id']
                assert result['suggested_slot'] in request['candidate_slots']
                assert case['draft_count'] == 1
                assert any(s['action'] == 'save_draft' and s['observation']['ok'] for s in output['trace'])
            else:
                assert case['draft_count'] == 0
                assert result['draft_id'] is None
            if case['case'] == 'conflict':
                assert result['suggested_slot'].endswith('19:00:00+08:00')
                assert result['confirmation_status'] == 'pending'
                assert 'confirm_hard_time_change' in result['pending_items']
            if case['case'] == 'occupancy_changed':
                assert result['suggested_slot'] == request['requested_slot']
            if case['case'] == 'risk':
                assert result['review']['risks']
            if case['case'] == 'missing':
                assert result['review']['missing'] and result['pending_items']
            if case['case'] == 'save_failure':
                assert result['save_status'] == 'failed'
            if case['case'] == 'repeat':
                first = json.loads((folder / 'repeat.first.json').read_text(encoding='utf-8'))
                assert result['draft_id'] == first['result']['draft_id']
                assert result['save_status'] == 'existing'
            if summary['mode'] != 'mock':
                assert output['model']['evidence_boundary'] == 'live_model'
                assert all(s.get('model_response', {}).get('id') for s in output['trace'])
        print(f"Verified {len(summary['cases'])} cases: {folder.name} ({summary['mode']})")


if __name__ == '__main__':
    main()
