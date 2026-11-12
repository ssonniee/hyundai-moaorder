"""Create a private LAN test CA/certificate. Does not install trust or expose a server."""
import argparse
import ipaddress
import os
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--ip', required=True, type=ipaddress.IPv4Address)
    p.add_argument('--output', type=Path, default=Path('demo/tls'))
    args = p.parse_args()
    if not args.ip.is_private or args.ip.is_loopback or args.ip.is_unspecified:
        p.error('Use the PC private LAN IPv4 address')
    folder = args.output.resolve()
    if folder.exists():
        p.error('Output already exists; reuse its certificate or choose a new directory')
    folder.mkdir(parents=True, mode=0o700)
    os.chmod(folder, 0o700)
    def run(*argv):
        subprocess.run(['openssl', *argv], cwd=folder, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    old_mask = os.umask(0o077)
    try:
        run('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '30',
            '-keyout', 'ca-key.pem', '-out', 'ca.pem', '-subj', '/CN=Moa Order Local Test CA',
            '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        run('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'server-key.pem', '-out', 'server.csr',
            '-subj', f'/CN={args.ip}')
        (folder/'server.ext').write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:{args.ip},DNS:localhost,IP:127.0.0.1\n')
        run('x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem', '-CAkey', 'ca-key.pem', '-CAcreateserial',
            '-out', 'server.pem', '-days', '30', '-sha256', '-extfile', 'server.ext')
        run('x509', '-in', 'ca.pem', '-outform', 'DER', '-out', 'MoaOrder-Local-CA.cer')
    finally:
        os.umask(old_mask)
    print(f'Phone trust certificate: {folder / "MoaOrder-Local-CA.cer"}')
    print('Only transfer the .cer file to the phone. Keep *-key.pem files on this PC.')
    print('No system trust settings or network listeners were changed.')


if __name__ == '__main__':
    main()
