"""Generate the demo's keyed URL and QR locally; never starts a public tunnel."""
import argparse
import os
from pathlib import Path
import re
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://localhost:8765')
args = parser.parse_args()
parsed = urlparse(args.base_url)
if not ((parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')) or
        (parsed.scheme == 'https' and re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com', parsed.netloc))):
    parser.error('Use the local server or its approved HTTPS quick-tunnel address.')
key_file = ROOT/'demo/sessions/.access-key'
if not key_file.is_file():
    parser.error('Start demo.sh first.')
url = args.base_url.rstrip('/')+'/#key='+key_file.read_text().strip()
out = ROOT/'demo/mobile-access.txt'
with out.open('w') as handle:
    os.chmod(out, 0o600)
    handle.write(url+'\n')
try:
    import qrcode
    qr = ROOT/'demo/mobile-access.png'
    qrcode.make(url).save(qr)
    os.chmod(qr, 0o600)
except ImportError:
    pass
print(url)
