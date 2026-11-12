"""SpeechBrain worker; isolated interpreter avoids NeMo/Torchaudio version conflicts."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import soundfile as sf
import torch
from speechbrain.inference.separation import SepformerSeparation

p = argparse.ArgumentParser()
p.add_argument('--jobs', type=Path, required=True)
p.add_argument('--model-dir', type=Path, required=True)
p.add_argument('--device', default='cuda')
p.add_argument('--model', choices=['sepformer-wsj02mix', 'sepformer-whamr'], default='sepformer-wsj02mix')
args = p.parse_args()
torch.set_num_threads(4)
if args.device == 'cuda':
    torch.cuda.reset_peak_memory_stats()
t = time.monotonic()
model = SepformerSeparation.from_hparams(source='speechbrain/' + args.model,
    savedir=str(args.model_dir), run_opts={'device': 'cuda:0' if args.device == 'cuda' else args.device})
with torch.inference_mode():
    for job in json.loads(args.jobs.read_text()):
        wave, sr = sf.read(job['input'], dtype='float32')
        if sr != 8000 or wave.ndim != 1:
            raise ValueError('Separator input must be 8 kHz mono')
        result = model.separate_batch(torch.from_numpy(wave)[None])[0].cpu().numpy().T
        np.save(job['output'], result)
metrics = {'model': 'speechbrain/' + args.model, 'seconds': time.monotonic()-t,
    'peak_gpu_allocated_mib': torch.cuda.max_memory_allocated()/1024**2 if args.device == 'cuda' else 0}
args.jobs.with_name('separator_metrics.json').write_text(json.dumps(metrics, indent=2))
