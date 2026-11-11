"""Configure the existing model factory, then execute unchanged run_exp.py.

Only API request settings are supplied through create_llm's existing overrides.
No agent, prompt, search, WorldEnv or evaluator behavior is replaced.
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configured_factory(factory):
    def create(name, **overrides):
        overrides.setdefault('max_tokens', 4096)
        request_args = dict(overrides.get('default_request_args') or {})
        extra_body = dict(request_args.get('extra_body') or {})
        extra_body['thinking'] = {'type': 'disabled'}
        request_args['extra_body'] = extra_body
        overrides['default_request_args'] = request_args
        return factory(name, **overrides)
    return create


def main():
    sys.path.insert(0, str(ROOT))
    from run import configure
    configure()
    from chinatravel.agent import llms
    llms.create_llm = configured_factory(llms.create_llm)
    runpy.run_path(str(ROOT / 'run_exp.py'), run_name='__main__')


if __name__ == '__main__':
    main()
