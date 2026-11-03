import json
import threading
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import SimulationServer
from app.server import ROOT


class APITests(unittest.TestCase):
    def test_forecast_contract_exposes_correct_model_and_preserves_state(self):
        with self.request('/api/optimizer/reset',{'forecast_horizon':12,'traffic_pattern':'periodic'}) as response:
            before=json.load(response)
        with self.request('/api/optimizer/forecast?node=U1&steps=3') as response:
            result=json.load(response)
        self.assertEqual(set(result['nodes']),{'U1'})
        self.assertEqual(result['method'],'adaptive_ar_holt_persistence')
        self.assertEqual(result['flow_horizon_seconds'],6)
        self.assertEqual(len(result['nodes']['U1']['forecast']),3)
        with self.request('/api/optimizer/state') as response:
            self.assertEqual(json.load(response),before)

    @classmethod
    def setUpClass(cls):
        cls.server = SimulationServer(('127.0.0.1', 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None):
        request = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
        return urlopen(request, timeout=5)

    def test_scenario_replay_and_rejection_are_atomic(self):
        from app import scenarios
        if not (scenarios.ROOT/'index.json').is_file():
            self.skipTest('Generated catalog is not installed')
        with self.request('/api/optimizer/scenarios?method=random&limit=1') as response:
            item = json.load(response)['scenarios'][0]
        with self.request('/api/optimizer/scenario', {'scenario_id': item['scenario_id']}) as response:
            loaded = json.load(response)
        self.assertEqual(loaded['state']['deployment'], 'distributed')
        self.assertEqual(len(loaded['state']['nodes']), item['nodes'])
        for body in ({'scenario_id': 'x'*64}, {'scenario_id': item['scenario_id'], 'label': {}}):
            with self.assertRaises(HTTPError):
                self.request('/api/optimizer/scenario', body)
        with self.request('/api/optimizer/state') as response:
            self.assertEqual(json.load(response), loaded['state'])

    def test_only_current_distributed_profiles_are_public(self):
        for body in ({'deployment': 'regional'}, {'constellation': 'legacy'}):
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/optimizer/reset', body)
            self.assertEqual(caught.exception.code, 400)

    def test_reset_step_and_invalid_action(self):
        with self.request('/api/reset', {'duration_s': 1, 'seed': 9}) as response:
            state = json.load(response)
        self.assertEqual(state['metrics']['time_s'], 0)
        with self.request('/api/step', {'steps': 5}) as response:
            state = json.load(response)
        self.assertAlmostEqual(state['metrics']['time_s'], .5)
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/step', {'action': {'bandwidth_hz': {'bad->link': 1}}})
        self.assertEqual(caught.exception.code, 400)
        with self.request('/api/state') as response:
            self.assertEqual(json.load(response), state)
        with self.assertRaises(HTTPError):
            self.request('/api/reset', {'battery_j': -1})
        with self.request('/api/state') as response:
            self.assertEqual(json.load(response), state)

    def test_site_assets_and_no_source_exposure(self):
        for path in ('/', '/network.html', '/css/optimizer.css', '/js/optimizer/app.js'):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())
        for path in ('/.git/config', '/server.py', '/js/../server.py', '/assets/', '/illustration.html', '/js/network/dashboard.js'):
            with self.assertRaises(HTTPError) as caught:
                self.request(path)
            self.assertEqual(caught.exception.code, 404)

    def test_new_frontend_paths_and_legacy_css_aliases(self):
        for name in ('base.css','earth.css','workbench.css'):
            with self.request('/css/'+name) as response:
                self.assertEqual(response.status,200)
                self.assertIn('text/css',response.headers['Content-Type'])
                self.assertTrue(response.read())
        for old,new in (('optimizer.css','workbench.css'),('styles.css','earth.css'),('refinements.css','base.css')):
            with self.request('/css/'+old) as response: legacy=response.read()
            with self.request('/css/'+new) as response: current=response.read()
            self.assertEqual(legacy,current)
        for path in ('/app/server.py','/web/network.html','/optimizer/service.py'):
            with self.assertRaises(HTTPError): self.request(path)

    def test_report_routes_are_explicit_and_do_not_expose_output_directories(self):
        (ROOT/'outputs').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'outputs') as directory:
            report=Path(directory)/'report.html'
            report.write_text('<!doctype html><title>Report fixture</title>',encoding='utf-8')
            with patch.dict('app.server.REPORTS',{'/reports/test.html':report}):
                with self.request('/reports/test.html') as response:
                    self.assertEqual(response.status,200)
                    self.assertIn(b'Report fixture',response.read())
        for path in ('/outputs/','/reports/../server.py','/reports/unknown.html'):
            with self.assertRaises(HTTPError): self.request(path)

    def test_internal_errors_have_json_bodies_instead_of_empty_responses(self):
        from simulator.packet_simulation import PacketSimulation
        for method, path, body in (('snapshot', '/api/state', None),
                                   ('step', '/api/step', {'steps': 1})):
            with patch.object(PacketSimulation, method, side_effect=RuntimeError('test failure')):
                with self.assertLogs(level='ERROR'):
                    with self.assertRaises(HTTPError) as caught:
                        self.request(path, body)
                response = caught.exception
                self.assertEqual(response.code, 500)
                self.assertIn('application/json', response.headers['Content-Type'])
                self.assertTrue(json.loads(response.read())['error'])

    def test_unknown_api_has_json_error(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/not-found')
        self.assertEqual(caught.exception.code, 404)
        self.assertTrue(json.loads(caught.exception.read())['error'])

    def test_optimizer_api_search_compare_transmit_and_stale_plan(self):
        with self.request('/api/optimizer/reset', {'size':'full'}) as response:
            state=json.load(response)
        self.assertEqual(len(state['nodes']),69)
        budget={'ants':4,'aco_iterations':4,'particles':4,'pso_iterations':4}
        with self.request('/api/optimizer/optimize',{'request':{'source':'G1','target':'G6'},'method':'aco_pso','budget':budget}) as response:
            plan=json.load(response)
        self.assertTrue(plan['feasible'])
        with self.request('/api/optimizer/state') as response: self.assertEqual(json.load(response),state)
        with self.request('/api/optimizer/transmit',{'plan_id':plan['plan_id']}) as response:
            result=json.load(response)
        self.assertEqual(result['state']['served'],1)
        self.assertGreater(result['state']['revision'],state['revision'])
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/optimizer/transmit',{'plan_id':plan['plan_id']})
        self.assertEqual(caught.exception.code,400)
        with self.request('/api/optimizer/advance',{'seconds':1}) as response:
            self.assertEqual(json.load(response)['served'],1)

    def test_optimizer_rejects_invalid_requests_without_mutation(self):
        with self.request('/api/optimizer/reset',{}) as response: before=json.load(response)
        for body in ({'request':{'data_mb':-1}}, {'method':'unknown'}, {'budget':{'ants':999}}, {'seed':True}):
            with self.assertRaises(HTTPError) as caught: self.request('/api/optimizer/optimize',body)
            self.assertEqual(caught.exception.code,400)
        with self.assertRaises(HTTPError): self.request('/api/optimizer/reset',{'battery_j':-10})
        with self.request('/api/optimizer/state') as response: self.assertEqual(json.load(response),before)
        for path in ('/js/optimizer/app.js','/js/optimizer/globe.js','/css/optimizer.css','/index.html'):
            with self.request(path) as response: self.assertEqual(response.status,200)

    def test_ai_method_and_latency_preference_over_http(self):
        with self.request('/api/optimizer/reset', {'size':'small'}) as response:
            before = json.load(response)
        body = {'method':'ai_aco_pso', 'request':{'latency_weight':.7},
                'budget':{'ants':4,'aco_iterations':4,'particles':4,'pso_iterations':4}}
        with self.request('/api/optimizer/optimize', body) as response:
            plan = json.load(response)
        self.assertTrue(plan['feasible'])
        self.assertIn(plan['ai']['status'], ('ready', 'fallback'))
        self.assertEqual(plan['request']['latency_weight'], .7)
        with self.request('/api/optimizer/state') as response:
            self.assertEqual(json.load(response), before)
        for value in (-1, 2, True):
            body['request']['latency_weight'] = value
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/optimizer/optimize', body)
            self.assertEqual(caught.exception.code, 400)

    def test_resource_profiles_forecast_and_invalid_reset_are_atomic(self):
        with self.request('/api/optimizer/reset', {'size':'full', 'battery_profile':'mixed',
                         'load_profile':'mixed','forecast_load':True,'state_seed':17}) as response:
            state = json.load(response)
        self.assertEqual({n['battery_level'] for n in state['nodes'] if n['battery_j'] is not None}, {'weak','medium','strong'})
        self.assertEqual(state['forecast_method'], 'Holt double exponential smoothing')
        self.assertTrue(all(n['planning_bandwidth_hz'] <= n['available_bandwidth_hz'] for n in state['nodes']))
        for config in ({'battery_profile':'bad'}, {'load_profile':'bad'}, {'state_seed':True}, {'forecast_load':'yes'}):
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/optimizer/reset', config)
            self.assertEqual(caught.exception.code, 400)
        with self.request('/api/optimizer/state') as response:
            self.assertEqual(json.load(response), state)


if __name__ == '__main__':
    unittest.main()
