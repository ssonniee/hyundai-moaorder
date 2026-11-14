"""Nemotron 3.5 Transcribe client and speaker-attributed output adapter."""
import base64
import json
import math
import re
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from .orders import dump


DEFAULT_MODEL = 'nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-NVFP4'


def transcription_prompt(menu=None, max_speakers=4):
    if not 1 <= max_speakers <= 8:
        raise ValueError('max_speakers must be in [1, 8]')
    tags = ' '.join(f'<spk:{i}>' for i in range(max_speakers))
    prompt = (
        'Transcribe this Korean audio with punctuation. Include all spoken words and verbal fillers. '
        'Write numbers in their standard written form. '
        f'Put speaker tags {tags} on the transcription.'
    )
    terms = [item.get('name', '').strip() for item in (menu or {}).get('items', [])]
    terms = [term for term in terms if term]
    if terms:
        prompt += ' Context terms (use only when spoken): ' + ', '.join(terms)[:1000] + '.'
    return prompt


def _endpoint(base_url):
    base = base_url.rstrip('/')
    return base + '/chat/completions' if base.endswith('/v1') else base + '/v1/chat/completions'


def request_transcription(audio_path, menu=None, *, base_url='http://127.0.0.1:8000/v1',
                          model=DEFAULT_MODEL, api_key='EMPTY', max_speakers=4,
                          max_tokens=4096, timeout=7200):
    audio = base64.b64encode(Path(audio_path).read_bytes()).decode('ascii')
    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': transcription_prompt(menu, max_speakers)},
            {'type': 'audio_url', 'audio_url': {'url': f'data:audio/wav;base64,{audio}'}},
        ]}],
        'temperature': 0,
        'top_p': 1.0,
        'max_tokens': max_tokens,
        'chat_template_kwargs': {'enable_thinking': False},
        'skip_special_tokens': False,
        'spaces_between_special_tokens': False,
        'seed': 0,
        'mm_processor_kwargs': {'capture_ctc_timestamps': True},
    }
    request = urllib.request.Request(
        _endpoint(base_url),
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:2000]
        raise RuntimeError(f'Nemotron server returned HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Cannot reach Nemotron server at {base_url}: {exc.reason}') from exc
    choices = result.get('choices') or []
    if not choices:
        raise RuntimeError('Nemotron response has no choices')
    if choices[0].get('finish_reason') == 'length':
        raise RuntimeError('Nemotron transcript reached max_tokens; increase --nemotron-max-tokens')
    return result


def _speaker_number(value):
    match = re.search(r'(\d+)', str(value))
    if not match or not 0 <= int(match.group(1)) <= 7:
        raise ValueError(f'Invalid Nemotron speaker label: {value!r}')
    return int(match.group(1))


def _clean_text(tokens):
    text = ' '.join(str(token).strip() for token in tokens if str(token).strip()).strip()
    text = re.sub(r'\s+([,.!?…:;%)\]])', r'\1', text)
    text = re.sub(r'([(\[])\s+', r'\1', text)
    return re.sub(r'\s+', ' ', text).strip()


def _valid_time(value, field):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'Invalid {field}: {value!r}')
    return value


def _normalize_diarization(alignment):
    segments = []
    for item in alignment.get('diarization') or []:
        start, end = _valid_time(item['start'], 'start'), _valid_time(item['end'], 'end')
        if end < start:
            raise ValueError('Diarization segment ends before it starts')
        segments.append({'speaker': _speaker_number(item['speaker']), 'start': start, 'end': end})
    return sorted(segments, key=lambda item: (item['start'], item['speaker']))


def _speaker_mapping(alignment):
    mapping = {}
    for tag, diarization_speaker in (alignment.get('speaker_tag_to_diarization_speaker') or {}).items():
        if diarization_speaker is not None:
            mapping[_speaker_number(tag)] = _speaker_number(diarization_speaker)
    return mapping


def _overlaps_other(start, end, transcript_speaker, diarization, mapping):
    own = mapping.get(transcript_speaker)
    active = [segment['speaker'] for segment in diarization
              if segment['start'] < end and segment['end'] > start]
    if own is not None:
        return any(speaker != own for speaker in active)
    return len(set(active)) > 1


