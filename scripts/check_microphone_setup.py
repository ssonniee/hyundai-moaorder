"""Simulated device failures + real browser media stream, without recording human audio."""
import asyncio
from pathlib import Path
import tempfile

from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from drive_order.orders import dump
from check_recording_meter import TONE

ROOT = Path(__file__).resolve().parents[1]


async def main():
    async def runner(state, recording, output):
        assert recording.stat().st_size > 0
        output.mkdir()
        dump(output/'orders.json', {'status': 'draft', 'speakers': {}})
        dump(output/'metrics.json', {'audio_seconds': state['duration']})
        (output/'utterances.jsonl').write_text('')
        (output/'order_events.jsonl').write_text('')

    with tempfile.TemporaryDirectory() as data:
        app = create_app(data, runner)
        server = web.AppRunner(app)
        await server.setup()
        await web.TCPSite(server, '127.0.0.1', 8769).start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context(viewport={'width': 390, 'height': 844})
                await context.add_init_script(TONE + '''
                window.goodMic = navigator.mediaDevices.getUserMedia;
                navigator.mediaDevices.getUserMedia = async options => {
                  window.micOptions = options; window.checkedStream = await goodMic(options); return checkedStream;
                };
                ''')
                await context.route('https://tile.openstreetmap.org/**', lambda r: r.abort())
                await context.route('https://fonts.googleapis.com/**', lambda r: r.abort())
                page = await context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                await page.goto('http://127.0.0.1:8769/#key='+app['demo'].access_key)
                await page.wait_for_selector('#health.ready')
                await page.locator('#checkMicBtn').click()
                await page.wait_for_function("document.getElementById('micStatus').textContent.includes('실제 소리 입력')")
                assert await page.evaluate("checkedStream.getTracks().every(t => t.readyState === 'ended')")
                assert await page.evaluate('micOptions.audio === true')
                assert not app['demo'].sessions, 'Microphone check must not save/upload audio'
                await page.locator('[data-store="starbucks_wangsimni_exit9"]').click()
                for name, phrase in [('NotFoundError', '녹음 장치를'), ('NotAllowedError', '허용되지'), ('NotReadableError', '열지 못했어요')]:
                    await page.evaluate("name => navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('test', name); }", name)
                    await page.locator('#startBtn').click()
                    await page.wait_for_function("() => phase === 'idle' && document.getElementById('micStatus').dataset.state === 'error'")
                    assert phrase in await page.locator('#micStatus').inner_text()
                    assert await page.locator('#micHelp').is_visible()
                    assert not app['demo'].sessions
                    assert await page.evaluate('audioContext === null')
                await page.locator('#copyBrowserLink').click()
                await page.wait_for_selector('#browserLink', state='visible')
                assert await page.locator('#browserLink').input_value() == 'http://127.0.0.1:8769/#key='+app['demo'].access_key
                # A device choice must be honored, not silently replaced with another input.
                await page.evaluate('''() => {
                  document.getElementById('microphoneSelect').add(new Option('USB test mic', 'chosen-device'));
                  navigator.mediaDevices.getUserMedia = async options => { window.micOptions = options; return goodMic(options); };
                }''')
                await page.locator('#microphoneSelect').select_option('chosen-device')
                await page.locator('#startBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                assert await page.evaluate("micOptions.audio.deviceId.exact === 'chosen-device'")
                assert await page.locator('#checkMicBtn').is_disabled()
                assert await page.locator('#microphoneSelect').is_disabled()
                await page.wait_for_timeout(1200)
                await page.locator('#stopBtn').click()
                await page.wait_for_selector('#results', state='visible')
                assert await page.locator('#micHelp').is_hidden()
                for width in (320, 390, 1440):
                    await page.set_viewport_size({'width': width, 'height': 900})
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                assert not errors, errors
                await browser.close()
                print('PASS: local-only mic check, missing/denied/busy devices, safe cleanup, forwarded-port link, explicit device choice, real MediaRecorder recovery, narrow layouts')
        finally:
            await server.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
