import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from drive_order.demo_server import create_app


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.fail_once = False

        async def runner(state, recording, output):
            self.calls.append((recording.read_bytes(), output))
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError('temporary failure')
            output.mkdir()
            (output/'orders.json').write_text(json.dumps({'status': 'draft', 'speakers': {}}))
            (output/'utterances.jsonl').write_text('')
            (output/'order_events.jsonl').write_text('')
            (output/'metrics.json').write_text('{}')

        self.app = create_app(self.temp.name, runner)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.headers = {'X-Drive-Order': '1', 'Authorization': 'Bearer '+self.app['demo'].access_key}

    async def create(self):
        response = await self.client.post('/api/sessions', headers=self.headers, json={
            'destination': {'name': '직접 선택한 카페', 'latitude': 37.56, 'longitude': 126.97},
            'menu': [{'name': '라떼', 'aliases': ['카페라떼']}], 'mime': 'audio/webm;codecs=opus'})
        self.assertEqual(response.status, 201)
        return (await response.json())['id']

    async def await_done(self, id):
        for _ in range(100):
            state = await (await self.client.get('/api/sessions/'+id, headers=self.headers)).json()
            if state['status'] in ('complete', 'failed'):
                return state
            await asyncio.sleep(.01)
        self.fail('job did not finish')

    async def test_deleted_records_do_not_hide_older_orders(self):
        kept = await self.create()
        for _ in range(30):
            deleted = await self.create()
            response = await self.client.delete('/api/sessions/'+deleted, headers=self.headers)
            self.assertEqual(response.status, 200)
        records = await (await self.client.get('/api/sessions', headers=self.headers)).json()
        self.assertEqual([s['id'] for s in records], [kept])

    async def test_authentication_origin_and_secure_pairing(self):
        self.assertEqual((await self.client.get('/api/sessions')).status, 401)
        bad = await self.client.post('/api/pair', headers={'X-Drive-Order': '1'}, json={'key': 'wrong'})
        self.assertEqual(bad.status, 401)
        headers = {**self.headers, 'Origin': 'https://unrelated.example'}
        self.assertEqual((await self.client.post('/api/pair', headers=headers, json={})).status, 403)
        headers = {'X-Drive-Order': '1', 'Host': 'demo-test.trycloudflare.com', 'Origin': 'https://demo-test.trycloudflare.com'}
        paired = await self.client.post('/api/pair', headers=headers, json={'key': self.app['demo'].access_key})
        self.assertEqual(paired.status, 200)
        self.assertTrue(paired.cookies['moa_access']['secure'])
        self.assertTrue(paired.cookies['moa_access']['httponly'])
        self.assertEqual((await self.client.get('/', headers={'Host': 'evil.example'})).status, 403)

    async def test_chunk_order_idempotency_completion_and_isolation(self):
        id = await self.create()
        other = await self.create()
        base = '/api/sessions/'+id
        self.assertEqual((await self.client.post(base+'/chunks/1', headers=self.headers, data=b'B')).status, 409)
        for _ in range(2):
            self.assertEqual((await self.client.post(base+'/chunks/0', headers=self.headers, data=b'A')).status, 200)
        self.assertEqual((await self.client.post(base+'/chunks/0', headers=self.headers, data=b'X')).status, 409)
        self.assertEqual((await self.client.post(base+'/finish', headers=self.headers, json={'chunks': 2})).status, 409)
        await self.client.post(base+'/chunks/1', headers=self.headers, data=b'B')
        for _ in range(2):
            self.assertEqual((await self.client.post(base+'/finish', headers=self.headers, json={'chunks': 2, 'duration': 2})).status, 200)
        state = await self.await_done(id)
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], b'AB')
        other_state = await (await self.client.get('/api/sessions/'+other, headers=self.headers)).json()
        self.assertEqual(other_state['bytes'], 0)
        result = await (await self.client.get(base+'/result', headers=self.headers)).json()
        self.assertEqual(result['session']['menu']['items'][0]['name'], '라떼')
        self.assertEqual((await self.client.post(base+'/chunks/2', headers=self.headers, data=b'C')).status, 409)
        renamed = await self.client.post(base+'/names', headers=self.headers, json={'names': {'speaker_0': '운전자'}})
        self.assertEqual((await renamed.json())['speaker_names']['speaker_0'], '운전자')
        self.assertEqual((await self.client.get(base+'/audio')).status, 401)

    async def test_failed_job_retry_uses_saved_recording_and_new_output(self):
        id = await self.create()
        base = '/api/sessions/'+id
        await self.client.post(base+'/chunks/0', headers=self.headers, data=b'RECORDING')
        self.fail_once = True
        await self.client.post(base+'/finish', headers=self.headers, json={'chunks': 1, 'duration': 1})
        self.assertEqual((await self.await_done(id))['status'], 'failed')
        await self.client.post(base+'/finish', headers=self.headers, json={'chunks': 1, 'duration': 1})
        state = await self.await_done(id)
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(state['attempt'], 2)
        self.assertEqual(self.calls[0][0], self.calls[1][0])
        self.assertNotEqual(self.calls[0][1], self.calls[1][1])

    async def test_cancel_prevents_analysis(self):
        id = await self.create()
        base = '/api/sessions/'+id
        await self.client.post(base+'/cancel', headers=self.headers, json={})
        self.assertEqual((await self.client.post(base+'/chunks/0', headers=self.headers, data=b'A')).status, 409)
        self.assertEqual((await self.client.post(base+'/finish', headers=self.headers, json={'chunks': 0})).status, 409)
        self.assertEqual(await (await self.client.get('/api/sessions', headers=self.headers)).json(), [])

    async def test_browser_link_requires_authentication_and_same_origin(self):
        denied = await self.client.post('/api/access-link', headers={'X-Drive-Order': '1'}, json={})
        self.assertEqual(denied.status, 401)
        wrong_origin = await self.client.post('/api/access-link', headers={**self.headers, 'Origin': 'https://untrusted.local'}, json={})
        self.assertEqual(wrong_origin.status, 403)
        accepted = await self.client.post('/api/access-link', headers=self.headers, json={})
        self.assertEqual(accepted.status, 200)
        self.assertEqual((await accepted.json())['key'], self.app['demo'].access_key)
        self.assertEqual(accepted.headers['Cache-Control'], 'no-store')

    async def test_phone_host_allowlist_does_not_bypass_pairing_or_origin(self):
        self.app['allowed_hosts'] = frozenset(['order.local'])
        self.assertEqual((await self.client.get('/api/config', headers={'Host': 'order.local'})).status, 401)
        self.assertEqual((await self.client.get('/', headers={'Host': 'untrusted.local'})).status, 403)
        rejected = await self.client.post('/api/pair', headers={
            'Host': 'order.local', 'Origin': 'https://untrusted.local', 'X-Drive-Order': '1'},
            json={'key': self.app['demo'].access_key})
        self.assertEqual(rejected.status, 403)
        accepted = await self.client.post('/api/pair', headers={
            'Host': 'order.local', 'Origin': 'https://order.local', 'X-Drive-Order': '1'},
            json={'key': self.app['demo'].access_key})
        self.assertEqual(accepted.status, 200)
        self.assertTrue(accepted.cookies['moa_access']['secure'])

    async def test_registered_stores_use_authoritative_menu_and_distinct_ids(self):
        config = await (await self.client.get('/api/config', headers=self.headers)).json()
        self.assertEqual([len(s['items']) for s in config['stores']], [8, 5, 5])
        states = []
        for store in config['stores']:
            response = await self.client.post('/api/sessions', headers=self.headers, json={
                'catalog_store_id': store['id'], 'mime': 'audio/webm',
                'destination': {'name': '다른 지점', 'latitude': 0, 'longitude': 0},
                'menu': [{'name': '등록되지 않은 음식', 'aliases': []}]})
            self.assertEqual(response.status, 201)
            state = await response.json()
            states.append(state)
            self.assertEqual(state['destination']['name'], store['name'])
            self.assertEqual(state['destination']['latitude'], store['latitude'])
            self.assertEqual(state['menu']['source'], 'user_provided')
            self.assertEqual([m['name'] for m in state['menu']['items']], [m['name'] for m in store['items']])
            self.assertEqual(state['menu']['store_id'], store['id'])
            # Session edits must not change the catalogue for the next recording.
            self.app['demo'].sessions[state['id']]['menu']['items'][0]['aliases'].append('임의 수정')
            self.assertNotIn('임의 수정', self.app['demo'].stores[store['id']]['items'][0]['aliases'])
        self.assertEqual(len({s['destination']['store_id'] for s in states}), 3)
        invalid = await self.client.post('/api/sessions', headers=self.headers, json={
            'catalog_store_id': 'unknown', 'mime': 'audio/webm'})
        self.assertEqual(invalid.status, 400)




    async def test_upload_validation_and_actual_deletion(self):
        import io
        import wave
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(b'\0\0' * 16000)
        payload = audio.getvalue()
        async def upload(data):
            response = await self.client.post('/api/sessions', headers=self.headers, json={
                'destination': {'name':'업로드 매장', 'latitude':37.56, 'longitude':126.97},
                'menu':[{'name':'라떼'}], 'mime':'audio/wav', 'source':'upload', 'expected_bytes':len(data)})
            self.assertEqual(response.status, 201)
            id = (await response.json())['id']
            base = '/api/sessions/'+id
            await self.client.post(base+'/chunks/0', headers=self.headers, data=data[:10])
            self.assertEqual((await self.client.post(base+'/finish', headers=self.headers, json={'chunks':1})).status, 409)
            await self.client.post(base+'/chunks/1', headers=self.headers, data=data[10:])
            await self.client.post(base+'/finish', headers=self.headers, json={'chunks':2,'duration':0})
            return id, await self.await_done(id)
        id, state = await upload(payload)
        self.assertEqual(state['status'], 'complete')
        self.assertAlmostEqual(state['duration'], 1, places=2)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((Path(self.temp.name)/id).exists())
        self.assertEqual((await self.client.delete('/api/sessions/'+id, headers=self.headers)).status, 200)
        self.assertFalse((Path(self.temp.name)/id).exists())
        self.assertEqual((await self.client.get('/api/sessions/'+id, headers=self.headers)).status, 404)
        self.assertEqual((await self.client.get('/api/sessions/'+id+'/audio', headers=self.headers)).status, 404)
        self.assertEqual((await self.client.post('/api/sessions/'+id+'/chunks/2', headers=self.headers, data=b'x')).status, 404)
        bad, state = await upload(b'not an audio file at all')
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(len(self.calls), 1, 'invalid audio must not reach inference')
        self.assertEqual((await self.client.delete('/api/sessions/'+bad, headers=self.headers)).status, 200)
        self.assertEqual(await (await self.client.get('/api/sessions', headers=self.headers)).json(), [])

    async def test_delete_blocked_during_analysis_and_requires_auth(self):
        id = await self.create()
        base = '/api/sessions/'+id
        self.assertEqual((await self.client.delete(base, headers={'X-Drive-Order': '1'})).status, 401)
        for status in ('queued','processing'):
            self.app['demo'].sessions[id]['status'] = status
            self.assertEqual((await self.client.delete(base, headers=self.headers)).status, 409)
            self.assertTrue((Path(self.temp.name)/id).exists())
        self.app['demo'].sessions[id]['status'] = 'recording'
        self.assertEqual((await self.client.delete(base, headers=self.headers)).status, 200)

if __name__ == '__main__':
    unittest.main()
