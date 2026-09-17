"""Offline macOS integration tests. Every write stays in a temporary home."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('bridge', ROOT / 'src/macos/bridge.py')
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)

STUB = r'''
import base64, json, os, pathlib, sys, time
args = sys.argv[1:]
if args == ['debug', 'models', '--bundled']:
    print(json.dumps({'models': [{'slug': 'gpt-5.4', 'effective_context_window_percent': 95}]}))
elif args == ['--version']:
    print('codex-cli 0.154.0')
else:
    home = pathlib.Path(os.environ['CODEX_HOME'])
    capture = {'args': args, 'home': str(home),
               'key_present': bool(os.environ.get('BRIDGE_TEST_KEY')),
               'openai_key_present': 'OPENAI_API_KEY' in os.environ,
               'cache': json.loads((home / 'models_cache.json').read_text()) if (home / 'models_cache.json').exists() else None}
    pathlib.Path(os.environ['BRIDGE_TEST_CAPTURE']).write_text(json.dumps(capture))
    if os.environ.get('BRIDGE_TEST_WAIT'):
        pathlib.Path(os.environ['BRIDGE_TEST_WAIT']).write_text(str(os.getpid()))
        time.sleep(60)
    if '--output-last-message' in args:
        pathlib.Path(args[args.index('--output-last-message') + 1]).write_text('PROVIDER_SMOKE_OK')
    if args[-1].startswith('Use built-in image generation'):
        generated = home / 'generated_images'
        generated.mkdir(exist_ok=True)
        data = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=')
        for i in range(int(os.environ.get('BRIDGE_TEST_IMAGE_COUNT', '1'))):
            (generated / ('result-' + str(time.time_ns()) + '.png')).write_bytes(data)
    sys.exit(int(os.environ.get('BRIDGE_TEST_EXIT', '0')))
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS runtime')
class MacBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bridge mac test ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        # Include spaces, apostrophes, Unicode and shell metacharacters in paths.
        self.provider = self.home / "provider's $(literal) Türkçe"
        self.gpt = self.home / 'normal codex'
        self.gpt.mkdir()
        (self.gpt / 'sentinel').write_text('untouched')
        self.bin = self.home / 'bin space'
        self.broker = self.home / 'broker'
        self.project = self.home / 'sample project'
        self.project.mkdir()
        self.capture = self.root / 'capture.json'
        stub_bin = self.root / 'stub'
        stub_bin.mkdir()
        executable = stub_bin / 'codex'
        executable.write_text('#!' + sys.executable + '\n' + STUB)
        executable.chmod(0o700)
        self.env = dict(os.environ, HOME=str(self.home), ZDOTDIR=str(self.home),
                        PATH=str(stub_bin) + os.pathsep + os.environ['PATH'],
                        BRIDGE_TEST_CAPTURE=str(self.capture))
        self.env.pop('BRIDGE_TEST_KEY', None)
        self.flags = ['--provider-codex-home', str(self.provider), '--gpt-codex-home', str(self.gpt),
                      '--install-bin', str(self.bin), '--broker-root', str(self.broker),
                      '--api-key-environment-variable', 'BRIDGE_TEST_KEY']
        self.command = [str(ROOT / 'setup.sh')]

    def run_command(self, command, expected=0, env=None):
        result = subprocess.run(command, env=env or self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return result

    def setup_command(self, action, *flags, expected=0):
        return self.run_command(self.command + [action] + self.flags + list(flags), expected)

    def install(self, *flags):
        self.setup_command('install', *flags)
        return bridge.read_json(self.provider / '.bridge/install.json')

    def with_key(self):
        return dict(self.env, BRIDGE_TEST_KEY='test-value-not-a-secret')

    def request(self, **changes):
        request = dict(project_id='sample', task_id='image-task', operation='generate',
                       prompt='Create an original landscape background.', reference_images=[], max_images=1)
        request.update(changes)
        path = self.project / 'request.json'
        path.write_text(json.dumps(request))
        return path

    def register(self, policy='staging'):
        self.setup_command('register-project', '--project-root', str(self.project),
                           '--project-id', 'sample', '--delivery-policy', policy)

    def image_command(self, request, *flags, expected=0, env=None):
        return self.run_command([str(self.bin / 'codex-image'), '--request-path', str(request)] + list(flags), expected, env)

    def test_install_catalog_profile_and_reinstall(self):
        self.install('--plan-reasoning-effort', 'high')
        catalog = bridge.read_json(self.provider / 'models_cache.json')
        self.assertEqual(catalog['client_version'], '0.154.0')
        self.assertEqual([m['slug'] for m in catalog['models']], ['deepseek-flash', 'deepseek-v4-pro'])
        self.assertTrue(all(m['auto_review_model_override'] == 'deepseek-flash' for m in catalog['models']))
        self.assertEqual([m['input_modalities'] for m in catalog['models']], [['text', 'image'], ['text']])
        self.assertEqual([m['supports_image_detail_original'] for m in catalog['models']], [True, False])
        config = (self.provider / 'config.toml').read_text()
        self.assertNotIn('approvals_reviewer', config)
        self.assertIn('plan_mode_reasoning_effort = "high"', config)
        self.assertIn('model_auto_compact_token_limit = 900000', config)
        self.install('--approvals-reviewer', 'auto_review')
        self.assertIn('approvals_reviewer = "auto_review"', (self.provider / 'config.toml').read_text())
        profile = (self.home / '.zprofile').read_text()
        self.assertEqual(profile.count('# >>>'), 1)
        self.assertEqual((self.gpt / 'sentinel').read_text(), 'untouched')

    def test_argument_boundaries_all_levels_and_exit_code(self):
        self.install('--skip-path-update', '--plan-reasoning-effort', 'high')
        prompt = 'Preserve --low, "quotes", $HOME, `uname`, spaces and Türkçe'
        for level in bridge.LEVELS:
            self.run_command([str(self.bin / 'codex-deepseek'), '--' + level.upper(), 'exec', prompt, ''], env=self.with_key())
            capture = bridge.read_json(self.capture)
            self.assertEqual(capture['args'][-3:], ['exec', prompt, ''])
            self.assertIn('model_reasoning_effort=' + json.dumps(level), capture['args'])
            self.assertIn('plan_mode_reasoning_effort=' + json.dumps(level), capture['args'])
            self.assertIn('model_providers.deepseek.wire_api="responses"', capture['args'])
            self.assertEqual(capture['home'], str(self.provider))
        self.run_command([str(self.bin / 'codex-deepseek'), 'exec', prompt], expected=7,
                         env=dict(self.with_key(), BRIDGE_TEST_EXIT='7'))
        self.assertIn('plan_mode_reasoning_effort="high"', bridge.read_json(self.capture)['args'])
        self.assertFalse((self.home / '.zprofile').exists())

    def test_key_storage_permissions_and_missing_key(self):
        cfg = self.install()
        self.run_command([str(self.bin / 'codex-deepseek')], expected=1)
        with patch.dict(os.environ, self.env, clear=True), patch.object(bridge.getpass, 'getpass', return_value='test-key'), contextlib.redirect_stdout(io.StringIO()):
            bridge.set_key(cfg)
        path = bridge.key_path(cfg)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.run_command([str(self.bin / 'codex-deepseek'), 'exec', 'hello'])
        self.assertTrue(bridge.read_json(self.capture)['key_present'])
        path.chmod(0o644)
        self.run_command([str(self.bin / 'codex-deepseek')], expected=1)

    def test_cache_refresh_before_launch_and_repeated_refresh(self):
        self.install()
        path = self.provider / 'models_cache.json'
        original = bridge.read_json(path)
        original['fetched_at'] = '2000-01-01T00:00:00Z'
        bridge.write_json(path, original)
        self.run_command([str(self.bin / 'codex-deepseek'), 'exec', 'hello'], env=self.with_key())
        fresh = bridge.read_json(self.capture)['cache']
        self.assertNotEqual(fresh['fetched_at'], original['fetched_at'])
        self.assertEqual(fresh['models'], original['models'])
        stop = threading.Event()
        thread = threading.Thread(target=bridge.keep_cache, args=(path, stop, 0.01))
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while bridge.read_json(path)['fetched_at'] == fresh['fetched_at'] and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertNotEqual(bridge.read_json(path)['fetched_at'], fresh['fetched_at'])
        finally:
            stop.set()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        path.unlink()
        self.run_command([str(self.bin / 'codex-deepseek')], expected=1, env=self.with_key())

    def test_termination_reaches_codex(self):
        self.install()
        pid_file = self.root / 'pid'
        process = subprocess.Popen([str(self.bin / 'codex-deepseek'), 'exec', 'hello'],
                                   env=dict(self.with_key(), BRIDGE_TEST_WAIT=str(pid_file)),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(pid_file.exists())
            process.terminate()
            self.assertEqual(process.wait(timeout=5), 128 + signal.SIGTERM)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_registered_broker_generate_and_edit(self):
        self.install()
        self.register()
        request = self.request()
        validated = self.image_command(request, '--validate-only')
        self.assertEqual(json.loads(validated.stdout)['status'], 'validated')
        self.assertFalse((self.gpt / 'generated_images').exists())
        result = self.image_command(request, env=dict(self.with_key(), OPENAI_API_KEY='test-only'))
        manifest = json.loads(result.stdout)
        artifact = manifest['artifacts'][0]
        self.assertEqual((artifact['width'], artifact['height']), (1, 1))
        self.assertEqual(len(artifact['sha256']), 64)
        self.assertFalse(manifest['production_approved'])
        capture = bridge.read_json(self.capture)
        self.assertEqual(capture['home'], str(self.gpt))
        self.assertFalse(capture['key_present'])
        self.assertFalse(capture['openai_key_present'])
        request = self.request(operation='edit', reference_images=[artifact['path']])
        self.image_command(request)
        self.assertIn('--image', bridge.read_json(self.capture)['args'])
        self.image_command(request, expected=1, env=dict(self.env, BRIDGE_TEST_IMAGE_COUNT='2'))

    def test_approval_policy_and_request_boundaries(self):
        self.install()
        self.register('approval-before-copy')
        result = self.image_command(self.request())
        artifact = json.loads(result.stdout)['artifacts'][0]['path']
        self.assertTrue(bridge.inside(self.broker / 'outputs', artifact))
        self.assertFalse((self.project / bridge.STAGING).exists())
        self.image_command(self.request(output_directory='Saved/AI_Temp/DelegatedImages/test'), '--validate-only', expected=1)
        self.register()
        for changes in ({'project_id': 'other'}, {'task_id': '../escape'}, {'unknown': True},
                        {'operation': 'edit'}, {'max_images': True}, {'max_images': 5},
                        {'reference_images': ['../../outside.png']}, {'output_directory': '../escape'},
                        {'prompt': 'x'}, {'reference_images': 'wrong-type'}):
            with self.subTest(changes=changes):
                self.image_command(self.request(**changes), '--validate-only', expected=1)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'image.png').write_bytes(b'not-important')
        (self.project / 'link').symlink_to(outside, target_is_directory=True)
        self.image_command(self.request(reference_images=['link/image.png']), '--validate-only', expected=1)
        (self.project / 'Saved').symlink_to(outside, target_is_directory=True)
        self.image_command(self.request(), '--validate-only', expected=1)

    def test_broker_lock(self):
        self.install()
        self.register()
        with (self.broker / 'image.lock').open('w') as lock:
            bridge.fcntl.flock(lock, bridge.fcntl.LOCK_EX | bridge.fcntl.LOCK_NB)
            self.image_command(self.request(), expected=1)

    def test_uninstall_preview_and_owned_paths(self):
        self.install()
        self.register()
        (self.home / '.zprofile').write_text('# user settings\n' + (self.home / '.zprofile').read_text())
        self.setup_command('uninstall', '--what-if')
        self.assertTrue(self.provider.exists())
        self.setup_command('uninstall')
        self.assertFalse(self.provider.exists())
        self.assertFalse((self.bin / 'codex-deepseek').exists())
        self.assertTrue((self.bin / 'codex-image').exists())
        self.assertTrue(self.broker.exists())
        self.assertTrue(self.project.exists())
        self.assertEqual((self.gpt / 'sentinel').read_text(), 'untouched')
        self.assertEqual((self.home / '.zprofile').read_text(), '# user settings\n')

    def test_refuse_unowned_and_overlapping_paths(self):
        self.provider.mkdir()
        (self.provider / 'important').write_text('preserve')
        self.setup_command('install', expected=1)
        self.setup_command('uninstall', expected=1)
        self.assertEqual((self.provider / 'important').read_text(), 'preserve')
        self.setup_command('install', '--provider-codex-home', str(self.gpt), expected=1)
        self.setup_command('install', '--command-name', 'codex', expected=1)
        self.setup_command('install', '--provider-name', 'nested.provider', expected=1)

    def test_diagnostics_and_live_smoke_with_stub(self):
        self.install()
        self.setup_command('test', expected=1)
        result = self.run_command(self.command + ['test'] + self.flags + ['--live-test'], env=self.with_key())
        self.assertEqual(json.loads(result.stdout)['live_test'], 'passed')


if __name__ == '__main__':
    unittest.main()
