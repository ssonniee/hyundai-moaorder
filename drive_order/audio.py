"""Disk-backed streaming diarization, two-source separation, Korean ASR."""
import gc
import json
import math
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .orders import dump


def release(model):
    import torch
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def normalize(source, target, channel=0):
    if channel < 0:
        raise ValueError('channel must be nonnegative')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source),
        '-af', f'pan=mono|c0=c{channel}', '-ar', '16000', '-c:a', 'pcm_s16le', str(target)], check=True)
    if sf.info(target).duration <= 0:
        raise ValueError('Empty recording')


def runs(mask, gap=0, minimum=1):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    spans = list(zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)))
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(int(a), int(b)) for a, b in merged if b - a >= minimum]


def diarize(path, output, device='cuda', threshold=.5):
    import torch
    from transformers import AutoModelForAudioFrameClassification, AutoProcessor
    model_id = 'nvidia/Nemotron-3-Diarization'
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModelForAudioFrameClassification.from_pretrained(model_id, local_files_only=True).to(device).eval()
    processor.set_streaming_mode('low_latency')
    info = sf.info(path)
    # The feature extractor scores complete 10 ms frames; the sub-frame tail has no logit.
    nframes = max(1, info.frames // 160)
    probs = np.lib.format.open_memmap(output / 'speaker_probs.npy', mode='w+', dtype='float32', shape=(nframes, 8))
    probs[:] = 0
    cache, mel_idx, cursor, first = None, 0, 0, True
    with sf.SoundFile(path) as audio, torch.inference_mode():
        while True:
            start = 0 if first else processor.audio_chunk_start(mel_idx)
            count = processor.num_samples_first_audio_chunk if first else processor.num_samples_per_audio_chunk
            audio.seek(start)
            chunk = audio.read(count, dtype='float32')
            last = start + count >= info.frames
            inputs = processor(chunk, sampling_rate=16000, is_streaming=True,
                is_first_audio_chunk=first, is_last_audio_chunk=last).to(device, dtype=model.dtype)
            prediction = model(**inputs, speaker_cache=cache)
            cache = prediction.speaker_cache
            p = prediction.logits[0].sigmoid().float().cpu().numpy()
            size = min(len(p), nframes - cursor)
            probs[cursor:cursor+size] = p[:size]
            cursor += size
            if last:
                break
            mel_idx += processor.num_mel_frames_per_step
            first = False
    if cursor != nframes:
        raise RuntimeError(f'Diarization coverage mismatch: {cursor}/{nframes}')
    probs.flush()
    segments = []
    for speaker in range(8):
        for a, b in runs(probs[:, speaker] >= threshold, gap=15, minimum=15):
            segments.append({'speaker': f'speaker_{speaker}', 'start': a/100,
                             'end': min(b/100, info.duration)})
    segments.sort(key=lambda x: (x['start'], x['speaker']))
    dump(output / 'diarization.json', segments)
    with (output / 'diarization.rttm').open('w') as f:
        for s in segments:
            f.write(f"SPEAKER recording 1 {s['start']:.3f} {s['end']-s['start']:.3f} <NA> <NA> {s['speaker']} <NA> <NA>\n")
    del model, prediction, inputs, cache
    release(None)
    return probs


def assign_sources(sources, activity, minimum_anchor=20, margin=.20):
    """Map arbitrary separator channels using exclusive speech anchors, never channel index."""
    n = min(len(activity), sources.shape[1] // 80)
    energy = np.mean(sources[:, :n*80].reshape(2, n, 80)**2, axis=-1)
    votes = []
    for s in range(2):
        anchor = activity[:n, s] & ~activity[:n, 1-s]
        if anchor.sum() < minimum_anchor:
            continue
        e = energy[:, anchor].sum(axis=1)
        if e.sum() <= 1e-10:
            continue
        dominance = (e[0]-e[1]) / e.sum()
        if abs(dominance) < margin:
            continue
        votes.append((0 if dominance > 0 else 1) if s == 0 else (1 if dominance > 0 else 0))
    if not votes or len(set(votes)) != 1:
        return None
    return [votes[0], 1-votes[0]]


def splice_overlap(mix, source, activity, speaker):
    """Preserve original single-speaker audio; use separation only while others speak."""
    from scipy.ndimage import uniform_filter1d
    source = resample_poly(source, 2, 1)[:len(mix)]
    if len(source) < len(mix):
        source = np.pad(source, (0, len(mix)-len(source)))
    other = np.delete(activity, speaker, axis=1).any(axis=1)
    solo = activity[:, speaker] & ~other
    solo_samples = np.repeat(solo, 160)[:len(mix)]
    # Match source gain/phase to original solo anchors before joining waveforms.
    if solo_samples.sum() >= 3200:
        s, m = source[solo_samples], mix[solo_samples]
        gain = float(np.dot(s, m) / (np.dot(s, s) + 1e-9))
    else:
        gain = float(np.sqrt(np.mean(mix**2) / (np.mean(source**2) + 1e-9)))
    weights = np.repeat(other, 160).astype('float32')[:len(mix)]
    weights = uniform_filter1d(weights, size=320, mode='nearest')
    return mix*(1-weights) + source*gain*weights


def prepare_clips(path, probs, output, model_dir, device='cuda', threshold=.5, max_seconds=20,
                  separator_kind='sepformer', separator_python='/home/ssonniee/anaconda3/envs/diarizen/bin/python',
                  sepformer_model='sepformer-wsj02mix'):
    import torch
    from .vendor.conv_tasnet import conv_tasnet_base
    if not 2 <= max_seconds <= 30:
        raise ValueError('max_seconds must be in [2, 30]')
    active = probs >= threshold
    # Drop isolated very short detections and bridge short intra-speaker gaps.
    cleaned = np.zeros_like(active)
    for s in range(active.shape[1]):
        for a, b in runs(active[:, s], gap=15, minimum=15):
            cleaned[a:b, s] = True
    active = cleaned
    # Keep nearby solo anchors in the separator window. Cutting exactly at an overlap
    # can remove the evidence needed to recover / identify the quieter speaker.
    regions = runs(active.any(axis=1), gap=300, minimum=20)
    separated_files = {}
    if separator_kind == 'sepformer':
        jobs = []
        work = output / 'separation'
        work.mkdir()
        with sf.SoundFile(path) as audio:
            for region_start, region_end in regions:
                cap = int(max_seconds*100)
                for begin in range(region_start, region_end, cap):
                    end = min(begin+cap, region_end)
                    a, b = max(0, begin-30), min(len(active), end+30)
                    mask = active[a:b]
                    if (mask.sum(axis=1) > 1).any() and mask.any(axis=0).sum() == 2:
                        audio.seek(a*160)
                        wave = audio.read((b-a)*160, dtype='float32')
                        source, target = work / f'{begin}.wav', work / f'{begin}.npy'
                        sf.write(source, resample_poly(wave, 1, 2), 8000, subtype='FLOAT')
                        jobs.append({'input': str(source.resolve()), 'output': str(target.resolve())})
                        separated_files[begin] = target
        if jobs:
            jobfile = work / 'jobs.json'
            dump(jobfile, jobs)
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            subprocess.run([separator_python, str(Path(__file__).resolve().parents[1] / 'scripts/separate.py'),
                '--jobs', str(jobfile.resolve()), '--model-dir', str((model_dir / sepformer_model).resolve()),
                '--device', device, '--model', sepformer_model], env=env, check=True)
    separator = None
    clips, index = [], 0
    clip_dir = output / 'clips'
    clip_dir.mkdir()
    duration = sf.info(path).duration
    with sf.SoundFile(path) as audio:
        for region_start, region_end in regions:
            cap = int(max_seconds*100)
            for begin in range(region_start, region_end, cap):
                end = min(begin+cap, region_end)
                forced_cut = region_end-region_start > cap
                # Context stays inside a bounded window; clipping never duplicates output audio.
                a, b = max(0, begin-30), min(len(active), end+30)
                mask = active[a:b]
                speakers = np.flatnonzero(mask.any(axis=0))
                overlap = bool((mask.sum(axis=1) > 1).any())
                audio.seek(a*160)
                mix = audio.read((b-a)*160, dtype='float32')
                mapping, separated = None, None
                if overlap and len(speakers) == 2 and separator_kind != 'none':
                    if separator_kind == 'sepformer':
                        separated = np.load(separated_files[begin])
                    else:
                        if separator is None:
                            separator = conv_tasnet_base(num_sources=2)
                            separator.load_state_dict(torch.load(model_dir / 'conv_tasnet_base_libri2mix.pt', map_location='cpu', weights_only=True))
                            separator.to(device).eval()
                        low = resample_poly(mix, 1, 2).astype('float32')
                        with torch.inference_mode():
                            separated = separator(torch.from_numpy(low)[None, None].to(device))[0].cpu().numpy()
                    mapping = assign_sources(separated, mask[:, speakers])
                for local, speaker in enumerate(speakers):
                    # Per-speaker speech segments remain attributable in chronological order.
                    spans = runs(active[begin:end, speaker], gap=35, minimum=20)
                    # A quieter overlap speaker may disappear from diarization in the middle
                    # of a word. Decode their separated track across its speech envelope.
                    decode_spans = [(spans[0][0], spans[-1][1])] if spans and separated is not None and mapping is not None else spans
                    for x, y in decode_spans:
                        start, stop = begin+x, begin+y
                        needs_review = forced_cut or (overlap and mapping is None)
                        if separated is not None and mapping is not None:
                            track = splice_overlap(mix, separated[mapping[local]], mask, speaker)
                            wave = track[(start-a)*160:(stop-a)*160]
                            method = separator_kind + '_overlap_splice'
                        else:
                            wave = mix[(start-a)*160:(stop-a)*160]
                            method = 'unresolved_overlap' if overlap else 'single_speaker'
                        if len(wave) < 3200:
                            continue
                        index += 1
                        clip = clip_dir / f'{index:06d}.wav'
                        peak = max(1., float(np.max(np.abs(wave))))
                        sf.write(clip, wave/peak, 16000)
                        clips.append({'id': f'u{index:06d}', 'speaker': f'speaker_{speaker}',
                            'start': start/100, 'end': min(stop/100, duration),
                            'speech_spans': [[(begin+u)/100, min((begin+v)/100, duration)] for u,v in spans if u < y and v > x],
                            'overlap': overlap, 'method': method, 'needs_review': needs_review,
                            'review_reason': 'chunk_boundary' if forced_cut else ('speaker_assignment' if needs_review else None),
                            'audio_path': str(clip.resolve())})
    del separator
    release(None)
    return sorted(clips, key=lambda x: (x['start'], x['speaker']))


def transcribe(clips, output, device='cuda', backend='nemo', model_dir=None, menu=None):
    import torch
    if backend == 'nemo':
        import nemo.collections.asr as nemo_asr
        model = nemo_asr.models.ASRModel.from_pretrained('nvidia/nemotron-3.5-asr-streaming-0.6b', map_location=device)
    else:
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
        processor = AutoProcessor.from_pretrained(model_dir / 'whisper-large-v3-turbo')
        model = AutoModelForSpeechSeq2Seq.from_pretrained(model_dir / 'whisper-large-v3-turbo',
            dtype=torch.float16 if device == 'cuda' else torch.float32).to(device)
        hint = ', '.join(item['name'] for item in (menu or {}).get('items', []))[:500]
        prompt_ids = processor.get_prompt_ids('식당 메뉴: ' + hint, return_tensors='pt').to(device) if hint else None
    model.eval()
    speaker_dir = output / 'speakers'
    speaker_dir.mkdir(exist_ok=True)
    # Single-clip batches bound VRAM independently of recording duration.
    with (output / 'utterances.jsonl').open('w', encoding='utf-8') as f:
        for clip in clips:
            with torch.inference_mode():
                if backend == 'nemo':
                    predictions = model.transcribe([clip['audio_path']], batch_size=1,
                        target_lang='ko-KR', num_workers=0, verbose=False)
                    if isinstance(predictions, tuple):
                        predictions = predictions[0]
                    text = predictions[0] if isinstance(predictions[0], str) else predictions[0].text
                else:
                    wave, _ = sf.read(clip['audio_path'], dtype='float32')
                    inputs = processor(wave, sampling_rate=16000, return_tensors='pt',
                        return_attention_mask=True).to(device, dtype=model.dtype)
                    ids = model.generate(**inputs, language='korean', task='transcribe',
                        max_new_tokens=256, do_sample=False, prompt_ids=prompt_ids)
                    text = processor.batch_decode(ids, skip_special_tokens=True)[0]
                    del inputs, ids
            turn = dict(clip, text=re.sub(r'<[a-z]{2}-[A-Z]{2}>', '', text).strip(), asr_backend=backend)
            if not turn['text']:
                turn.update(needs_review=True, review_reason='empty_asr_on_detected_speech')
            f.write(json.dumps(turn, ensure_ascii=False) + '\n')
            f.flush()
            with (speaker_dir / (clip['speaker'] + '.jsonl')).open('a', encoding='utf-8') as speaker_file:
                speaker_file.write(json.dumps(turn, ensure_ascii=False) + '\n')
            print(f"{turn['speaker']} {turn['start']:.2f}–{turn['end']:.2f}: {turn['text']}", flush=True)
    del model
    release(None)
