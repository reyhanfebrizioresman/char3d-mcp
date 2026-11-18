"""Director contracts: no network, subprocesses or Blender. Run directly."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anthropic
import httpx2
from engine.cinematic import PRESETS
from engine.script_plan import parse_script
from providers.director import direct, status
from providers.director import claude, claude_cli
from providers.director.common import SCHEMA, options
from providers.director.offline import Backend as Offline
from providers.director.prompts import SYSTEM, system_blocks

IDEAS = [
    'dua sahabat bertemu lagi di taman saat senja setelah 10 tahun, haru',
    'ibu dan anak berpamitan di ruang keluarga',
    'guru dan tiga murid belajar di kelas pagi hari',
    'empat rekan kerja berdebat di kantor, mendung',
    'satu presenter menjelaskan produk di panggung',
    'wawancara podcast tentang memulai lagi',
    'pasangan mengaku cinta di pantai pada jam biru',
    'tiga teman komedi di kafe saat hujan',
    'perayaan kemenangan dua atlet di jalan kota, epik',
    'seorang pria berusia 67 tahun monolog di taman berkabut',
    'Two friends reunite at a beach at night',
    'Four colleagues pitch a product in an office',
    'One teacher gives a lesson in a classroom on a snowy morning',
    'Three women celebrate a birthday at a windy cafe',
    'A mother and child say goodbye at home',
    'Naya dan Bima berdebat di kantor, hujan',
    'fantasy dream in a mountain kitchen',
]


def draft():
    return Offline().generate(options('dua sahabat di taman', characters=2))


def response(payload=None, stop='end_turn', usage=None):
    return NS(model='claude-opus-5-5', stop_reason=stop,
              usage=NS(model_dump=lambda: usage or {'input_tokens': 1000, 'output_tokens': 500,
                         'cache_creation_input_tokens': 100, 'cache_read_input_tokens': 200}),
              content=[NS(type='text', text=json.dumps(payload or draft()))])


class OfflineTests(unittest.TestCase):
    def test_optional_multi_scene_film(self):
        from engine.film_plan import parse_film
        result = direct('Dua sahabat di kafe pagi lalu taman sore dan street malam', generator='offline', duration_s=60)
        self.assertEqual(len(result['plan']['scenes']), 3)
        self.assertEqual(result['plan'], parse_film(result['script']))
        self.assertEqual(result['build_options']['tool'], 'script_to_film')

    def test_varied_ideas_all_looks_and_weather(self):
        for i, idea in enumerate(IDEAS):
            with self.subTest(idea=idea):
                result = direct(idea, generator='offline', seed=i, language='en' if i >= 10 and i <= 14 else 'id')
                plan = parse_script(result['script'], seed=i)
                self.assertEqual(plan['warnings'], [])
                self.assertEqual(plan, result['plan'])
                self.assertTrue(result['brief'].startswith('# '))
                self.assertIn('## ', result['brief'])
                self.assertEqual(result['generator'], 'offline')
                self.assertNotIn('cost_usd_estimate', result)
        for look in [*PRESETS, 'none']:
            for count in range(1, 5):
                with self.subTest(look=look, count=count):
                    result = direct('adegan pendek', generator='offline', look=look, characters=count)
                    self.assertEqual(len(result['plan']['characters']), count)
                    self.assertEqual((result['plan']['look'] or {}).get('preset', 'none'), look)
                    self.assertFalse(result['plan']['warnings'])
        for idea, weather in [('hujan', 'rain'), ('snow', 'snow'), ('fog', 'fog'), ('wind', 'wind'), ('cerah', 'clear')]:
            self.assertEqual(direct(idea, generator='offline')['plan']['weather'], weather)

    def test_deterministic_and_variation(self):
        a = direct(IDEAS[0], generator='offline', seed=7)
        self.assertEqual(a, direct(IDEAS[0], generator='offline', seed=7))
        self.assertNotEqual(a['script'], direct(IDEAS[0], generator='offline', seed=8)['script'])
        self.assertTrue(all(c['age'] >= 30 for c in a['plan']['characters']))
        named = direct('Naya dan Bima bertemu di pantai', generator='offline')
        self.assertEqual([c['id'] for c in named['plan']['characters']], ['Naya', 'Bima'])
        family = direct(IDEAS[1], generator='offline')['plan']['characters']
        self.assertEqual([c['age'] for c in family], [42, 13])

    def test_bad_options_and_consent_rejected(self):
        for kwargs in [dict(idea=''), dict(idea='x', characters=5), dict(idea='x', duration_s=float('nan')),
                       dict(idea='x', location='spaceship'), dict(idea='x', generator='unknown')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                direct(**kwargs)
        for generator in ('claude', 'claude_cli'):
            with self.assertRaisesRegex(ValueError, 'Persetujuan'):
                direct('halo', generator=generator)


class APITests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = [response()]
        owner = self
        class Client:
            def __init__(self, **kwargs):
                owner.client_args = kwargs
                self.beta = NS(messages=NS(create=self.create))
                self.messages = NS(create=self.create)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def create(self, *, fallbacks=None, output_config=None, **kwargs):
                owner.calls.append(dict(fallbacks=fallbacks, output_config=output_config, **kwargs))
                value = owner.responses.pop(0)
                if isinstance(value, Exception): raise value
                return value
        self.client_patch = patch.object(anthropic, 'Anthropic', Client)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        p = patch.object(claude.Backend, 'available', return_value=True)
        p.start(); self.addCleanup(p.stop)

    def generate(self):
        return direct('dua sahabat di taman', generator='claude', characters=2, consent=True)

    def test_success_sdk_contract_cost_cache_and_stability(self):
        result = self.generate()
        self.assertEqual(result['generator'], 'claude')
        self.assertEqual(result['cost_usd_estimate'], .01454)
        call = self.calls[0]
        self.assertEqual(call['fallbacks'], 'default')
        self.assertEqual(call['betas'], ['server-side-fallback-2026-07-01'])
        self.assertEqual(call['output_config'], {'effort': 'medium', 'format': {'type': 'json_schema', 'schema': SCHEMA}})
        self.assertEqual(call['max_tokens'], 16000)
        self.assertFalse(call['stream'])
        self.assertFalse({'thinking', 'budget_tokens', 'temperature', 'top_p'} & call.keys())
        self.assertEqual(self.client_args['timeout'], 180)
        self.assertEqual(call['system'], system_blocks())
        before = json.dumps(call['system'])
        self.responses = [response()]
        direct('A completely different idea', generator='claude', consent=True)
        self.assertEqual(before, json.dumps(self.calls[-1]['system']))
        self.assertEqual(system_blocks()[0]['cache_control'], {'type': 'ephemeral'})
        self.assertGreater(len(SYSTEM), 12000)
        self.responses = [response()]
        with patch.dict(os.environ, {'CHAR3D_DIRECTOR_EFFORT': 'high', 'CHAR3D_DIRECTOR_MODEL': 'custom-model'}):
            self.generate()
        self.assertEqual(self.calls[-1]['model'], 'custom-model')
        self.assertEqual(self.calls[-1]['output_config']['effort'], 'high')

    def test_stop_reason_before_reading_content(self):
        class Stopped:
            model = 'claude-opus-5-5'
            usage = response().usage
            @property
            def content(self): raise AssertionError('Do not read stopped content')
        for stop in ('refusal', 'max_tokens'):
            value = Stopped(); value.stop_reason = stop
            self.responses = [value]
            result = self.generate()
            self.assertEqual(result['generator'], 'offline')
            self.assertIn('offline', ' '.join(result['warnings']))
            self.assertEqual(result['usage']['output_tokens'], 500)

    def test_invalid_script_one_repair_and_no_third_call(self):
        broken = draft(); broken['script'] += '\n[Ayu menghilang]'
        self.responses = [response(broken), response()]
        result = self.generate()
        self.assertEqual(result['generator'], 'claude')
        self.assertEqual(len(self.calls), 2)
        self.assertIn('Unknown stage direction', self.calls[1]['messages'][0]['content'])
        self.assertEqual(result['usage']['output_tokens'], 1000)
        self.calls.clear()
        invalid = draft(); invalid['script'] = 'tidak valid'
        self.responses = [response(invalid), response(invalid)]
        self.assertEqual(self.generate()['generator'], 'offline')
        self.assertEqual(len(self.calls), 2)

    def test_unknown_descriptors_repaired(self):
        broken = draft(); broken['script'] = broken['script'].replace('perempuan,', 'lembut sekali, perempuan,', 1)
        self.responses = [response(broken), response()]
        self.generate()
        self.assertEqual(len(self.calls), 2)
        self.assertIn('unknown descriptors', self.calls[-1]['messages'][0]['content'])

    def test_typed_errors_friendly_and_secrets_never_echoed(self):
        req = httpx2.Request('POST', 'https://api.anthropic.com/v1/messages')
        for cls, status_code, hint in [(anthropic.AuthenticationError, 401, 'Autentikasi'),
                                       (anthropic.RateLimitError, 429, 'kuota'),
                                       (anthropic.APIStatusError, 500, 'kesalahan')]:
            self.responses = [cls('secret-sentinel', response=httpx2.Response(status_code, request=req), body={'key': 'secret-sentinel'})]
            with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'secret-sentinel'}), patch.object(logging.Logger, '_log') as logs:
                result = self.generate()
                self.assertEqual(result['generator'], 'offline')
                self.assertIn(hint, ' '.join(result['warnings']))
                self.assertNotIn('secret-sentinel', json.dumps(result))
                self.assertNotIn('secret-sentinel', str(logs.call_args_list))
        self.responses = [anthropic.APIConnectionError(request=req)]
        self.assertIn('terhubung', ' '.join(self.generate()['warnings']))
        payload = draft(); payload['brief'] += '\nsecret-sentinel'
        self.responses = [response(payload)]
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'secret-sentinel'}):
            self.assertNotIn('secret-sentinel', json.dumps(self.generate()))

    def test_auto_selection_never_switches_to_api_after_cli_failure(self):
        with patch.object(claude_cli.Backend, 'available', return_value=True), patch.object(claude_cli.Backend, 'generate', side_effect=RuntimeError('bad')):
            result = direct('halo', consent=True)
            self.assertEqual(result['generator'], 'offline')
            self.assertEqual(result['requested_generator'], 'claude_cli')
            self.assertEqual(self.calls, [])
        with patch.object(claude_cli.Backend, 'available', return_value=False):
            self.assertEqual(direct('halo', consent=True)['generator'], 'claude')
        self.assertEqual(direct('halo')['generator'], 'offline')


class CLITests(unittest.TestCase):
    def test_success_envelope_and_isolation(self):
        envelope = dict(type='result', is_error=False, structured_output=draft(), result='',
                        usage={'input_tokens': 150, 'output_tokens': 600}, total_cost_usd=.123,
                        modelUsage={'claude-opus-5-5': {}})
        def run(argv, **kwargs):
            self.assertEqual(list(Path(kwargs['cwd']).iterdir()), [])
            self.assertFalse(Path(kwargs['cwd']).is_relative_to(Path.cwd()))
            self.assertEqual(argv[argv.index('--tools') + 1], '')
            self.assertEqual(json.loads(argv[argv.index('--mcp-config') + 1]), {'mcpServers': {}})
            for flag in ('--strict-mcp-config', '--no-session-persistence', '--safe-mode'):
                self.assertIn(flag, argv)
            self.assertNotIn('--bare', argv)
            self.assertNotIn('my private idea', ' '.join(argv))
            self.assertNotIn('secret-sentinel', json.dumps(argv))
            self.assertNotIn('ANTHROPIC_API_KEY', kwargs['env'])
            self.assertIn('my private idea', kwargs['input'])
            self.assertEqual(kwargs['timeout'], 300)
            return NS(returncode=0, stdout=json.dumps(envelope), stderr='')
        with patch.object(claude_cli, 'discover', return_value='/fake/claude'), patch.object(subprocess, 'run', side_effect=run), patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'secret-sentinel'}):
            result = direct('my private idea', generator='claude_cli', consent=True)
        self.assertEqual(result['generator'], 'claude_cli')
        self.assertEqual(result['billing'], 'subscription')
        self.assertNotIn('cost_usd_estimate', result)
        self.assertNotIn('total_cost_usd', result)
        self.assertEqual(result['model'], 'claude-opus-5-5')

    def test_login_timeout_and_repair(self):
        envelopes = [NS(returncode=1, stdout=json.dumps({'type': 'result', 'is_error': True, 'result': 'Not logged in · Please run /login', 'usage': {}}), stderr='')]
        with patch.object(claude_cli, 'discover', return_value='/fake/claude'), patch.object(subprocess, 'run', side_effect=envelopes):
            result = direct('hi', generator='claude_cli', consent=True)
            self.assertEqual(result['generator'], 'offline')
            self.assertIn('terminal lalu login', ' '.join(result['warnings']))
        with patch.object(claude_cli, 'discover', return_value='/fake/claude'), patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('claude', 300)):
            self.assertIn('5 menit', ' '.join(direct('hi', generator='claude_cli', consent=True)['warnings']))
        invalid = draft(); invalid['script'] = 'bad script'
        envelopes = [NS(returncode=0, stdout=json.dumps({'structured_output': payload, 'usage': {}}), stderr='') for payload in (invalid, draft())]
        with patch.object(claude_cli, 'discover', return_value='/fake/claude'), patch.object(subprocess, 'run', side_effect=envelopes) as mocked:
            self.assertEqual(direct('hi', generator='claude_cli', consent=True)['generator'], 'claude_cli')
            self.assertEqual(mocked.call_count, 2)

    def test_binary_discovery_versions_and_overrides(self):
        with tempfile.TemporaryDirectory() as root:
            for version in ('2.1.9', '2.1.321', '2.1.30'):
                binary = Path(root) / '.config/Claude/claude-code' / version / 'hash/claude'
                binary.parent.mkdir(parents=True); binary.touch(); binary.chmod(0o700)
            with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=Path(root)), patch.object(claude_cli.shutil, 'which', return_value=None):
                self.assertIn('/2.1.321/', claude_cli.discover())
                with patch.dict(os.environ, {'CHAR3D_CLAUDE_BIN': str(binary)}):
                    self.assertEqual(claude_cli.discover(), str(binary))


class StatusTests(unittest.TestCase):
    def test_status_no_network_no_secrets_and_profiles(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'ANTHROPIC_CONFIG_DIR': root}, clear=True), patch.object(anthropic.resources.beta.messages.Messages, 'create', side_effect=AssertionError('network')):
            self.assertFalse(status()['generators']['claude']['configured'])
            with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'secret-sentinel'}):
                result = status()
                self.assertTrue(result['generators']['claude']['configured'])
                self.assertNotIn('secret-sentinel', json.dumps(result))
        # SDK local profile discovery, without requesting any access token.
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'ANTHROPIC_CONFIG_DIR': root}, clear=True):
            cfg = Path(root) / 'configs/default.json'; cfg.parent.mkdir()
            cfg.write_text(json.dumps({'authentication': {'type': 'user_oauth'}})); cfg.chmod(0o600)
            credentials = Path(root) / 'credentials/default.json'; credentials.parent.mkdir()
            credentials.write_text(json.dumps({'access_token': 'profile-secret'})); credentials.chmod(0o600)
            result = status()
            self.assertTrue(result['generators']['claude']['configured'])
            self.assertNotIn('profile-secret', json.dumps(result))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if not result.wasSuccessful(): sys.exit(1)
    print('DIRECTOR UNIT OK')
