import importlib.util
import unittest
from pathlib import Path


class DataTests(unittest.TestCase):
    def test_launch_adapter_uses_existing_factory_overrides(self):
        path = Path(__file__).with_name('entrypoint.py')
        self.assertTrue(path.exists(), 'model launch adapter must exist')
        spec = importlib.util.spec_from_file_location('entrypoint', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []
        def factory(name, **overrides):
            calls.append((name, overrides))
            return 'existing-model-adapter'
        wrapped = module.configured_factory(factory)
        self.assertEqual(wrapped('deepseek-flash'), 'existing-model-adapter')
        self.assertEqual(calls[0][1]['default_request_args']['extra_body']['thinking']['type'], 'disabled')
        self.assertEqual(calls[0][1]['max_tokens'], 4096)

    def test_report_verifier_rejects_omitted_transport_and_wrong_daily_cost(self):
        path = Path(__file__).with_name('verify.py')
        spec = importlib.util.spec_from_file_location('verify', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'verify_case'), 'independent per-case verification is required')
        plan = {'itinerary': [{'day': 1, 'activities': [{'cost': 10, 'transports': [{'cost': 3}]}]}]}
        with self.assertRaises(AssertionError):
            module.verify_case(plan, {'activities': 1, 'transports': 0}, '13', {'1': '13'})
        with self.assertRaises(AssertionError):
            module.verify_case(plan, {'activities': 1, 'transports': 1}, '13', {'1': '10'})
        module.verify_case(plan, {'activities': 1, 'transports': 1}, '13', {'1': '13'})

    def test_csv_types_and_escaped_dsl(self):
        path = Path(__file__).with_name('prepare.py')
        self.assertTrue(path.exists(), 'preparation module must exist')
        spec = importlib.util.spec_from_file_location('prepare', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        row = {'days': '3', 'people_number': '2', 'limit_rooms': 'False',
               'limits_room_type': 'True',
               'hard_logic_py': repr(['result=True\\nfor x in []:\\n  result=False'])}
        actual = module.normalize(row)
        self.assertEqual(actual['days'], 3)
        self.assertIs(actual['limit_rooms'], False)
        self.assertIs(actual['limits_room_type'], True)
        self.assertEqual(actual['hard_logic_py'], ['result=True\nfor x in []:\n  result=False'])
        compile(actual['hard_logic_py'][0], '<dsl>', 'exec')


if __name__ == '__main__':
    unittest.main()