def turns_from_response(response, *, turn_gap=1.2, audio_path=None):
    """Convert CTC word timestamps to the application's utterance format."""
    alignment = response.get('ctc_timestamps')
    if not isinstance(alignment, dict):
        raise RuntimeError('Nemotron response has no ctc_timestamps; start vLLM with timestamp middleware')
    if alignment.get('error') is not None:
        raise RuntimeError(f"Nemotron CTC alignment failed: {alignment['error']}")
    diarization = _normalize_diarization(alignment)
    mapping = _speaker_mapping(alignment)
    by_speaker = defaultdict(list)
    for item in alignment.get('words') or []:
        word = str(item.get('word', '')).strip()
        if not word:
            continue
        start, end = _valid_time(item['start'], 'start'), _valid_time(item['end'], 'end')
        if end < start:
            raise ValueError('Word ends before it starts')
        by_speaker[_speaker_number(item.get('speaker', 0))].append(
            {'word': word, 'start': start, 'end': end})
    transcript = (((response.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()
    if transcript and not by_speaker:
        raise RuntimeError('Nemotron returned text but no aligned words')
    grouped = []
    for speaker, words in by_speaker.items():
        words.sort(key=lambda item: (item['start'], item['end']))
        current = []
        for word in words:
            if current and word['start'] - current[-1]['end'] > turn_gap:
                grouped.append((speaker, current))
                current = []
            current.append(word)
        if current:
            grouped.append((speaker, current))
    grouped.sort(key=lambda item: (item[1][0]['start'], item[0]))
    turns = []
    for index, (speaker, words) in enumerate(grouped, 1):
        start, end = words[0]['start'], words[-1]['end']
        diarization_speaker = mapping.get(speaker)
        speech_spans = [[segment['start'], segment['end']] for segment in diarization
                        if diarization_speaker is not None and segment['speaker'] == diarization_speaker
                        and segment['start'] < end and segment['end'] > start]
        turns.append({
            'id': f'u{index:06d}',
            'speaker': f'speaker_{speaker}',
            'start': start,
            'end': end,
            'speech_spans': speech_spans or [[start, end]],
            'overlap': _overlaps_other(start, end, speaker, diarization, mapping),
            'method': 'nemotron35_transcribe',
            'needs_review': False,
            'review_reason': None,
            'audio_path': str(Path(audio_path).resolve()) if audio_path else None,
            'text': _clean_text(word['word'] for word in words),
            'asr_backend': 'nemotron35',
        })
    return turns, diarization


def write_transcription(audio_path, output, menu=None, **request_options):
    output = Path(output)
    response = request_transcription(audio_path, menu, **request_options)
    dump(output / 'nemotron35_response.json', response)
    turns, diarization = turns_from_response(response, audio_path=audio_path)
    diarization_rows = [dict(segment, speaker=f"speaker_{segment['speaker']}") for segment in diarization]
    dump(output / 'diarization.json', diarization_rows)
    with (output / 'diarization.rttm').open('w', encoding='utf-8') as handle:
        for segment in diarization_rows:
            handle.write(
                f"SPEAKER recording 1 {segment['start']:.3f} "
                f"{segment['end']-segment['start']:.3f} <NA> <NA> {segment['speaker']} <NA> <NA>\n"
            )
    dump(output / 'clips.json', turns)
    speaker_dir = output / 'speakers'
    speaker_dir.mkdir(exist_ok=True)
    with (output / 'utterances.jsonl').open('w', encoding='utf-8') as handle:
        for turn in turns:
            line = json.dumps(turn, ensure_ascii=False) + '\n'
            handle.write(line)
            with (speaker_dir / f"{turn['speaker']}.jsonl").open('a', encoding='utf-8') as speaker_file:
                speaker_file.write(line)
            print(f"{turn['speaker']} {turn['start']:.2f}–{turn['end']:.2f}: {turn['text']}", flush=True)
    return turns
