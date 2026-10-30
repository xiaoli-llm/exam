"""Bounded observe/decide/act loop with authoritative final projection."""
from datetime import datetime, timezone


def run(tools, model, max_steps=12):
    if not 1 <= max_steps <= 100:
        raise ValueError('max_steps must be between 1 and 100')
    history = []
    status, reason = 'incomplete', 'step_limit_reached'
    for step in range(1, max_steps + 1):
        try:
            decision = model.decide(tools.request, history)
            if not isinstance(decision, dict) or set(decision) != {'action', 'arguments', 'reason'}:
                raise ValueError('invalid action shape')
            action, args = decision['action'], decision['arguments']
            if not isinstance(action, str) or not isinstance(args, dict) or not isinstance(decision['reason'], str):
                raise ValueError('invalid action types')
        except Exception as exc:
            # Never include exception messages: upstream errors may contain keys or private payloads.
            status, reason = 'failed', 'model_error:' + type(exc).__name__
            history.append({'step': step, 'action': 'model_error', 'arguments': {},
                            'reason': '模型未返回有效动作', 'observation': {'ok': False, 'error': reason}})
            break
        if action == 'finish':
            requested = args.get('status')
            allowed = {'completed', 'pending_confirmation', 'blocked', 'needs_information', 'failed'}
            if set(args) != {'status', 'reason'} or not isinstance(requested, str) or requested not in allowed or not isinstance(args['reason'], str):
                observation = {'ok': False, 'error': 'invalid_finish'}
            elif tools.saved:
                status = 'pending_confirmation' if tools.saved['confirmation_status'] == 'pending' else 'completed'
                reason = args['reason']
                observation = {'ok': True, 'status': status}
            elif requested in ('completed', 'pending_confirmation'):
                observation = {'ok': False, 'error': 'cannot_finish_success_without_saved_draft'}
            else:
                status, reason = requested, args['reason']
                observation = {'ok': True, 'status': status}
        else:
            observation = tools.execute(action, args)
        history.append({'step': step, 'at': datetime.now(timezone.utc).isoformat(),
                        'action': action, 'arguments': args, 'reason': decision['reason'],
                        'observation': observation})
        if hasattr(model, 'last_call'):
            history[-1]['model_response'] = model.last_call
        if action == 'finish' and observation.get('ok'):
            break
    return {'schema_version': 1, 'model': {'mode': model.mode, 'name': model.name,
            'evidence_boundary': 'flow_only' if model.mode == 'mock' else 'live_model'},
            'max_steps': max_steps, 'tool_calls': sum(h['action'] not in ('finish', 'model_error') for h in history),
            'result': tools.report(status, reason), 'trace': history}
