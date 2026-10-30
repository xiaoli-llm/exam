import argparse
import json
import sys
import sqlite3
from pathlib import Path
from .agent import run
from .core import Tools
from .models import JsonModel, MockModel, load_config


def main():
    # Keep redirected JSON portable on Windows where the console default may be GBK.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Review materials and save schedule drafts; never publish.')
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--data', type=Path, default=Path('data/catalog.json'))
    parser.add_argument('--db', type=Path, default=Path('work/drafts.sqlite'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--config', type=Path, help='Optional private JSON config with MODEL_* keys')
    parser.add_argument('--model', choices=['mock', 'ollama', 'compatible'], default='mock')
    parser.add_argument('--max-steps', type=int, default=12)
    parser.add_argument('--simulate-save-failure', action='store_true', help='Explicit test-only fault injection')
    args = parser.parse_args()
    try:
        load_config(args.config)
        request = json.loads(args.input.read_text(encoding='utf-8-sig'))
        data = json.loads(args.data.read_text(encoding='utf-8-sig'))
        model = MockModel() if args.model == 'mock' else JsonModel(args.model)
        args.db.parent.mkdir(parents=True, exist_ok=True)
        tools = Tools(request, data, args.db, args.simulate_save_failure)
        try:
            result = run(tools, model, args.max_steps)
        finally:
            tools.close()
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + '\n', encoding='utf-8')
        print(output)
        return 0 if result['result']['status'] in ('completed', 'pending_confirmation') else 2
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'status': 'failed', 'error': 'configuration_or_input_error',
                          'type': type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
