"""Pause/resume/delete, real WAV uploads and repeated orders. No speech-model inference."""
import asyncio
import io
import wave
import tempfile
from pathlib import Path
from aiohttp import web
from playwright.async_api import async_playwright
from drive_order.demo_server import create_app
from drive_order.orders import dump
from check_recording_meter import TONE
ROOT=Path(__file__).resolve().parents[1]

def wav(seconds):
    data=io.BytesIO()
    with wave.open(data,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*16000*seconds)
    return data.getvalue()

async def main():
    calls=[]
    async def fixture(state,recording,output):
        calls.append(state['id']);output.mkdir()
        dump(output/'orders.json',{'status':'draft','speakers':{}})
        dump(output/'metrics.json',{'audio_seconds':state['duration']})
        (output/'utterances.jsonl').write_text('');(output/'order_events.jsonl').write_text('')
    with tempfile.TemporaryDirectory() as data:
        app=create_app(data,fixture);server=web.AppRunner(app);await server.setup()
        await web.TCPSite(server,'127.0.0.1',8775).start()
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch()
                ctx=await browser.new_context(viewport={'width':390,'height':844})
                await ctx.add_init_script(TONE)
                await ctx.route('https://tile.openstreetmap.org/**',lambda r:r.abort())
                page=await ctx.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto('http://127.0.0.1:8775/#key='+app['demo'].access_key)
                await page.wait_for_selector('#health.ready')
                async def choose(name):
                    await page.locator('#storeSearch').fill(name)
                    await page.locator('[data-store]').first.click()
                await choose('스타벅스')
                await page.locator('#startBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.wait_for_timeout(1200)
                await page.locator('#pauseBtn').click()
                await page.wait_for_function("phase === 'paused' && recorder.state === 'paused'")
                assert await page.locator('#waveformPanel').is_hidden()
                assert await page.evaluate('stream.getAudioTracks().every(t=>!t.enabled)')
                duration=await page.evaluate('recordingSeconds()')
                await page.wait_for_timeout(1200)
                assert abs(await page.evaluate('recordingSeconds()')-duration)<.01
                assert await page.locator('#storeSearch').is_disabled()
                await page.locator('#pauseBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                await page.wait_for_timeout(1200)
                await page.locator('#pauseBtn').click()
                await page.locator('#stopBtn').click()
                await page.wait_for_selector('#results',state='visible')
                first=await page.evaluate('current.id')
                assert app['demo'].sessions[first]['duration'] < 4
                assert await page.locator('#nextOrderBtn').is_visible()
                await page.locator('#newBtn').click()
                assert await page.locator('#placeName').input_value()==''
                assert await page.locator('#startBtn').is_disabled()
                assert first in app['demo'].sessions
                await choose('맥도날드')
                payload=wav(1)
                await page.locator('#audioFile').set_input_files({'name':'sample.wav','mimeType':'audio/wav','buffer':payload})
                await page.wait_for_selector('#results',state='visible')
                uploaded=await page.evaluate('current.id')
                state=app['demo'].sessions[uploaded]
                assert state['source']=='upload' and state['bytes']==len(payload)
                assert state['destination']['name']=='맥도날드 한양대'
                assert abs(state['duration']-1)<.01
                assert state['destination']['name']!=app['demo'].sessions[first]['destination']['name']
                page.once('dialog',lambda d:d.accept())
                await page.locator('#cancelBtn').click()
                await page.wait_for_function("phase === 'idle' && current === null")
                assert not (Path(data)/uploaded).exists()
                assert (Path(data)/first).exists()
                # Delete while paused; never send this session to analysis.
                await page.locator('#startBtn').click()
                await page.wait_for_selector('#waveformPanel[data-input="signal"]')
                discarded=await page.evaluate('current.id')
                await page.wait_for_timeout(1200)
                await page.locator('#pauseBtn').click()
                page.once('dialog',lambda d:d.accept())
                await page.locator('#cancelBtn').click()
                await page.wait_for_function("phase === 'idle' && current === null")
                assert discarded not in calls and not (Path(data)/discarded).exists()
                # A later chunk failing must be resumable without duplicating the first.
                broken=True
                async def second_chunk(route):
                    if broken: await route.fulfill(status=503,content_type='application/json',body='{"error":"test interrupted"}')
                    else: await route.continue_()
                await ctx.route('**/chunks/1',second_chunk)
                large=wav(140)
                await page.locator('#audioFile').set_input_files({'name':'retry.wav','mimeType':'audio/wav','buffer':large})
                await page.wait_for_function("phase === 'upload_failed'")
                retry_id=await page.evaluate('current.id')
                assert app['demo'].sessions[retry_id]['next_chunk']==1
                assert retry_id not in calls
                broken=False
                await page.locator('#retryBtn').click()
                await page.wait_for_selector('#results',state='visible')
                assert app['demo'].sessions[retry_id]['bytes']==len(large)
                assert calls.count(retry_id)==1
                await page.locator('#newBtn').click()
                await choose('백소정')
                for theme in ('light','dark'):
                    await page.locator(f'[data-set-theme="{theme}"]').click()
                    await page.wait_for_timeout(200)
                    await page.locator('#recorderCard').screenshot(path=str(ROOT/f'demo/test-artifacts/record-controls-{theme}.png'))
                for width in (320,390,768,1440):
                    await page.set_viewport_size({'width':width,'height':900})
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
                assert not errors,errors
                await browser.close()
                print('PASS: pause/resume excludes paused time, stop/delete while paused, actual file deletion, WAV upload validation, interrupted upload resume, separate repeated orders, responsive themes')
        finally:await server.cleanup()
if __name__=='__main__':asyncio.run(main())
