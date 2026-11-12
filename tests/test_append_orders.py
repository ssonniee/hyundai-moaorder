"""Saved order revisions use real audio concatenation and deterministic order updates."""
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

from aiohttp.test_utils import TestClient, TestServer
from drive_order.demo_server import create_app
from drive_order.orders import OrderBook, dump


def audio(value=1000):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
        f.writeframes(value.to_bytes(2, 'little', signed=True)*16000)
    return buf.getvalue()


class AppendOrderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inputs = []
        self.fail_runner = False
        self.app = create_app(self.temp.name, self.runner)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.headers = {'X-Drive-Order':'1', 'Authorization':'Bearer '+self.app['demo'].access_key}

    async def runner(self, state, recording, output):
        with wave.open(str(recording)) as f:
            self.inputs.append(f.readframes(f.getnframes()))
        if self.fail_runner:
            self.fail_runner = False
            raise RuntimeError('retry fixture')
        # Each run consumes the entire conversation, including the old choice.
        count = state.get('revision', 1)
        turns = [dict(id='1',speaker='speaker_0',start=0,end=.8,text='라떼 하나'),
                 dict(id='2',speaker='speaker_0',start=1,end=1.8,text='라떼 말고 차 하나'),
                 dict(id='3',speaker='speaker_0',start=2,end=2.8,text='차 두 잔 더')][:count]
        ops = iter([[dict(op='set', menu_id='menu_000', quantity=1, options=[])],
                    [dict(op='remove', menu_id='menu_000'),dict(op='set',menu_id='menu_001',quantity=1,options=[])],
                    [dict(op='add',menu_id='menu_001',quantity=2,options=[])]])
        book = OrderBook(state['menu'], lambda _:dict(action='update',operations=next(ops),reason='synthetic test'), output)
        for turn in turns:
            book.consume(turn)
        (output/'utterances.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in turns))
        dump(output/'metrics.json', {'audio_seconds':count})

    async def create(self, parent=None, payload=None):
        payload = payload if payload is not None else audio()
        body = dict(destination=dict(name='테스트 카페',latitude=37.5,longitude=127.),
                    menu=[dict(name='라떼'),dict(name='차')],mime='audio/wav',source='upload',expected_bytes=len(payload))
        if parent:
            body.update(parent_id=parent, destination=dict(name='변경 금지',latitude=0,longitude=0),menu=[dict(name='다른 메뉴')])
        response = await self.client.post('/api/sessions',headers=self.headers,json=body)
        self.assertEqual(response.status,201,await response.text())
        return await response.json()

    async def finish(self, state, payload=None):
        payload = payload if payload is not None else audio()
        url = '/api/sessions/'+state['id']
        res = await self.client.post(url+'/chunks/0',headers=self.headers,data=payload)
        self.assertEqual(res.status,200)
        res = await self.client.post(url+'/finish',headers=self.headers,json=dict(chunks=1,duration=1))
        self.assertEqual(res.status,200)
        return await self.done(state['id'])

    async def done(self, id):
        for _ in range(300):
            state = await self.get('/api/sessions/'+id)
            if state['status'] in ('complete','failed'):
                return state
            await asyncio.sleep(.02)
        self.fail('processing timed out')

    async def get(self, path):
        res = await self.client.get(path,headers=self.headers)
        self.assertEqual(res.status,200,await res.text())
        return await res.json()

    async def test_append_reanalysis_saved_results_and_restart(self):
        first = await self.finish(await self.create())
        second = await self.create(first['id'],audio(2000))
        self.assertEqual(second['menu'],first['menu'])
        self.assertEqual(second['destination'],first['destination'])
        second = await self.finish(second,audio(2000))
        third = await self.finish(await self.create(second['id'],audio(3000)),audio(3000))
        self.assertEqual(third['status'],'complete')
        self.assertAlmostEqual(third['duration'],3)
        expected = b''.join(v.to_bytes(2,'little',signed=True)*16000 for v in (1000,2000,3000))
        self.assertEqual(self.inputs[-1],expected,'old recordings must appear exactly once and in order')
        result = await self.get('/api/sessions/'+third['id']+'/result')
        self.assertEqual([(x['name'],x['quantity']) for x in result['orders']['speakers']['speaker_0']],[('차',3)])
        self.assertEqual(len(result['utterances']),3)
        self.assertEqual([(x['start'],x['end']) for x in result['recordings']],[(0,1),(1,2),(2,3)])
        records = await self.get('/api/sessions')
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['id'],third['id'])
        old = await self.get('/api/sessions/'+first['id']+'/result')
        self.assertEqual(old['orders']['speakers']['speaker_0'][0]['name'],'라떼')
        response = await self.client.get('/api/sessions/'+third['id']+'/audio',headers=self.headers)
        self.assertEqual(response.headers['Content-Type'],'audio/wav')
        with wave.open(io.BytesIO(await response.read())) as f:
            self.assertEqual(f.getnframes(),48000)
        stale = await self.client.post('/api/sessions',headers=self.headers,json=dict(parent_id=first['id']))
        self.assertEqual(stale.status,409)
        restored = create_app(self.temp.name,self.runner)['demo']
        self.assertEqual(restored.result(restored.get(third['id']))['orders'],result['orders'])
        self.assertEqual(restored.recordings(restored.get(third['id'])),result['recordings'])

    async def test_pending_failure_retry_and_deletion_preserve_parent(self):
        first = await self.finish(await self.create())
        pending = await self.create(first['id'])
        duplicate = await self.client.post('/api/sessions',headers=self.headers,json=dict(parent_id=first['id']))
        self.assertEqual(duplicate.status,409)
        self.assertEqual((await self.client.delete('/api/sessions/'+first['id'],headers=self.headers)).status,409)
        records = await self.get('/api/sessions')
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['pending_append']['id'],pending['id'])
        self.fail_runner = True
        failed = await self.finish(pending)
        self.assertEqual(failed['status'],'failed')
        self.assertEqual((await self.get('/api/sessions'))[0]['id'],first['id'])
        res = await self.client.post('/api/sessions/'+pending['id']+'/finish',headers=self.headers,json=dict(chunks=1,duration=1))
        self.assertEqual(res.status,200)
        self.assertEqual((await self.done(pending['id']))['status'],'complete')
        self.assertEqual(self.inputs[-1],self.inputs[-2])
        extra = await self.create(pending['id'])
        self.assertEqual((await self.client.delete('/api/sessions/'+extra['id'],headers=self.headers)).status,200)
        self.assertEqual((await self.get('/api/sessions'))[0]['id'],pending['id'])
        other = await self.finish(await self.create())
        self.assertEqual((await self.client.delete('/api/sessions/'+pending['id'],headers=self.headers)).status,200)
        self.assertFalse((Path(self.temp.name)/first['id']).exists())
        self.assertFalse((Path(self.temp.name)/pending['id']).exists())
        self.assertEqual([s['id'] for s in await self.get('/api/sessions')],[other['id']])

    async def test_simultaneous_additions_are_serialized(self):
        first = await self.finish(await self.create())
        async def request():
            return await self.client.post('/api/sessions',headers=self.headers,json=dict(
                parent_id=first['id'],mime='audio/wav'))
        responses = await asyncio.gather(request(),request())
        self.assertEqual(sorted(r.status for r in responses),[201,409])
        self.assertEqual(len(self.app['demo'].order_members(first)),2)

    async def test_legacy_order_can_accept_an_addition(self):
        first = await self.finish(await self.create())
        state = self.app['demo'].get(first['id'])
        for name in ('order_id','parent_id','revision'):
            state.pop(name)
        self.app['demo'].save(state)
        second = await self.finish(await self.create(first['id']))
        self.assertEqual(second['status'],'complete')
        self.assertEqual(second['order_id'],first['id'])
        self.assertEqual(len(await self.get('/api/sessions')),1)
