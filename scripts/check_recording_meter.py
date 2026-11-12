"""Real browser audio/MediaRecorder checks using a controllable synthetic tone.

Checks signal vs silence, delayed/failed upload, AudioContext resume and cleanup.
Does not test human speech recognition or run the GPU pipeline.
"""
import asyncio
from pathlib import Path
import tempfile

from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from drive_order.orders import dump

ROOT = Path(__file__).resolve().parents[1]
TONE = '''navigator.mediaDevices.getUserMedia = async () => {
  const context = new AudioContext(); await context.resume();
  const oscillator = context.createOscillator(), gain = context.createGain();
  const destination = context.createMediaStreamDestination();
  oscillator.frequency.value = 220; gain.gain.value = .12;
  oscillator.connect(gain).connect(destination); oscillator.start();
  window.testTone = {context, gain};
  return destination.stream;
};'''


async def main():
    async def runner(state, recording, output):
        assert recording.stat().st_size > 1000
        output.mkdir()
        dump(output/'orders.json', {'status': 'draft', 'speakers': {}})
        dump(output/'metrics.json', {'audio_seconds': state['duration']})
        (output/'utterances.jsonl').write_text('')
        (output/'order_events.jsonl').write_text('')

    with tempfile.TemporaryDirectory() as data:
        app = create_app(data, runner)
        server = web.AppRunner(app)
        await server.setup()
        await web.TCPSite(server, '127.0.0.1', 8766).start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                for failing in (False, True):
                    context = await browser.new_context(viewport={'width': 390, 'height': 844})
                    await context.add_init_script(TONE)
                    await context.route('https://tile.openstreetmap.org/**', lambda r: r.abort())
                    await context.route('https://fonts.googleapis.com/**', lambda r: r.abort())
                    gate = asyncio.Event()
                    async def upload(route):
                        if failing:
                            await route.fulfill(status=503, content_type='application/json', body='{"error":"test offline"}')
                        else:
                            await gate.wait()
                            await route.continue_()
                    await context.route('**/chunks/*', upload)
                    page = await context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.goto('http://127.0.0.1:8766/#key='+app['demo'].access_key)
                    await page.wait_for_selector('#health.ready')
                    await page.locator('[data-store="starbucks_wangsimni_exit9"]').click()
                    await page.locator('#startBtn').click()
                    await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                    await page.wait_for_timeout(1600)
                    id = await page.evaluate("localStorage.getItem('moa-active')")
                    assert app['demo'].sessions[id]['bytes'] == 0
                    assert await page.locator('#saveStatus').get_attribute('data-state') != 'saved'
                    if failing:
                        await page.wait_for_selector('#retryBtn', state='visible', timeout=15000)
                        assert await page.locator('#saveStatus').get_attribute('data-state') == 'error'
                        assert app['demo'].sessions[id]['bytes'] == 0
                        assert await page.evaluate('audioContext === null && meterSource === null')
                    else:
                        gate.set()
                        await page.wait_for_selector('#saveStatus[data-state="saved"]')
                        assert app['demo'].sessions[id]['bytes'] > 0
                        assert 'KB' in await page.locator('#saveStatus').inner_text()
                        assert await page.evaluate('savedBytes') == app['demo'].sessions[id]['bytes']
                        await page.locator('#recorderCard').screenshot(path=str(ROOT/'demo/test-artifacts/recording-waveform.png'))
                        # Silence must eventually remove the previous sound from the 8-second history.
                        await page.evaluate('testTone.gain.gain.value = 0')
                        await page.wait_for_selector('#waveformPanel[data-input="quiet"]')
                        await page.wait_for_timeout(8300)
                        ink = await page.evaluate('''() => {
                            const c = document.getElementById('waveform'), data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                            let count = 0; for (let i=0; i<data.length; i+=4) if (data[i]===49 && data[i+1]===130 && data[i+2]===104 && data[i+3]>0) count++;
                            return count;
                        }''')
                        assert ink == 0, f'silence has {ink} waveform pixels'
                        await page.evaluate('testTone.gain.gain.value = .12')
                        await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                        await page.evaluate('audioContext.suspend()')
                        await page.wait_for_selector('#resumeMeterBtn', state='visible')
                        await page.locator('#resumeMeterBtn').click()
                        await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                        await page.locator('#stopBtn').click()
                        await page.wait_for_selector('#results', state='visible')
                        assert await page.locator('#waveformPanel').get_attribute('data-input') == 'stopped'
                        assert await page.locator('#saveStatus').get_attribute('data-state') == 'saved'
                        assert await page.evaluate('audioContext === null && meterSource === null')
                        await page.locator('#newBtn').click()
                        assert await page.locator('#waveformPanel').is_hidden()
                        for width in (320, 390, 1440):
                            await page.set_viewport_size({'width': width, 'height': 900})
                            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors, errors
                    await context.close()
                await browser.close()
                print('PASS: real signal/silence waveform, acknowledged storage, failed upload, suspend/resume, stop/reset cleanup')
        finally:
            await server.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
