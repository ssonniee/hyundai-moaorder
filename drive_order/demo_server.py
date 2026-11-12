"""Recording demo behind loopback or an authenticated HTTPS tunnel."""
import argparse
import asyncio
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import ssl
import sys
import time
import uuid

from aiohttp import web

from .orders import dump, validate_menu
from .trip import validate_trip

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'demo/static'
MAX_CHUNK = 8 * 1024 * 1024
MAX_SESSION = 250 * 1024 * 1024
MIME = {'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mp4': 'm4a', 'audio/wav': 'wav'}


class Demo:
    def __init__(self, data, runner=None, device='cuda', asr='whisper', separator='sepformer'):
        self.device, self.asr, self.separator = device, asr, separator
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.stores = {s['id']: s for s in json.loads((ROOT/'demo/stores.json').read_text())}
        key_file = self.data / '.access-key'
        if not key_file.exists():
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(secrets.token_urlsafe(32))
        self.access_key = key_file.read_text().strip()
        self.sessions, self.locks, self.tasks = {}, {}, set()
        self.gpu = asyncio.Semaphore(1)
        self.runner = runner or self.run_pipeline
        for file in self.data.glob('*/session.json'):
            state = json.loads(file.read_text())
            if state['status'] in ('queued', 'processing'):
                state.update(status='failed', phase='분석 중 서버가 종료되었습니다. 다시 분석할 수 있습니다.')
                dump(file, state)
            self.sessions[state['id']] = state
            self.locks[state['id']] = asyncio.Lock()

    def get(self, id):
        if not re.fullmatch('[a-f0-9]{32}', id) or id not in self.sessions:
            raise web.HTTPNotFound(text='녹음을 찾을 수 없습니다.')
        return self.sessions[id]

    def save(self, state):
        state['updated_at'] = time.time()
        dump(self.data / state['id'] / 'session.json', state)

    async def config(self, request):
        return web.json_response({'ready': all((ROOT/'models'/m/'config.json').exists() for m in
            ['whisper-large-v3-turbo', 'Qwen3-4B-Instruct-2507']),
            'max_minutes': 60, 'max_chunk_bytes': MAX_CHUNK,
            'processing': {'location': 'server', 'device': self.device, 'asr': self.asr, 'separator': self.separator},
            'stores': list(self.stores.values()),
            'tile_url': os.environ.get('DRIVE_ORDER_TILES', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'),
            'tile_attribution': os.environ.get('DRIVE_ORDER_TILE_ATTRIBUTION', '© OpenStreetMap contributors')})

    async def pair(self, request):
        body = await request.json()
        if not isinstance(body.get('key'), str) or not secrets.compare_digest(body['key'], self.access_key):
            raise web.HTTPUnauthorized(text='접속 키가 올바르지 않습니다. 전달받은 전체 링크로 열어 주세요.')
        response = web.json_response({'paired': True})
        response.set_cookie('moa_access', self.access_key, httponly=True, samesite='Strict',
                            secure=request.host.split(':')[0] not in ('127.0.0.1', 'localhost'), max_age=86400)
        return response

    async def access_link(self, request):
        # Authenticated, same-origin POST only; never put the key in public HTML/manifest.
        # The browser builds the URL so SSH-forwarded ports are preserved.
        return web.json_response({'key': self.access_key})

    async def create(self, request):
        body = await request.json()
        catalog_id = body.get('catalog_store_id')
        store = None
        if catalog_id is not None:
            if not isinstance(catalog_id, str) or catalog_id not in self.stores:
                raise ValueError('등록된 매장을 선택해 주세요.')
            store = self.stores[catalog_id]
            destination = {k: store[k] for k in ('name', 'latitude', 'longitude')}
            lines = copy.deepcopy(store['items'])
        else:
            destination, lines = body['destination'], body['menu']
        if not isinstance(destination, dict) or not isinstance(lines, list) or not 1 <= len(lines) <= 100:
            raise ValueError('메뉴를 1~100개 입력해 주세요.')
        name = destination.get('name', '').strip()
        if not name or len(name) > 120:
            raise ValueError('목적지 이름은 1~120자여야 합니다.')
        id = uuid.uuid4().hex
        items = []
        for i, entry in enumerate(lines):
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not 1 <= len(entry['name'].strip()) <= 80:
                raise ValueError('메뉴 이름을 확인해 주세요.')
            aliases = entry.get('aliases', [])
            if not isinstance(aliases, list) or len(aliases) > 12 or any(not isinstance(v, str) or not v.strip() or len(v) > 80 for v in aliases):
                raise ValueError('메뉴 별칭을 확인해 주세요.')
            items.append({'id': f'menu_{i:03d}', 'name': entry['name'].strip(), 'aliases': aliases})
        if len({x['name'] for x in items}) != len(items):
            raise ValueError('메뉴 이름이 중복되었습니다.')
        store_id = catalog_id or 'place_' + hashlib.sha256(f"{name}:{destination['latitude']}:{destination['longitude']}".encode()).hexdigest()[:16]
        menu = {'store_id': store_id, 'name': name, 'source': store['menu_source'] if store else 'user_entered_demo_menu',
                'version': store['menu_version'] if store else id, 'items': items}
        validate_menu(menu)
        destination = {k: destination.get(k) for k in ('latitude', 'longitude')}
        destination.update(name=name, store_id=store_id, poi_id=None)
        if store:
            destination['address'] = store['address']
        trip = {'session_id': id, 'destination': destination}
        validate_trip(trip, menu)
        mime = str(body.get('mime', '')).split(';')[0]
        if mime not in MIME:
            raise ValueError('지원하지 않는 녹음 형식입니다.')
        folder = self.data / id
        folder.mkdir()
        (folder/'chunks').mkdir()
        dump(folder/'menu.json', menu)
        dump(folder/'trip.json', trip)
        state = {'id': id, 'destination': destination, 'menu': menu, 'mime': mime,
                 'status': 'recording', 'phase': '대화를 녹음하고 있습니다', 'created_at': time.time(),
                 'next_chunk': 0, 'bytes': 0, 'duration': 0, 'attempt': 0, 'speaker_names': {},
                 'catalog_store_id': catalog_id}
        self.sessions[id], self.locks[id] = state, asyncio.Lock()
        self.save(state)
        return web.json_response(state, status=201)

    async def chunk(self, request):
        state = self.get(request.match_info['id'])
        try:
            index = int(request.match_info['index'])
        except ValueError:
            raise ValueError('잘못된 녹음 조각 번호입니다.')
        if not 0 <= index <= 100000:
            raise ValueError('잘못된 녹음 조각 번호입니다.')
        audio = await request.read()
        if not audio or len(audio) > MAX_CHUNK:
            raise ValueError('녹음 조각 크기를 확인해 주세요.')
        async with self.locks[state['id']]:
            path = self.data/state['id']/'chunks'/f'{index:06d}.chunk'
            if state['status'] != 'recording':
                raise web.HTTPConflict(text='종료된 녹음입니다.')
            if index < state['next_chunk']:
                if path.read_bytes() != audio:
                    raise web.HTTPConflict(text='이미 저장한 녹음 조각과 내용이 다릅니다.')
                return web.json_response({'next_chunk': state['next_chunk']})
            if index != state['next_chunk']:
                raise web.HTTPConflict(text='녹음 조각의 순서가 맞지 않습니다.')
            if state['bytes'] + len(audio) > MAX_SESSION:
                raise ValueError('최대 녹음 용량(250MB)을 초과했습니다.')
            tmp = path.with_suffix('.tmp')
            tmp.write_bytes(audio)
            tmp.replace(path)
            state['next_chunk'] += 1
            state['bytes'] += len(audio)
            self.save(state)
        return web.json_response({'next_chunk': state['next_chunk']})

    async def finish(self, request):
        state = self.get(request.match_info['id'])
        body = await request.json()
        async with self.locks[state['id']]:
            if state['status'] in ('queued', 'processing', 'complete'):
                return web.json_response(state)
            if state['status'] not in ('recording', 'failed'):
                raise web.HTTPConflict(text='분석할 수 없는 녹음 상태입니다.')
            if type(body.get('chunks')) is not int or body['chunks'] != state['next_chunk'] or not state['bytes']:
                raise web.HTTPConflict(text='음성 업로드가 아직 완료되지 않았습니다.')
            duration = body.get('duration', state['duration'])
            if type(duration) not in (float, int) or not math.isfinite(duration) or not 0 <= duration <= 3620:
                raise ValueError('녹음 길이를 확인해 주세요. 최대 60분입니다.')
            state.update(status='queued', phase='분석을 기다리고 있습니다', duration=duration)
            self.save(state)
            task = asyncio.create_task(self.process(state))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        return web.json_response(state)

    async def process(self, state):
        async with self.gpu:
            if state['status'] != 'queued':
                return
            state.update(status='processing', phase='녹음 파일을 준비하고 있습니다', attempt=state['attempt']+1)
            self.save(state)
            folder = self.data/state['id']
            output = folder/f"analysis_{state['attempt']:03d}"
            state['output'] = output.name
            recording = folder/('recording.' + MIME[state['mime']])
            try:
                def assemble():
                    with recording.open('wb') as target:
                        for index in range(state['next_chunk']):
                            target.write((folder/'chunks'/f'{index:06d}.chunk').read_bytes())
                await asyncio.to_thread(assemble)
                await asyncio.wait_for(self.runner(state, recording, output), timeout=7200)
                if not (output/'orders.json').is_file():
                    raise RuntimeError('주문 결과 파일이 만들어지지 않았습니다.')
                state.update(status='complete', phase='주문 정리가 끝났습니다')
            except asyncio.CancelledError:
                state.update(status='failed', phase='서버가 중지되었습니다. 다시 분석해 주세요.')
                raise
            except Exception as exc:
                state.update(status='failed', phase='분석에 실패했습니다. 저장된 음성으로 다시 시도할 수 있습니다.', error=str(exc)[:500])
            finally:
                self.save(state)

    async def run_pipeline(self, state, recording, output):
        folder = self.data/state['id']
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join([str(ROOT/'.deps'), str(ROOT.parent/'Nemotron-ASR/Speech'), str(ROOT)])
        proc = await asyncio.create_subprocess_exec(sys.executable, '-u', '-m', 'drive_order', 'audio',
            '--input', str(recording), '--menu', str(folder/'menu.json'), '--trip', str(folder/'trip.json'),
            '--device', self.device, '--asr', self.asr, '--separator', self.separator,
            '--output', str(output), cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True, limit=1024*1024)
        phases = {'Streaming diarization': '누가 언제 말했는지 찾고 있습니다',
                  'Preparing speaker clips': '겹친 목소리를 나누고 있습니다',
                  'Korean ASR': '화자별 대화를 글로 옮기고 있습니다',
                  'Interpreting order changes': '메뉴 선택과 변경 내용을 정리하고 있습니다'}
        try:
            with (folder/f"analysis_{state['attempt']:03d}.log").open('wb') as log:
                async for line in proc.stdout:
                    log.write(line)
                    for prefix, label in phases.items():
                        if line.startswith(prefix.encode()):
                            state['phase'] = label
                            self.save(state)
            if await proc.wait():
                raise RuntimeError('음성 처리 엔진 오류. 해당 녹음 폴더의 분석 로그를 확인해 주세요.')
        finally:
            if proc.returncode is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except asyncio.TimeoutError:
                    os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()

    async def list_sessions(self, request):
        records = sorted(self.sessions.values(), key=lambda s: s['created_at'], reverse=True)[:30]
        return web.json_response([s for s in records if s['status'] != 'cancelled'])

    async def status(self, request):
        state = self.get(request.match_info['id'])
        return web.json_response(state)

    def result(self, state):
        if state['status'] != 'complete':
            raise web.HTTPConflict(text='아직 분석이 완료되지 않았습니다.')
        output = self.data/state['id']/state['output']
        def lines(name):
            return [json.loads(line) for line in (output/name).read_text().splitlines() if line.strip()]
        return {'session': state, 'orders': json.loads((output/'orders.json').read_text()),
                'utterances': lines('utterances.jsonl'), 'events': lines('order_events.jsonl'),
                'metrics': json.loads((output/'metrics.json').read_text())}

    async def results(self, request):
        state = self.get(request.match_info['id'])
        headers = {'Content-Disposition': 'attachment; filename="order-result.json"'} if request.query.get('download') else {}
        return web.json_response(self.result(state), headers=headers,
                                 dumps=lambda v: json.dumps(v, ensure_ascii=False, indent=2))

    async def audio(self, request):
        state = self.get(request.match_info['id'])
        path = self.data/state['id']/('recording.'+MIME[state['mime']])
        if not path.exists():
            raise web.HTTPNotFound(text='녹음 종료 후 재생할 수 있습니다.')
        return web.FileResponse(path, headers={'Content-Type': state['mime']})

    async def rename(self, request):
        state = self.get(request.match_info['id'])
        body = await request.json()
        names = body.get('names')
        if not isinstance(names, dict) or len(names) > 8 or any(
                not re.fullmatch('speaker_[0-7]', k) or not isinstance(v, str) or len(v) > 40 for k,v in names.items()):
            raise ValueError('화자 이름을 확인해 주세요.')
        state['speaker_names'] = names
        self.save(state)
        return web.json_response(state)

    async def cancel(self, request):
        state = self.get(request.match_info['id'])
        async with self.locks[state['id']]:
            if state['status'] not in ('recording', 'queued'):
                raise web.HTTPConflict(text='이미 분석을 시작한 녹음입니다.')
            state.update(status='cancelled', phase='녹음 취소됨')
            self.save(state)
        return web.json_response(state)

    async def cleanup(self, app):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@web.middleware
async def guard(request, handler):
    try:
        host = request.host.split(':')[0].lower()
        local = host in ('127.0.0.1', 'localhost')
        if not local and host not in request.app['allowed_hosts'] and not re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com', host):
            raise web.HTTPForbidden(text='허용되지 않은 접속 주소입니다.')
        if request.method not in ('GET', 'HEAD'):
            origin = request.headers.get('Origin')
            expected = f'{request.scheme if local else "https"}://{request.host}'
            if request.headers.get('X-Drive-Order') != '1' or (origin and origin != expected):
                raise web.HTTPForbidden(text='잘못된 요청 출처입니다.')
        if request.path.startswith('/api/') and request.path != '/api/pair':
            supplied = request.cookies.get('moa_access', '')
            bearer = request.headers.get('Authorization', '')
            if bearer.startswith('Bearer '):
                supplied = bearer[7:]
            if not secrets.compare_digest(supplied, request.app['demo'].access_key):
                raise web.HTTPUnauthorized(text='접속 키가 포함된 링크로 열어 주세요.')
        response = await handler(request)
    except (ValueError, KeyError, TypeError) as exc:
        response = web.json_response({'error': str(exc)}, status=400)
    except web.HTTPException as exc:
        response = web.json_response({'error': exc.text}, status=exc.status)
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


def create_app(data=None, runner=None, *, device='cuda', asr='whisper', separator='sepformer', allowed_hosts=()):
    demo = Demo(data or ROOT/'demo/sessions', runner, device, asr, separator)
    app = web.Application(middlewares=[guard], client_max_size=MAX_CHUNK)
    app['demo'] = demo
    app['allowed_hosts'] = frozenset(h.lower() for h in allowed_hosts)
    async def index(request):
        return web.FileResponse(STATIC/'index.html', headers={'Cache-Control': 'no-cache'})
    async def service_worker(request):
        return web.FileResponse(STATIC/'sw.js', headers={'Cache-Control': 'no-cache'})
    app.add_routes([web.get('/', index), web.get('/api/config', demo.config), web.post('/api/pair', demo.pair),
        web.post('/api/access-link', demo.access_link),
        web.get('/api/sessions', demo.list_sessions), web.post('/api/sessions', demo.create),
        web.get('/api/sessions/{id}', demo.status), web.post('/api/sessions/{id}/chunks/{index}', demo.chunk),
        web.post('/api/sessions/{id}/finish', demo.finish), web.post('/api/sessions/{id}/cancel', demo.cancel),
        web.get('/api/sessions/{id}/result', demo.results), web.get('/api/sessions/{id}/audio', demo.audio),
        web.post('/api/sessions/{id}/names', demo.rename), web.get('/sw.js', service_worker)])
    app.router.add_static('/static/', STATIC, show_index=False)
    app.on_cleanup.append(demo.cleanup)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cuda')
    parser.add_argument('--asr', choices=['whisper', 'nemo'], default='whisper')
    parser.add_argument('--separator', choices=['sepformer', 'convtasnet', 'none'], default='sepformer')
    parser.add_argument('--data', type=Path)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--public-host', help='Explicit phone-facing hostname or IPv4 address, without scheme/port')
    parser.add_argument('--tls-cert', type=Path)
    parser.add_argument('--tls-key', type=Path)
    parser.add_argument('--phone-port', type=int, help='Also serve the same app over HTTPS on --public-host; keep loopback HTTP')
    args = parser.parse_args()
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error('--tls-cert and --tls-key must be provided together')
    if args.public_host and not re.fullmatch(r'[a-zA-Z0-9.-]+', args.public_host):
        parser.error('--public-host must be a hostname or IPv4 address, without scheme/port')
    if args.host not in ('127.0.0.1', 'localhost') and not (args.tls_cert and args.public_host):
        parser.error('Phone-facing binding requires TLS and --public-host')
    if args.phone_port and (not args.tls_cert or not args.public_host or args.host not in ('127.0.0.1', 'localhost') or args.phone_port == args.port):
        parser.error('--phone-port requires TLS, --public-host, loopback --host, and a different port')
    tls = None
    if args.tls_cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.tls_cert, args.tls_key)
    app = create_app(args.data, device=args.device, asr=args.asr, separator=args.separator,
                     allowed_hosts=[args.public_host] if args.public_host else [])
    print('\n모아오더 직접 녹음 데모', flush=True)
    print('이 PC의 Chrome 또는 Edge에서 아래 전체 주소를 열어 주세요:', flush=True)
    primary_scheme = 'https' if tls and not args.phone_port else 'http'
    primary_host = 'localhost' if args.phone_port else (args.public_host or 'localhost')
    print(f"{primary_scheme}://{primary_host}:{args.port}/#key={app['demo'].access_key}\n", flush=True)
    if args.phone_port:
        print(f"휴대폰: https://{args.public_host}:{args.phone_port}/#key={app['demo'].access_key}\n", flush=True)
    print('지도에서 목적지 선택 → 메뉴 확인 → 녹음 시작 → 녹음 마치고 주문 정리', flush=True)
    print('서버를 종료하려면 Ctrl+C를 누르세요.\n', flush=True)
    if args.phone_port:
        async def serve_phone():
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            try:
                await web.TCPSite(runner, args.host, args.port).start()
                await web.TCPSite(runner, args.public_host, args.phone_port, ssl_context=tls).start()
                await asyncio.Event().wait()
            finally:
                await runner.cleanup()
        try:
            asyncio.run(serve_phone())
        except KeyboardInterrupt:
            pass
    else:
        web.run_app(app, host=args.host, port=args.port, access_log=None, ssl_context=tls)
