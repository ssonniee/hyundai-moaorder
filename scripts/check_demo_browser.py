"""Mobile viewport + actual MediaRecorder/GPU integration smoke test.

Chromium's virtual microphone supplies test tones, not speech or a user dataset.
Run with PYTHONPATH=.demo-deps:. PLAYWRIGHT_BROWSERS_PATH=demo/test-artifacts/browsers.
"""
import asyncio
import json
from pathlib import Path
import time

from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app

ROOT = Path(__file__).resolve().parents[1]


async def main():
    artifacts = ROOT/'demo/test-artifacts'
    data = artifacts/f'browser-{int(time.time())}'
    app = create_app(data)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 8766)
    await site.start()
    errors = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
            context = await browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True,
                                                permissions=['microphone'])
            # Avoid automated fetching/panning of community map tiles during QA.
            await context.route('https://tile.openstreetmap.org/**', lambda route: route.fulfill(
                content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e8ece5"/></svg>'))
            await context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto('http://127.0.0.1:8766/#key='+app['demo'].access_key)
            await page.wait_for_selector('#health.ready')
            for store in app['demo'].stores.values():
                await page.locator('#storeSearch').fill(store['name'])
                await page.locator('[data-store="'+store['id']+'"]').click()
                assert await page.locator('#placeName').input_value() == store['name']
                assert await page.locator('#menuChips span').count() == len(store['items'])
                assert await page.locator('#menuChips span').all_text_contents() == [m['name'] for m in store['items']]
            await page.reload()
            await page.wait_for_selector('#health.ready')
            await page.wait_for_function("document.getElementById('placeName').value === '백소정 한양대점'")
            # The numbered map marker must select the same catalogue as the cards.
            await page.locator('.leaflet-marker-icon[title="맥도날드 한양대"]').click()
            assert await page.locator('#menuChips span').count() == 5
            await page.locator('#storeSearch').fill('스타벅스')
            await page.locator('[data-store="starbucks_wangsimni_exit9"]').click()
            assert not await page.locator('#startBtn').is_disabled()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile horizontal overflow'
            await page.screenshot(path=str(artifacts/'mobile-before.png'), full_page=True)
            await page.locator('#startBtn').click()
            await page.wait_for_function("document.getElementById('recordBadge').textContent.includes('녹음 중')")
            assert await page.locator('#storeSearch').is_disabled()
            await page.wait_for_timeout(6500)
            await page.screenshot(path=str(artifacts/'mobile-recording.png'), full_page=True)
            await page.locator('#stopBtn').click()
            id = await page.evaluate("localStorage.getItem('moa-active')")
            assert app['demo'].sessions[id]['catalog_store_id'] == 'starbucks_wangsimni_exit9'
            assert len(app['demo'].sessions[id]['menu']['items']) == 8
            print('Recording uploaded; real GPU pipeline running, session '+id, flush=True)
            last = None
            deadline = time.monotonic()+600
            while time.monotonic() < deadline:
                state = app['demo'].sessions[id]
                if state['phase'] != last:
                    last = state['phase']
                    print(last, flush=True)
                if state['status'] in ('complete', 'failed'):
                    break
                await asyncio.sleep(2)
            assert state['status'] == 'complete', json.dumps(state, ensure_ascii=False)
            await page.wait_for_selector('#results', state='visible', timeout=10000)
            await page.screenshot(path=str(artifacts/'mobile-result.png'), full_page=True)
            assert not errors, errors
            recording = data/id/'recording.webm'
            assert recording.read_bytes()[:4] == b'\x1aE\xdf\xa3', 'not a real WebM recording'
            await page.reload()
            await page.wait_for_selector('#results', state='visible')
            assert '스타벅스 왕십리역9번출구점' in await page.locator('#resultSubtitle').inner_text()
            await page.locator('#newBtn').click()
            assert not await page.locator('#storeSearch').is_disabled()
            assert await page.locator('#results').is_hidden()
            report = {'status': 'passed', 'virtual_microphone': True, 'human_speech_accuracy_tested': False,
                      'recording_bytes': recording.stat().st_size, 'duration': state['duration'],
                      'session_folder': str(data/id), 'page_errors': errors}
            (artifacts/'browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)
            await browser.close()
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
