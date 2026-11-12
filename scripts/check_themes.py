"""Theme persistence and switching during real MediaRecorder capture; synthetic audio."""
import asyncio
import tempfile
from pathlib import Path
from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from drive_order.orders import dump
from check_recording_meter import TONE, waveform_ink
ROOT = Path(__file__).resolve().parents[1]

async def main():
    async def fixture(state, recording, output):
        output.mkdir()
        dump(output/'orders.json', {'status':'draft','speakers':{'speaker_0':[{'name':'토피넛라떼','quantity':1,'options':[]}]}})
        dump(output/'metrics.json', {'audio_seconds':state['duration']})
        (output/'utterances.jsonl').write_text('')
        (output/'order_events.jsonl').write_text('')
    with tempfile.TemporaryDirectory() as data:
        app=create_app(data, fixture)
        server=web.AppRunner(app);await server.setup()
        await web.TCPSite(server,'127.0.0.1',8773).start()
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch()
                ctx=await browser.new_context(viewport={'width':1440,'height':1050}, color_scheme='light')
                await ctx.add_init_script(TONE)
                await ctx.route('https://tile.openstreetmap.org/**',lambda r:r.abort())
                page=await ctx.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto('http://127.0.0.1:8773/#key='+app['demo'].access_key)
                await page.wait_for_selector('#health.ready')
                assert await page.locator('html').get_attribute('data-theme')=='light'
                await page.emulate_media(color_scheme='dark')
                await page.wait_for_selector('html[data-theme="dark"]')
                for theme in ['light','dark']:
                    await page.locator(f'[data-set-theme="{theme}"]').click()
                    assert await page.locator(f'[data-set-theme="{theme}"]').get_attribute('aria-pressed')=='true'
                    await page.reload();await page.wait_for_selector('#health.ready')
                    assert await page.locator('html').get_attribute('data-theme')==theme
                    await page.locator('#storeSearch').fill('스타벅스')
                    await page.locator('[data-store]').click()
                    for width in [320,390,768,1440]:
                        await page.set_viewport_size({'width':width,'height':1050})
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(theme,width)
                        assert await page.locator('[data-set-theme="dark"]').is_visible()
                    await page.evaluate('window.scrollTo(0,0)')
                    await page.screenshot(path=str(ROOT/f'demo/test-artifacts/theme-{theme}-desktop.png'),full_page=True)
                    await page.set_viewport_size({'width':390,'height':844})
                    await page.screenshot(path=str(ROOT/f'demo/test-artifacts/theme-{theme}-mobile.png'),full_page=True)
                await page.emulate_media(color_scheme='light')
                assert await page.locator('html').get_attribute('data-theme')=='dark', 'explicit preference overrides system'
                await page.locator('#startBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.evaluate('window.originalRecordingStream=stream')
                for theme in ['light','dark']:
                    await page.locator(f'[data-set-theme="{theme}"]').click()
                    await page.wait_for_timeout(1200)
                    assert await page.evaluate("phase === 'recording' && stream === originalRecordingStream && stream.getAudioTracks()[0].readyState === 'live'")
                    assert await waveform_ink(page)>100
                await page.locator('#stopBtn').click()
                await page.wait_for_selector('#results',state='visible')
                for theme in ['light','dark']:
                    await page.locator(f'[data-set-theme="{theme}"]').click()
                    assert await page.locator('.order-card .person-orders').inner_text()=='토피넛라떼\n1개'
                    await page.locator('#orderSummary').screenshot(path=str(ROOT/f'demo/test-artifacts/theme-{theme}-orders.png'))
                assert not errors,errors
                # A blocked preference store must not stop rendering or switching.
                isolated=await browser.new_context(color_scheme='dark')
                await isolated.add_init_script("Storage.prototype.getItem = function(){throw new DOMException('blocked','SecurityError')};Storage.prototype.setItem = function(){throw new DOMException('blocked','SecurityError')}")
                other=await isolated.new_page()
                await other.goto('http://127.0.0.1:8773/')
                assert await other.locator('html').get_attribute('data-theme')=='dark'
                await other.locator('[data-set-theme="light"]').click()
                assert await other.locator('html').get_attribute('data-theme')=='light'
                await browser.close()
                print('PASS: light/dark layouts at 320/390/768/1440, system default, explicit persistence, blocked preference storage, uninterrupted recording/waveform, order results')
        finally:
            await server.cleanup()
if __name__=='__main__':asyncio.run(main())
