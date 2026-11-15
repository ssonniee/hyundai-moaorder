import argparse
import os
import sys
import json
import time
from pathlib import Path

from .orders import LocalLLM, OrderBook, dump, validate_menu
from .trip import validate_trip


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description='Korean passenger order pipeline (local prototype)')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('audio', 'replay'):
        p = sub.add_parser(name)
        p.add_argument('--input', type=Path, required=True)
        p.add_argument('--menu', type=Path, required=True)
        p.add_argument('--trip', type=Path)
        p.add_argument('--output', type=Path, required=True)
        p.add_argument('--device', choices=['cpu', 'cuda'], default='cuda')
        p.add_argument('--llm', default=str(root / 'models/Qwen3-4B-Instruct-2507'))
        p.add_argument('--int4', action='store_true', help='Requires bitsandbytes; optional deployment experiment')
        p.add_argument('--order-backend', choices=['qwen', 'llm'], default='qwen')
        if name == 'audio':
            p.add_argument('--separated-audio', choices=['full', 'splice'], default='full')
            p.add_argument('--channel', type=int, default=0)
            p.add_argument('--threshold', type=float, default=.5)
            p.add_argument('--max-seconds', type=float, default=20)
            p.add_argument('--separator', choices=['sepformer', 'convtasnet', 'none'], default='sepformer')
            p.add_argument('--separator-python', default=os.environ.get('DRIVE_ORDER_SEPARATOR_PYTHON', sys.executable))
            p.add_argument('--sepformer-model', choices=['sepformer-wsj02mix', 'sepformer-whamr'], default='sepformer-wsj02mix')
            p.add_argument('--asr', choices=['nemo', 'whisper'], default='whisper')
            p.add_argument('--skip-orders', action='store_true', help='Audio stages only; no order claims')
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error('Input does not exist')
    menu = json.loads(args.menu.read_text(encoding='utf-8-sig'))
    validate_menu(menu)
    trip = json.loads(args.trip.read_text(encoding='utf-8-sig')) if args.trip else None
    route = validate_trip(trip, menu) if trip else None
    if args.command == 'audio' and (not 0 < args.threshold < 1 or not 2 <= args.max_seconds <= 30):
        parser.error('threshold must be in (0,1); max-seconds in [2,30]')
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be a new/empty directory to avoid mixing sessions')
    args.output.mkdir(parents=True, exist_ok=True)
    dump(args.output / 'menu.json', menu)
    if trip:
        dump(args.output / 'trip.json', trip)
        dump(args.output / 'navigation_request.json', route)
    started = time.monotonic()
    metrics = {'mode': args.command, 'device': args.device, 'llm': args.llm,
               'input': str(args.input.resolve()), 'status': 'running', 'stages_seconds': {}}
    import torch
    torch.set_num_threads(4)
    if args.device == 'cuda':
        torch.cuda.reset_peak_memory_stats()
    try:
        if args.command == 'audio':
            metrics['separator_kind'] = args.separator
            metrics['separated_audio'] = args.separated_audio
            from .audio import diarize, normalize, prepare_clips, transcribe
            import soundfile as sf
            normal = args.output / 'audio_16k.wav'
            t = time.monotonic()
            normalize(args.input, normal, args.channel)
            metrics['audio_seconds'] = sf.info(normal).duration
            metrics['stages_seconds']['normalize'] = time.monotonic()-t
            t = time.monotonic()
            print('Streaming diarization...', flush=True)
            probs = diarize(normal, args.output, args.device, args.threshold)
            metrics['stages_seconds']['diarization'] = time.monotonic()-t
            t = time.monotonic()
            print('Preparing speaker clips / separating overlaps...', flush=True)
            clips = prepare_clips(normal, probs, args.output, root / 'models',
                                  args.device, args.threshold, args.max_seconds, args.separator, args.separator_python,
                                  args.sepformer_model, args.separated_audio)
            dump(args.output / 'clips.json', clips)
            metrics['stages_seconds']['separation'] = time.monotonic()-t
            t = time.monotonic()
            print('Korean ASR...', flush=True)
            transcribe(clips, args.output, args.device, args.asr, root / 'models', menu)
            metrics['asr_backend'] = args.asr
            metrics['stages_seconds']['asr'] = time.monotonic()-t
            source = args.output / 'utterances.jsonl'
        else:
            source = args.input
        if not getattr(args, 'skip_orders', False):
            t = time.monotonic()
            print('Interpreting order changes...', flush=True)
            book_type = OrderBook
            if args.order_backend == 'qwen':
                from .qwen_context import QwenContextInterpreter
                from .context_orders import ContextOrderBook
                interpreter = QwenContextInterpreter(args.llm, args.device)
                book_type = ContextOrderBook
            else:
                interpreter = LocalLLM(args.llm, args.device, args.int4)
            metrics['order_backend'] = args.order_backend
            metrics['llm'] = args.llm
            book = book_type(menu, interpreter, args.output)
            count = 0
            with source.open(encoding='utf-8-sig') as f:
                for line in f:
                    if not line.strip():
                        continue
                    turn = json.loads(line)
                    event = book.consume(turn)
                    count += 1
                    if event:
                        print(json.dumps(event['decision'], ensure_ascii=False), flush=True)
            book.save()
            metrics.update(utterance_count=count, review_count=book.review_count)
            metrics['stages_seconds']['orders'] = time.monotonic()-t
        metrics['status'] = 'complete'
    except Exception as exc:
        metrics.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        metrics['total_seconds'] = time.monotonic()-started
        if args.device == 'cuda':
            metrics['peak_gpu_allocated_mib'] = torch.cuda.max_memory_allocated()/1024**2
            child = args.output / 'separation/separator_metrics.json'
            if child.exists():
                metrics['separator'] = json.loads(child.read_text())
                metrics['peak_gpu_allocated_mib'] = max(metrics['peak_gpu_allocated_mib'],
                    metrics['separator']['peak_gpu_allocated_mib'])
        if metrics.get('audio_seconds'):
            metrics['real_time_factor'] = metrics['total_seconds']/metrics['audio_seconds']
        dump(args.output / 'metrics.json', metrics)
    print(f'Results: {args.output.resolve()}', flush=True)


if __name__ == '__main__':
    main()
