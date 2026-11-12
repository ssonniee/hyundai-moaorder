"""UI contract test with clearly synthetic utterances; no speech accuracy claim."""
import asyncio
import json
from pathlib import Path
import tempfile

from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from drive_order.orders import OrderBook, dump

ROOT = Path(__file__).resolve().parents[1]


async def main():
    participant_count = 2
    async def fixture_runner(state, recording, output):
        output.mkdir()
        turns = [dict(id='1', speaker='speaker_0', start=0., end=1., text='아메리카노 하나'),
                 dict(id='2', speaker='speaker_1', start=1., end=2., text='카페라떼 하나'),
                 dict(id='3', speaker='speaker_0', start=2., end=3., text='아메리카노 말고 바닐라라떼 하나')]
        def item(id):
            return dict(op='set', menu_id=id, quantity=1, options=[])
        operations = [[item('menu_000')], [item('menu_001')],
                      [dict(op='remove', menu_id='menu_000'), item('menu_002')]]
        for index in range(2, participant_count):
            turns.append(dict(id=str(index + 2), speaker=f'speaker_{index}',
                              start=float(index + 1), end=float(index + 2), text='아메리카노 하나'))
            operations.append([item('menu_000')])
        ops = iter(operations)
        book = OrderBook(state['menu'], lambda p: dict(action='update', operations=next(ops), reason='UI 검증용 변경'), output)
        with (output/'utterances.jsonl').open('w') as handle:
            for turn in turns:
                handle.write(json.dumps(turn, ensure_ascii=False)+'\n')
                book.consume(turn)
        dump(output/'metrics.json', {'audio_seconds': 3, 'test_fixture': True})

    with tempfile.TemporaryDirectory() as data:
        app = create_app(data, fixture_runner)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', 8766).start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
                context = await browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True,
                                                    has_touch=True, permissions=['microphone'])
                await context.route('https://tile.openstreetmap.org/**', lambda route: route.abort())
                await context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                page = await context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                await page.goto('http://127.0.0.1:8766/#key='+app['demo'].access_key)
                await page.wait_for_selector('#health.ready')
                await page.locator('#map').click(position={'x': 150, 'y': 100})
                await page.locator('[data-menu="cafe"]').click()
                await page.locator('#startBtn').click()
                await page.wait_for_function("document.getElementById('recordBadge').textContent.includes('녹음 중')")
                await page.wait_for_timeout(1200)
                await page.locator('#stopBtn').click()
                await page.wait_for_selector('#results', state='visible')
                cards = page.locator('.order-card')
                assert await cards.count() == 2
                first = await cards.nth(0).inner_text()
                assert '바닐라라떼' in first and '아메리카노' not in first
                assert '카페라떼' in await cards.nth(1).inner_text()
                assert await page.locator('.guide-card').count() == 0
                assert '작은 팁' not in await page.locator('body').inner_text()
                assert await page.locator('.right-column #orderSummary').is_visible()
                assert await page.locator('#summaryCount').inner_text() == '2명'
                assert await cards.locator('input').count() == 0
                icons = await cards.locator('svg').evaluate_all('(els) => els.map(e => e.outerHTML)')
                assert len(set(icons)) == 2
                assert await cards.nth(0).get_attribute('aria-label') == '참여자 1의 최종 주문'
                assert await page.locator('#transcript .person-avatar').count() == 3
                assert await page.locator('#transcript svg').nth(0).evaluate('(e) => e.outerHTML') == icons[0]
                assert await page.locator('#transcript svg').nth(2).evaluate('(e) => e.outerHTML') == icons[0]
                await page.locator('[data-view="changes"]').click()
                assert await page.locator('#changes .turn').count() == 3
                async with page.expect_download() as download:
                    await page.locator('#downloadLink').click()
                downloaded = await download.value
                payload = json.loads(Path(await downloaded.path()).read_text())
                assert payload['orders']['speakers']['speaker_0'][0]['name'] == '바닐라라떼'
                await page.reload()
                await page.wait_for_selector('#results', state='visible')
                assert await cards.locator('svg').evaluate_all('(els) => els.map(e => e.outerHTML)') == icons
                for width in (320, 390, 1440):
                    await page.set_viewport_size({'width': width, 'height': 900})
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                    assert await page.locator('#orderSummary').is_visible()
                await page.locator('#orderSummary').screenshot(path=str(ROOT/'demo/test-artifacts/final-orders.png'))
                participant_count = 8
                await page.locator('#newBtn').click()
                assert await cards.count() == 0
                await page.locator('#startBtn').click()
                await page.wait_for_function("document.getElementById('recordBadge').textContent.includes('녹음 중')")
                await page.wait_for_timeout(1200)
                await page.locator('#stopBtn').click()
                await page.wait_for_selector('#results', state='visible')
                assert await cards.count() == 8
                assert await page.locator('#summaryCount').inner_text() == '8명'
                icons = await cards.locator('svg').evaluate_all('(els) => els.map(e => e.outerHTML)')
                assert len(set(icons)) == 8
                await page.set_viewport_size({'width': 320, 'height': 900})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await page.locator('#orderSummary').screenshot(path=str(ROOT/'demo/test-artifacts/final-orders-mobile.png'))
                assert not errors, errors
                await browser.close()
                print('PASS: synthetic order replacement, 2/8 distinct participant icons, matching transcript, reload, history, download, reset, 320/390/1440px layouts')
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
