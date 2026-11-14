"""Evaluate speaker-attributed Korean transcription on the curated 2-speaker mixtures."""
import argparse
import itertools
import json
import re
import sys
import time
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from drive_order.nemotron35 import DEFAULT_MODEL, write_transcription
from drive_order.orders import dump


def normalized(text):
    return re.sub(r'[^0-9a-zA-Z가-힣]', '', text).lower()


def edit_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for row, left in enumerate(reference, 1):
        current = [row]
        for column, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (left != right)))
        previous = current
    return previous[-1]


def best_assignment(references, predictions):
    size = max(len(references), len(predictions))
    refs = references + [''] * (size - len(references))
    preds = predictions + [''] * (size - len(predictions))
    best = None
    for order in itertools.permutations(range(size)):
        distances = [edit_distance(normalized(refs[i]), normalized(preds[order[i]])) for i in range(size)]
        candidate = (sum(distances), order, distances)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8000/v1')
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--api-key', default='EMPTY')
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('--output must be new or empty')
    args.output.mkdir(parents=True, exist_ok=True)
    records = [json.loads(line) for line in args.manifest.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if args.limit:
        records = records[:args.limit]
    results, total_edits, total_reference, found_menu, total_menu = [], 0, 0, 0, 0
    for record in records:
        sample_dir = args.output / record['demo_id']
        sample_dir.mkdir()
        terms = []
        for source in record['sources']:
            terms.extend(source.get('menu_spans') or [])
        menu = {'store_id': record['category'], 'items': [
            {'id': f'term_{index}', 'name': term} for index, term in enumerate(dict.fromkeys(terms))]}
        started = time.monotonic()
        turns = write_transcription(record['mixture_path'], sample_dir, menu,
            base_url=args.url, model=args.model, api_key=args.api_key,
            max_speakers=2, max_tokens=args.max_tokens)
        elapsed = time.monotonic() - started
        by_speaker = {}
        for turn in turns:
            by_speaker.setdefault(turn['speaker'], []).append(turn)
        speaker_ids = sorted(by_speaker)
        predictions = [' '.join(turn['text'] for turn in by_speaker[speaker]) for speaker in speaker_ids]
        references = [source['transcript'] for source in record['sources']]
        edits, assignment, distances = best_assignment(references, predictions)
        reference_chars = sum(len(normalized(text)) for text in references)
        sample_found, sample_total = 0, 0
        for index, source in enumerate(record['sources']):
            predicted = predictions[assignment[index]] if assignment[index] < len(predictions) else ''
            for term in source.get('menu_spans') or []:
                sample_total += 1
                sample_found += normalized(term) in normalized(predicted)
        duration = sf.info(record['mixture_path']).duration
        result = {
            'demo_id': record['demo_id'],
            'audio_seconds': duration,
            'inference_seconds': elapsed,
            'real_time_factor': elapsed / duration,
            'speaker_count': len(predictions),
            'speaker_ids': speaker_ids,
            'references': references,
            'predictions': predictions,
            'reference_to_prediction': list(assignment[:len(references)]),
            'character_edits': edits,
            'character_error_rate': edits / max(1, reference_chars),
            'menu_terms_found': sample_found,
            'menu_terms_total': sample_total,
        }
        dump(sample_dir / 'evaluation.json', result)
        results.append(result)
        total_edits += edits
        total_reference += reference_chars
        found_menu += sample_found
        total_menu += sample_total
        print(f"{record['demo_id']}: cpCER={result['character_error_rate']:.3f}, "
              f"menu={sample_found}/{sample_total}, RTF={result['real_time_factor']:.3f}", flush=True)
    summary = {
        'model': args.model,
        'sample_count': len(results),
        'cp_character_error_rate': total_edits / max(1, total_reference),
        'menu_term_recall': found_menu / max(1, total_menu),
        'menu_terms_found': found_menu,
        'menu_terms_total': total_menu,
        'mean_real_time_factor': sum(item['real_time_factor'] for item in results) / max(1, len(results)),
        'samples': results,
    }
    dump(args.output / 'summary.json', summary)
    print(json.dumps({key: value for key, value in summary.items() if key != 'samples'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
