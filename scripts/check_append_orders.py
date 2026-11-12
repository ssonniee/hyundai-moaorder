"""Real browser recording + upload additions; deterministic model fixture, no speech accuracy claim."""
import asyncio
import json
import tempfile
from pathlib import Path
from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from drive_order.orders import OrderBook, dump
from check_recording_controls import wav
from check_recording_meter import TONE
ROOT = Path(__file__).resolve().parents[1]

async def main():
    fail_next = False
    async def fixture(state, recording, output):
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise RuntimeError('synthetic retry')
        segments = app['demo'].recordings(state)
        operations = iter([
            [dict(op='set', menu_id='menu_000',quantity=1,options=[])],
            [dict(op='remove',menu_id='menu_000'),dict(op='set',menu_id='menu_001',quantity=1,options=[])],
            [dict(op='add',menu_id='menu_001',quantity=2,options=[])]])
        book = OrderBook(state['menu'],lambda _:dict(action='update',operations=next(operations),reason='검증용 주문 변경'),output)
        turns=[]
        for i,part in enumerate(segments):
            turn=dict(id=str(i),speaker='speaker_0',start=part['start'],end=part['end'],text=['윈터 스카치 바닐라 라떼 하나','윈터 스카치 바닐라 라떼 말고 토피넛라떼 하나','토피넛라떼 두 잔 더'][i])
            turns.append(turn);book.consume(turn)
        (output/'utterances.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in turns))
        dump(output/'metrics.json',dict(audio_seconds=state['duration'],test_fixture=True))
    with tempfile.TemporaryDirectory() as data:
        app=create_app(data,fixture);server=web.AppRunner(app);await server.setup()
        await web.TCPSite(server,'127.0.0.1',8778).start()
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch()
                context=await browser.new_context(viewport=dict(width=390,height=844))
                await context.add_init_script(TONE)
                await context.route('https://tile.openstreetmap.org/**',lambda r:r.abort())
                page=await context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto('http://127.0.0.1:8778/#key='+app['demo'].access_key)
                await page.wait_for_selector('#health.ready')
                await page.locator('#storeSearch').fill('스타벅스')
                await page.locator('[data-store]').first.click()
                async def record():
                    await page.locator('#startBtn').click()
                    await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                    await page.wait_for_timeout(1200)
                    for width in (320,390,1440):
                        await page.set_viewport_size(dict(width=width,height=900))
                        boxes = [await page.locator('#'+id).bounding_box() for id in ('pauseBtn','stopBtn','cancelBtn')]
                        assert max(b['y'] for b in boxes)-min(b['y'] for b in boxes)<1
                        assert await page.locator('.recorder-actions .action-icon svg').count()==3
                        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    await page.set_viewport_size(dict(width=390,height=844))
                    await page.locator('.recorder-actions').screenshot(path=str(ROOT/'demo/test-artifacts/compact-recording-controls.png'))
                    await page.locator('#stopBtn').click()
                await record()
                await page.wait_for_selector('#savedResult',state='visible')
                first=await page.evaluate('current.id')
                original=await page.locator('#savedOrders').inner_text()
                assert '윈터 스카치' in original
                await page.wait_for_selector('.history-add')
                assert await page.locator('.history-row .pin-symbol svg').count()==1
                assert await page.locator('.history-row .tag').count()==0
                assert '→' not in await page.locator('.history-row').inner_text()
                entry = await page.locator('.history-entry').bounding_box()
                extra = await page.locator('.history-add').bounding_box()
                main = await page.locator('.history-row').bounding_box()
                assert main['x']+main['width']<=extra['x']+1
                assert extra['y']+extra['height']<=entry['y']+entry['height']
                await page.locator('.history-section').screenshot(path=str(ROOT/'demo/test-artifacts/compact-order-history.png'))
                await page.locator('.history-add').click()
                await page.wait_for_selector('#appendNotice',state='visible')
                assert await page.locator('#storeSearch').is_disabled()
                assert '추가 녹음' in await page.locator('#startBtn').inner_text()
                await record()
                await page.wait_for_selector('#savedResult',state='visible')
                second=await page.evaluate('current.id')
                assert second!=first
                saved=await page.locator('#savedOrders').inner_text()
                assert '토피넛' in saved and '윈터 스카치' not in saved
                assert await page.locator('.recording-part').count()==2
                await page.wait_for_function("document.querySelectorAll('.history-row').length===1 && document.querySelector('.history-row').textContent.includes('녹음 2개')")
                # Header addition opens the same order; failed analysis keeps old result accessible.
                await page.locator('#nextOrderBtn').click()
                await page.wait_for_selector('#appendNotice',state='visible')
                fail_next=True
                await page.locator('#audioFile').set_input_files(dict(name='extra.wav',mimeType='audio/wav',buffer=wav(1)))
                await page.wait_for_function("phase==='failed'")
                await page.reload()
                await page.wait_for_function("phase==='failed'")
                await page.locator('#returnOrderBtn').click()
                await page.wait_for_selector('#savedResult',state='visible')
                assert await page.locator('#savedOrders').inner_text()==saved
                await page.wait_for_function("document.querySelector('.history-add')?.textContent.includes('이어보기')")
                await page.locator('.history-add').click()
                await page.wait_for_function("phase==='failed'")
                await page.locator('#retryBtn').click()
                await page.wait_for_selector('#savedResult',state='visible')
                assert '3개' in await page.locator('#savedOrders').inner_text()
                assert await page.locator('.recording-part').count()==3
                await page.locator('[data-view="transcript"]').click()
                assert await page.locator('#transcript').is_visible()
                assert await page.locator('#transcript .turn').count()==3
                await page.locator('[data-view="changes"]').click()
                assert await page.locator('#changes .turn').count()==3
                async with page.expect_download() as download:
                    await page.locator('#downloadLink').click()
                result=json.loads(Path(await (await download.value).path()).read_text())
                assert len(result['recordings'])==3
                assert result['orders']['speakers']['speaker_0'][0]['quantity']==3
                await page.locator('#newBtn').click()
                await page.locator('.history-row').click()
                await page.wait_for_selector('#savedResult',state='visible')
                assert '3개' in await page.locator('#savedOrders').inner_text()
                await page.reload()
                await page.wait_for_selector('#savedResult',state='visible')
                assert await page.locator('.recording-part').count()==3
                # Discard only the new recording, keeping the combined saved result.
                await page.locator('#appendOrderBtn').click()
                await page.wait_for_selector('#appendNotice',state='visible')
                await page.locator('#startBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.locator('#pauseBtn').click()
                page.once('dialog',lambda d:d.accept())
                await page.locator('#cancelBtn').click()
                await page.wait_for_selector('#savedResult',state='visible')
                assert await page.locator('.recording-part').count()==3
                assert '3개' in await page.locator('#savedOrders').inner_text()
                for theme in ('light','dark'):
                    await page.locator(f'[data-set-theme="{theme}"]').click()
                    for width in (320,390,1440):
                        await page.set_viewport_size(dict(width=width,height=900))
                        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(theme,width)
                    await page.set_viewport_size(dict(width=390,height=844))
                    await page.locator('#results').screenshot(path=str(ROOT/f'demo/test-artifacts/combined-order-{theme}.png'))
                assert not errors,errors
                await browser.close()
        finally:
            await server.cleanup()
    print('PASS: additional microphone recording + uploaded audio, combined saved result/history/download, failure recovery, reload, both themes and responsive widths')

asyncio.run(main())
