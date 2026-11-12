"""Evaluate saved real-model runs. Never infer correctness from exit code alone."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--text', default='final_text')
p.add_argument('--long', default='final_long')
p.add_argument('--overlap', default='final_overlap')
p.add_argument('--require-overlap', action='store_true', help='Exit nonzero if the full audio acceptance case fails')
args = p.parse_args()


def read(folder, name):
    return json.loads((ROOT / 'results' / folder / name).read_text(encoding='utf-8'))


def items(orders):
    return {speaker: sorted((i['menu_id'], i['quantity'], tuple(sorted(i['options']))) for i in values)
            for speaker, values in orders['speakers'].items() if values}


text_orders = read(args.text, 'orders.json')
long_orders = read(args.long, 'orders.json')
overlap_orders = read(args.overlap, 'orders.json')
expected_overlap = {'speaker_0': [('curry', 1, ('감자 빼기',))],
                    'speaker_1': [('cola', 1, ()), ('special_tendon', 1, ())]}
checks = {
    'text_order_changes': items(text_orders) == {'speaker_0': [('jajang', 2, ())], 'speaker_1': [('jjamppong', 1, ())]},
    'unknown_and_uncertain_held': text_orders['review_count'] == 2,
    'long_recording_order_preserved': items(long_orders) == {'speaker_0': [('curry', 1, ('감자 빼기',))]},
    'overlap_complete_order': items(overlap_orders) == expected_overlap,
    'overlap_confirmation_required': overlap_orders['status'] == 'needs_confirmation',
}
report = {
    'integration_complete': all(read(folder, 'metrics.json')['status'] == 'complete' for folder in (args.text,args.long,args.overlap)),
    'checks': checks,
    'ready_for_app_accuracy_gate': all(checks.values()),
    'overlap_expected': expected_overlap,
    'overlap_actual': items(overlap_orders),
    'runs': {folder: read(folder, 'metrics.json') for folder in (args.text,args.long,args.overlap)},
    'scope': 'Smoke tests only: one scripted transcript, repeated 91.756-second audio, one synthetic Korean overlap. Not a benchmark.',
}
target = ROOT / 'results/validation.json'
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
if args.require_overlap and not report['ready_for_app_accuracy_gate']:
    raise SystemExit(1)
