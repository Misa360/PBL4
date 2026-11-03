"""Local static site + network simulation API. Run: python server.py"""

import argparse
import json
import logging
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from simulator.packet_simulation import PacketSimulation, SimulationConfig
from optimizer.models import Budget, Demand
from optimizer.service import OptimizerSession
from . import scenarios

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
REPORTS = {"/reports/catalog.html": ROOT / "outputs/global-scenarios/catalog.html",
           "/reports/evaluation.html": ROOT / "outputs/global-scenarios/evaluation/report.html",
           "/reports/dynamic.html": ROOT / "outputs/global-scenarios/dynamic/report.html",
           "/reports/evaluation-legacy.html": ROOT / "outputs/diverse-1000/evaluation/report.html",
           "/reports/stress.html": ROOT / "outputs/diverse-1000/stress-evaluation/report.html"}


class SimulationServer(ThreadingHTTPServer):
    def __init__(self, address):
        super().__init__(address, partial(Handler, directory=str(WEB)))
        self.simulation = PacketSimulation()
        self.optimizer = OptimizerSession(size='full',deployment='distributed',battery_profile='mixed',load_profile='mixed',forecast_load=True,traffic_pattern='bursty')
        self.state_lock = Lock()


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        aliases = {'/css/optimizer.css':'workbench.css', '/css/styles.css':'earth.css',
                   '/css/refinements.css':'base.css'}
        clean = urlsplit(path).path
        if clean in aliases:
            return str(WEB / 'css' / aliases[clean])
        return super().translate_path(path)

    def _json(self, value, status=200):
        data = json.dumps(value, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlsplit(self.path).path == '/api/optimizer/scenarios':
            from urllib.parse import parse_qs
            try:
                values = parse_qs(urlsplit(self.path).query)
                self._json(scenarios.listing(values.get('method',[''])[0],int(values.get('offset',['0'])[0]),int(values.get('limit',['50'])[0])))
            except (ValueError,TypeError) as error:
                self._json({'error':str(error)},400)
            except Exception:
                logging.exception('Failed to read scenario catalog')
                self._json({'error':'Cannot read scenario catalog'},500)
            return
        if urlsplit(self.path).path == '/api/optimizer/state':
            try:
                with self.server.state_lock:
                    self._json(self.server.optimizer.snapshot())
            except Exception:
                logging.exception('Failed to read optimizer state')
                self._json({'error': 'Cannot read optimizer state; check server terminal.'}, 500)
            return
        if urlsplit(self.path).path == '/api/optimizer/forecast':
            try:
                from urllib.parse import parse_qs
                params = parse_qs(urlsplit(self.path).query)
                steps = int(params.get('steps', ['6'])[0])
                node_filter = params.get('node', [None])[0]
                if not 1 <= steps <= 24:
                    raise ValueError('steps must be between 1 and 24')
                with self.server.state_lock:
                    network = self.server.optimizer.network
                    if node_filter and node_filter not in network.forecasters:
                        self._json({'error': f'Node {node_filter} not found'}, 404)
                        return
                    forecast = network.forecast_all(steps,node_id=node_filter)
                    self._json({'nodes': forecast, 'method': 'adaptive_ar_holt_persistence',
                                'utilization_method':'holt','flow_horizon_seconds':6,
                                'horizon_steps': steps,
                                'time_s': network.time_s})
            except (ValueError, TypeError) as error:
                self._json({'error': str(error)}, 400)
            except Exception:
                logging.exception('Failed to compute traffic forecast')
                self._json({'error': 'Cannot compute forecast; check server terminal.'}, 500)
            return
        if urlsplit(self.path).path == '/api/state':
            try:
                with self.server.state_lock:
                    self._json(self.server.simulation.snapshot())
            except Exception:
                logging.exception('Failed to read simulation state')
                self._json({'error': 'Khong doc duoc trang thai mo phong. Kiem tra terminal cua server.'}, 500)
            return
        if urlsplit(self.path).path.startswith('/api/'):
            self._json({'error': 'Unknown API endpoint'}, 404)
            return
        # Only serve public website assets, never Python source or Git metadata.
        path = urlsplit(self.path).path
        if path in REPORTS:
            target = REPORTS[path].resolve()
            if not target.is_relative_to((ROOT/'outputs').resolve()) or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path not in ('/', '/index.html', '/network.html') and not path.startswith(('/js/', '/css/', '/assets/')):
            self.send_error(404)
            return
        resolved = Path(self.translate_path(self.path)).resolve()
        if not resolved.is_relative_to(WEB) or not resolved.is_file() and path != '/':
            self.send_error(404)
            return
        if path.startswith(('/js/', '/css/', '/assets/')):
            allowed = {'/js/': WEB / 'js', '/css/': WEB / 'css', '/assets/': WEB / 'assets'}
            base = next(base for prefix, base in allowed.items() if path.startswith(prefix))
            if not resolved.is_relative_to(base):
                self.send_error(404)
                return
        super().do_GET()

    def end_headers(self):
        # Avoid stale dashboard modules after local code changes.
        if not urlsplit(self.path).path.startswith('/assets/'):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_POST(self):
        path = urlsplit(self.path).path
        optimization = path.startswith('/api/optimizer/')
        if path not in ('/api/reset', '/api/step', '/api/optimizer/reset', '/api/optimizer/optimize', '/api/optimizer/transmit', '/api/optimizer/advance', '/api/optimizer/scenario'):
            self._json({'error': 'Unknown endpoint'}, 404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('Expected a JSON object, maximum 64 KiB')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            with self.server.state_lock:
                if optimization:
                    session = self.server.optimizer
                    if path.endswith('/scenario'):
                        if set(data) != {'scenario_id'}:
                            raise ValueError('Only scenario_id is accepted')
                        replacement,info = scenarios.load(data['scenario_id'])
                        snapshot = replacement.snapshot()
                        self.server.optimizer = replacement
                        result = {**info,'state':snapshot}
                    elif path.endswith('/reset'):
                        if data.get('deployment','distributed') != 'distributed':
                            raise ValueError('Only distributed station placement is available')
                        if data.get('constellation','balanced') not in ('compact','balanced','dense'):
                            raise ValueError('Choose compact, balanced or dense constellation')
                        self.server.optimizer = OptimizerSession(**data)
                        result = self.server.optimizer.snapshot()
                    elif path.endswith('/optimize'):
                        if set(data)-{'request', 'method', 'seed', 'budget'}:
                            raise ValueError('Unknown optimization option')
                        result = session.search(Demand(**data.get('request', {})), data.get('method', 'aco'),
                                                data.get('seed', 42), Budget(**data.get('budget', {})))
                    elif path.endswith('/transmit'):
                        if set(data) != {'plan_id'}:
                            raise ValueError('Expected plan_id only')
                        result = session.transmit(data['plan_id'])
                    else:
                        if set(data) != {'seconds'}:
                            raise ValueError('Expected seconds only')
                        result = session.advance(data['seconds'])
                    self._json(result)
                    return
                elif path == '/api/reset':
                    self.server.simulation = PacketSimulation(SimulationConfig(**data))
                else:
                    if set(data) - {'steps', 'action'}:
                        raise ValueError('Unknown step option')
                    steps = data.get('steps', 1)
                    if type(steps) is not int or not 1 <= steps <= 20:
                        raise ValueError('steps must be an integer in [1, 20]')
                    if data.get('action') is not None and steps != 1:
                        raise ValueError('Custom action requires steps=1')
                    for _ in range(steps):
                        self.server.simulation.step(data.get('action'))
                self._json(self.server.simulation.snapshot())
        except (ValueError, TypeError) as error:
            self._json({'error': str(error)}, 400)
        except Exception:
            logging.exception('Simulation API failed for %s', path)
            self._json({'error': 'Mo phong gap loi noi bo. Nhan Ket noi lai de doc trang thai; xem terminal server de biet chi tiet.'}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = SimulationServer(('127.0.0.1', args.port))
    print(f'SAGSIN simulation: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
