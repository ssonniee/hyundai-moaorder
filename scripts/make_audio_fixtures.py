"""Use labelled human speech to create reproducible overlap / long-file probes.

Ground truth labels are for evaluation only; inference never reads them.
"""
import json
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT.parent / 'Nemotron-ASR/audio'
OUT = ROOT / 'results/fixtures'
OUT.mkdir(parents=True, exist_ok=True)


def seconds(value):
    minute, sec = value.split(':')
    return int(minute)*60+float(sec)


def human(stem):
    label = json.loads((AUDIO / 'labels' / (stem+'.json')).read_text(encoding='utf-8-sig'))
    utterance = label['video']['interactions'][0]['human_event']['utterances'][0]
    wave, sr = sf.read(AUDIO / (stem+'.wav'), dtype='float32')
    assert sr == 16000 and wave.ndim == 1
    a, b = seconds(utterance['utterance_start']), seconds(utterance['utterance_end'])
    return wave[round(a*sr):round(b*sr)], utterance['utterance_cap']


a, ta = human('RS0002_05_R04_1104_sound')
b, tb = human('RS0004_01_R04_1107_sound')
placements = [(0.5, a, ta, 'source_a'), (2.0, b, tb, 'source_b')]
length = int((2+len(b)/16000+1)*16000)
mix = np.zeros(length, dtype='float32')
truth = []
for start, wave, text, speaker in placements:
    offset = round(start*16000)
    mix[offset:offset+len(wave)] += wave*.7
    truth.append(dict(start=start, end=start+len(wave)/16000, speaker=speaker, text=text))
mix /= max(1., abs(mix).max())
sf.write(OUT / 'overlap.wav', mix, 16000)
(OUT / 'overlap_reference.json').write_text(json.dumps(truth, ensure_ascii=False, indent=2))
# A second, deliberately different-voice probe. Retain the first difficult pair as a regression case.
b2, tb2 = human('RS0096_02_R04_0831_sound')
import librosa
b2, trim = librosa.effects.trim(b2, top_db=25, frame_length=512, hop_length=160)
mix2 = np.zeros(round((2+len(b2)/16000+1)*16000), dtype='float32')
mix2[8000:8000+len(a)] += a*.7
mix2[32000:32000+len(b2)] += b2*.7
mix2 /= max(1., abs(mix2).max())
sf.write(OUT / 'overlap_distinct.wav', mix2, 16000)
(OUT / 'overlap_distinct_reference.json').write_text(json.dumps([
    dict(start=.5, end=.5+len(a)/16000, speaker='source_a', text=ta),
    dict(start=2., end=2+len(b2)/16000, speaker='source_b', text=tb2)], ensure_ascii=False, indent=2))
short_overlap = np.zeros(round((2.9+len(b2)/16000+1)*16000), dtype='float32')
short_overlap[8000:8000+len(a)] += a*.7
offset = round(2.9*16000)
short_overlap[offset:offset+len(b2)] += b2*.7
short_overlap /= max(1., abs(short_overlap).max())
sf.write(OUT / 'overlap_short.wav', short_overlap, 16000)
(OUT / 'overlap_short_reference.json').write_text(json.dumps([
    dict(start=.5, end=.5+len(a)/16000, speaker='source_a', text=ta),
    dict(start=2.9, end=2.9+len(b2)/16000, speaker='source_b', text=tb2)], ensure_ascii=False, indent=2))
base, sr = sf.read(AUDIO / 'RS0002_05_R04_1104_sound.wav', dtype='float32')
with sf.SoundFile(OUT / 'long_90s.wav', mode='w', samplerate=sr, channels=1, subtype='PCM_16') as f:
    for _ in range(7):
        f.write(base)
        f.write(np.zeros(sr//2, dtype='float32'))
print(OUT)
