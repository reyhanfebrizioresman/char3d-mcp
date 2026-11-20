"""Loopback official-API stand-in. No real accounts, network outside loopback or cost."""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockCloud:
    def __init__(self):
        self.instances = {}
        self.calls = []
        self.fail = None
        self.price = .4
        self.allocated_price = None
        self.echo_key = False
        self.next_id = 100
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                path = urllib.parse.urlsplit(self.path).path.rstrip('/')
                mock.calls.append((self.command, path, body))
                expected = 'Bearer super-private-test-key'
                if self.headers.get('Authorization') != expected:
                    return self.reply(401, {'error': 'super-private-test-key'})
                if path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location','https://attacker.example/steal')
                    self.end_headers()
                    return
                if mock.fail == path:
                    return self.reply(500, {'error': 'super-private-test-key'})
                if path.endswith('/graphql'):
                    return self.reply(200, {'data': {'gpuTypes': [{'id': 'Test GPU', 'displayName': 'Test GPU',
                        'securePrice': mock.price, 'communityPrice': mock.price}]}})
                if path.endswith('/billing/pods'):
                    ident = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)['podId'][0]
                    return self.reply(200, [{'podId':ident,'amount':.001,'timeBilledMs':9000}])
                if path.endswith('/bundles'):
                    return self.reply(200, {'offers': [{'id': 1, 'gpu_name': 'Test GPU', 'num_gpus': 1,
                        'dph_total': mock.price, 'inet_up_cost': 0, 'inet_down_cost': 0, 'storage_cost': 0}]})
                if path.endswith('/ssh'):
                    return self.reply(200, {'success':True})
                if self.command == 'POST' and path.endswith('/pods') or self.command == 'PUT' and '/asks/' in path:
                    mock.next_id += 1
                    ident = str(mock.next_id)
                    rate = mock.price if mock.allocated_price is None else mock.allocated_price
                    mock.instances[ident] = dict(id=ident, name=body.get('name'), label=body.get('label'),
                        costPerHr=rate, dph_total=rate, publicIp='loopback',
                        portMappings={'22': 2222}, ssh_host='loopback', ssh_port=2222,
                        totalCost=.001, billedSeconds=9)
                    return self.reply(200, {'id': ident, 'new_contract': int(ident)})
                if self.command == 'DELETE':
                    ident = path.split('/')[-1]
                    mock.instances.pop(ident, None)
                    return self.reply(200, {'success': True})
                if self.command == 'GET':
                    ident = path.split('/')[-1]
                    if ident in ('pods', 'instances'):
                        result = list(mock.instances.values())
                        return self.reply(200, result if ident == 'pods' else {'instances': result})
                    if ident not in mock.instances:
                        return self.reply(404, {})
                    return self.reply(200, mock.instances[ident])
                return self.reply(404, {})

            def reply(self, code, obj):
                if mock.echo_key:
                    obj = {'echo': 'super-private-test-key'}
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PUT = do_DELETE = handle_request

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
