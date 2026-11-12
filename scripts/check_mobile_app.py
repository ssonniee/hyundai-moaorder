"""PWA lifecycle and access tests, using synthetic audio (no ASR accuracy claim)."""
import asyncio
import json
from pathlib import Path
import plistlib
import tempfile
import xml.etree.ElementTree as ET

from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from drive_order.orders import dump
from check_recording_meter import TONE

ROOT = Path(__file__).resolve().parents[1]


async def main():
    async def fixture(state, recording, output):
        assert recording.stat().st_size > 0
        output.mkdir()
        dump(output/'orders.json', {'status': 'draft', 'speakers': {}})
        dump(output/'metrics.json', {'audio_seconds': state['duration']})
        (output/'utterances.jsonl').write_text('')
        (output/'order_events.jsonl').write_text('')

    with tempfile.TemporaryDirectory() as data:
        app = create_app(data, fixture, device='cpu', separator='none')
        server = web.AppRunner(app)
        await server.setup()
        await web.TCPSite(server, '127.0.0.1', 8768).start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context(viewport={'width': 393, 'height': 852}, is_mobile=True, has_touch=True)
                await context.add_init_script(TONE)
                await context.route('https://tile.openstreetmap.org/**', lambda r: r.abort())
                await context.route('https://fonts.googleapis.com/**', lambda r: r.abort())
                page = await context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                await page.goto('http://127.0.0.1:8768/')
                await page.wait_for_selector('#pairForm', state='visible')
                await page.locator('#pairKey').fill('invalid-key')
                await page.locator('#pairForm button').click()
                await page.wait_for_function("document.getElementById('pairError').textContent.length > 0")
                await page.locator('#pairKey').fill('http://127.0.0.1:8768/#key='+app['demo'].access_key)
                await page.locator('#pairForm button').click()
                await page.wait_for_selector('#health.ready')
                assert '#' not in page.url
                config = await page.evaluate("fetch('/api/config').then(r=>r.json())")
                assert config['processing'] == {'location': 'server', 'device': 'cpu', 'asr': 'whisper', 'separator': 'none'}
                manifest = await page.evaluate("fetch('/static/manifest.webmanifest').then(r=>r.json())")
                assert manifest['display'] == 'standalone' and manifest['start_url'] == '/'
                assert app['demo'].access_key not in json.dumps(manifest)
                await page.evaluate('navigator.serviceWorker.ready')
                await page.reload()
                await page.wait_for_function('navigator.serviceWorker.controller !== null')
                await page.wait_for_selector('#health.ready')
                await page.locator('[data-store="starbucks_wangsimni_exit9"]').click()
                await page.locator('#startBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.wait_for_timeout(1200)
                await page.evaluate("Object.defineProperty(document, 'hidden', {configurable:true, value:true}); document.dispatchEvent(new Event('visibilitychange'))")
                await page.wait_for_selector('#results', state='visible')
                assert await page.locator('#summaryCount').inner_text() == '0명'
                entries = await page.evaluate('''async () => {
                    const cachesList = await caches.keys();
                    return (await Promise.all(cachesList.map(async k => (await (await caches.open(k)).keys()).map(r=>r.url)))).flat();
                }''')
                assert entries and all('/api/' not in url and 'key=' not in url for url in entries)
                await context.set_offline(True)
                await page.reload()
                await page.wait_for_selector('#connectionPanel', state='visible')
                assert '서버 연결' in await page.locator('#connectionTitle').inner_text()
                assert await page.locator('#pairForm').is_hidden()
                assert await page.locator('#startBtn').is_disabled()
                await context.set_offline(False)
                await page.locator('#reconnectBtn').click()
                await page.wait_for_selector('#health.ready')
                await page.wait_for_selector('#results', state='visible')
                assert not errors, errors
                await browser.close()
        finally:
            await server.cleanup()

    # Structural checks only. Swift compilation/signing still requires Xcode on macOS.
    project = plistlib.loads((ROOT/'ios/MoaOrder.xcodeproj/project.pbxproj').read_bytes())
    objects = project['objects']
    assert project['rootObject'] in objects
    for obj in objects.values():
        if obj['isa'] == 'PBXFileReference' and obj.get('sourceTree') == '<group>':
            assert (ROOT/'ios/MoaOrder'/obj['path']).exists(), obj['path']
    privacy = plistlib.loads((ROOT/'ios/MoaOrder/Info.plist').read_bytes())
    assert privacy['NSMicrophoneUsageDescription'] and not privacy.get('NSAppTransportSecurity', {}).get('NSAllowsArbitraryLoads')
    ET.parse(ROOT/'ios/MoaOrder.xcodeproj/xcshareddata/xcschemes/MoaOrder.xcscheme')
    print('PASS: pairing, standalone manifest, shell cache, no cached audio/API/key, offline/reconnect, background recording stop, CPU config; iOS project structure only (not a Swift build)')


if __name__ == '__main__':
    asyncio.run(main())
