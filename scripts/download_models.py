"""Download the three default models needed by the web server."""
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(__file__).resolve().parents[1]
snapshot_download('Qwen/Qwen3-4B-Instruct-2507', local_dir=root / 'models/Qwen3-4B-Instruct-2507',
    allow_patterns=['*.json', '*.safetensors', '*.txt', '*.jinja', 'LICENSE', 'README.md'])
snapshot_download('nvidia/Nemotron-3-Diarization',
    allow_patterns=['*.json', '*.safetensors'])
snapshot_download('openai/whisper-large-v3-turbo', local_dir=root / 'models/whisper-large-v3-turbo',
    allow_patterns=['*.json', '*.safetensors', '*.txt', '*.tiktoken', 'README.md'])
# The SpeechBrain worker fetches SepFormer weights on first use.
