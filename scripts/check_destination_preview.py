"""Destination discovery and local microphone preview; synthetic audio only."""
import asyncio
import tempfile
from pathlib import Path
from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from check_recording_meter import TONE, waveform_ink
ROOT = Path(__file__).resolve().parents[1]

async def main():
    with tempfile.TemporaryDirectory() as data:
        app = create_app(data)
        server = web.AppRunner(app)
        await server.setup()
        await web.TCPSite(server, '127.0.0.1', 8772).start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context(viewport={'width':390,'height':844})
                await context.add_init_script(TONE + '\nwindow.goodMic = navigator.mediaDevices.getUserMedia;')
                await context.route('https://tile.openstreetmap.org/**', lambda r:r.abort())
                page = await context.new_page()
                errors=[]
                page.on('pageerror', lambda e:errors.append(str(e)))
                await page.goto('http://127.0.0.1:8772/#key='+app['demo'].access_key)
                await page.wait_for_selector('#health.ready')
                assert await page.locator('#searchResults').is_hidden()
                assert await page.locator('[data-store]').count() == 0
                await page.locator('#storeSearch').fill('빅맥')
                assert await page.locator('[data-store]').count() == 1
                await page.locator('#storeSearch').press('ArrowDown')
                await page.keyboard.press('Enter')
                assert await page.locator('#placeName').input_value() == '맥도날드 한양대'
                assert await page.locator('#searchResults').is_hidden()
                assert await page.locator('#menuChips span').count() == 5
                assert await page.locator('#menuTitle').inner_text() == '“맥도날드 한양대”의 메뉴'
                assert await page.locator('.destination .pin-symbol svg').count() == 1
                await page.locator('#storeSearch').fill('없는매장')
                assert await page.locator('[data-store]').count() == 0
                assert '검색 결과가 없어요' in await page.locator('#searchStatus').inner_text()
                await page.locator('#storeSearch').press('Escape')
                assert await page.locator('#searchResults').is_hidden()
                await page.locator('.leaflet-control-zoom-out').click()
                await page.locator('.leaflet-marker-icon[title="백소정 한양대점"]').click()
                assert await page.locator('#placeName').input_value() == '백소정 한양대점'
                await page.evaluate('''() => {
                  window.originalStores = stores;
                  stores = Array.from({length:1000}, (_,i)=>({...originalStores[0], id:`fixture-${i}`, name:`테스트 매장 ${i}`, address:`테스트 주소 ${i}`}));
                }''')
                await page.locator('#storeSearch').fill('테스트')
                assert await page.locator('[data-store]').count() == 6
                assert '1000곳' in await page.locator('#searchStatus').inner_text()
                await page.locator('#storeSearch').fill('테스트매장999')
                await page.locator('[data-store="fixture-999"]').click()
                assert await page.locator('#placeName').input_value() == '테스트 매장 999'
                await page.evaluate('stores = originalStores')
                await page.locator('#storeSearch').fill('스타벅스')
                await page.locator('[data-store]').click()
                # Local preview must work without creating a session or uploading audio.
                await page.locator('#micOrbit').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.wait_for_timeout(1000)
                assert await waveform_ink(page) > 100
                assert await page.locator('#saveStatus').is_hidden()
                assert not app['demo'].sessions
                await page.evaluate('testTone.gain.gain.value = 0')
                await page.wait_for_selector('#waveformPanel[data-input="quiet"]')
                await page.wait_for_timeout(4300)
                assert await waveform_ink(page) == 0
                await page.evaluate('testTone.gain.gain.value = .12')
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.evaluate('window.lastPreview = previewStream; audioContext.suspend()')
                await page.wait_for_selector('#resumeMeterBtn', state='visible')
                await page.locator('#resumeMeterBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.wait_for_timeout(1500)
                await page.locator('#recorderCard').screenshot(path=str(ROOT/'demo/test-artifacts/mic-preview.png'))
                await page.locator('#endPreviewBtn').click()
                assert await page.locator('#waveformPanel').is_hidden()
                assert await page.evaluate("lastPreview.getTracks().every(t=>t.readyState==='ended') && audioContext===null && meterSink===null")
                # Permission denial leaves the button usable.
                await page.evaluate("() => { navigator.mediaDevices.getUserMedia = async()=>{throw new DOMException('denied','NotAllowedError')}; }")
                await page.locator('#micOrbit').click()
                await page.wait_for_selector('#micStatus[data-state="error"]')
                assert not await page.locator('#micOrbit').is_disabled()
                assert await page.evaluate('audioContext === null')
                # Cancel a pending permission request; a late stream must be closed.
                await page.evaluate('() => { navigator.mediaDevices.getUserMedia = () => new Promise(resolve => window.resolveMic = resolve); }')
                await page.locator('#micOrbit').click()
                await page.wait_for_function('typeof resolveMic === "function"')
                await page.locator('#micOrbit').click()
                await page.evaluate('goodMic().then(s=>{window.lateStream=s;resolveMic(s)})')
                await page.wait_for_function('lateStream.getTracks().every(t=>t.readyState==="ended")')
                assert await page.locator('#waveformPanel').is_hidden()
                # Backgrounding releases the preview microphone.
                await page.evaluate('() => { navigator.mediaDevices.getUserMedia = goodMic; }')
                await page.locator('#micOrbit').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
                assert await page.evaluate('previewStream===null && audioContext===null')
                assert not app['demo'].sessions
                for width in (320,390,768,1440):
                    await page.set_viewport_size({'width':width,'height':900})
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                await page.screenshot(path=str(ROOT/'demo/test-artifacts/search-desktop.png'),full_page=True)
                assert not errors,errors
                await browser.close()
                print('PASS: bounded 1000-store search, menu/map/keyboard selection, real preview signal/silence, no upload, resume, denied/pending permission cleanup, background cleanup, responsive layout')
        finally:
            await server.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
