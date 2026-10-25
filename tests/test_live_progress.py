import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
import test_control
from embedded_agent.server import make_server
from embedded_agent.contracts import CONTRACTS, validate_shape
from test_power import model


class LiveProgressTests(unittest.TestCase):
    def test_progress_responds_while_model_is_waiting(self):
        fixture = test_control.ControlTests(); fixture.setUp()
        entered, release = threading.Event(), threading.Event()
        class Provider:
            def decide(self, context):
                entered.set(); release.wait(5)
                return {'kind': 'pause', 'reason': 'fixture response complete'}
        server = None
        try:
            run = fixture.prepared()
            server = make_server(fixture.root, port=0, decision_provider=Provider())
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = 'http://127.0.0.1:'+str(server.server_port)+'/runs/'+run['id']
            def invoke():
                with urlopen(Request(base+'/auto', b'{}', {'Content-Type':'application/json'}), timeout=8) as response:
                    return json.load(response)
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(invoke)
                self.assertTrue(entered.wait(3))
                try:
                    with urlopen(base+'/progress', timeout=1) as response: state = json.load(response)
                    self.assertEqual(state['phase'], 'model')
                    self.assertTrue(state['busy'])
                    self.assertFalse(future.done())
                finally: release.set()
                self.assertEqual(future.result()['status'], 'paused')
            with urlopen(base+'/progress') as response:
                self.assertFalse(json.load(response)['busy'])
        finally:
            release.set()
            if server: server.shutdown(); server.server_close(); thread.join()
            fixture.tearDown()

    def test_power_schema_identifies_missing_boundary_and_duration(self):
        valid = {'candidate_id':'fixture', 'model':model()}
        validate_shape(CONTRACTS['power_estimate'], valid)
        del valid['model']['power_boundary']
        with self.assertRaisesRegex(ValueError, r'arguments.model.power_boundary'):
            validate_shape(CONTRACTS['power_estimate'], valid)
        valid['model']['power_boundary']='whole_load_bus'
        valid['model']['states'][0]['duration_s']='remaining'
        with self.assertRaisesRegex(ValueError, r'arguments.model.states\[0\].duration_s'):
            validate_shape(CONTRACTS['power_estimate'], valid)


if __name__=='__main__': unittest.main()
