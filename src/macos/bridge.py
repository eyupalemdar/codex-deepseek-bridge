#!/usr/bin/env python3
"""macOS installer and installed runtime. Uses only Python's standard library."""

import argparse
import copy
import datetime
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading


LEVELS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
OWNER = 'codex-deepseek-bridge-macos-v1'
STAGING = Path('Saved/AI_Temp/DelegatedImages')


def emit(value):
    print(json.dumps(value, indent=2))


def token(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', value):
        raise ValueError('Invalid identifier: ' + value)
    return value


def inside(root, path):
    """Resolve existing symlinks as well as .., including in output parents."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def bounded_path(root, value):
    path = (Path(root) / value).resolve()
    if not inside(root, path):
        raise ValueError('Path escapes registered root: ' + str(value))
    return path


def atomic_write(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2) + '\n')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def codex_path():
    executable = shutil.which('codex')
    if not executable:
        raise ValueError('Install Codex CLI and place codex on PATH first.')
    return executable


def catalog(cfg):
    executable = codex_path()
    bundled = json.loads(subprocess.check_output(
        [executable, 'debug', 'models', '--bundled'], text=True))
    template = next((m for m in bundled['models'] if m['slug'] == 'gpt-5.4'), None)
    if template is None:
        raise ValueError('Compatible bundled metadata template was not found.')
    models = []
    for priority, slug in enumerate(cfg['models'], 1):
        model = copy.deepcopy(template)
        model.update(
            slug=slug, display_name=slug.replace('-', ' '),
            description=cfg['provider_name'] + ' model exposed through a custom Codex provider.',
            default_reasoning_level=cfg['reasoning_effort'],
            supported_reasoning_levels=[dict(effort=e, description=e + ' reasoning') for e in LEVELS],
            visibility='list', priority=priority, additional_speed_tiers=[], service_tiers=[],
            availability_nux=None, upgrade=None, model_messages=None,
            base_instructions='You are a coding agent operating through Codex CLI. Follow the active '
            'system, developer, project, safety, permission, and user instructions. Use available '
            'tools carefully and work within the current workspace.',
            supports_image_detail_original=False, supports_search_tool=False,
            auto_review_model_override=cfg['default_model'], input_modalities=['text'],
            context_window=cfg['context_window'], max_context_window=cfg['context_window'])
        models.append(model)
    version = subprocess.check_output([executable, '--version'], text=True).split()[1]
    return dict(fetched_at=now(), etag='local-' + cfg['provider_name'] + '-catalog-v1',
                client_version=version, models=models)


def overrides(cfg, effort=None):
    provider = 'model_providers.' + cfg['provider_name']
    return {
        'model': cfg['default_model'],
        'model_reasoning_effort': effort or cfg['reasoning_effort'],
        'plan_mode_reasoning_effort': effort or cfg['plan_reasoning_effort'],
        'model_provider': cfg['provider_name'],
        'model_context_window': cfg['context_window'],
        'model_auto_compact_token_limit': cfg['context_window'] * 9 // 10,
        provider + '.name': cfg['provider_name'],
        provider + '.base_url': cfg['base_url'],
        provider + '.env_key': cfg['api_key_environment_variable'],
        provider + '.wire_api': 'responses',
    }


def config_text(cfg):
    values = overrides(cfg)
    values.update(web_search='disabled')
    if cfg['approvals_reviewer']:
        values['approvals_reviewer'] = cfg['approvals_reviewer']
    prefix = 'model_providers.' + cfg['provider_name']
    values.update({prefix + '.request_max_retries': 3, prefix + '.stream_max_retries': 3,
                   prefix + '.stream_idle_timeout_ms': 300000})
    # Quote each TOML key segment so identifiers containing dots stay literal.
    lines = []
    for key, value in values.items():
        if key.startswith(prefix + '.'):
            key = 'model_providers.' + json.dumps(cfg['provider_name']) + '.' + key[len(prefix) + 1:]
        lines.append(key + ' = ' + json.dumps(value, ensure_ascii=False))
    return '\n'.join(lines) + '\n'


def launcher_text(runtime, mode, config):
    command = [sys.executable, str(runtime), mode, str(config)]
    return '#!/bin/sh\n# ' + OWNER + '\nexec ' + shlex.join(command) + ' "$@"\n'


def write_launcher(path, runtime, mode, config):
    path = Path(path)
    if path.exists() and OWNER not in path.read_text(encoding='utf-8'):
        raise ValueError('Refusing to overwrite an unrelated command: ' + str(path))
    atomic_write(path, launcher_text(runtime, mode, config), 0o700)


def settings(args):
    cfg = vars(args).copy()
    for name in ('provider_codex_home', 'gpt_codex_home', 'install_bin', 'broker_root'):
        cfg[name] = str(Path(cfg[name]).expanduser().resolve())
    models = cfg['models'].split(',') if isinstance(cfg['models'], str) else cfg['models']
    cfg['models'] = [token(m) for m in models]
    token(cfg['provider_name'])
    if '.' in cfg['provider_name']:
        raise ValueError('Provider names cannot contain dots in Codex CLI override paths.')
    token(cfg['command_name'])
    if cfg['command_name'] in ('codex', 'codex-image'):
        raise ValueError('Command name is reserved.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cfg['api_key_environment_variable']):
        raise ValueError('Invalid environment variable name.')
    if cfg['default_model'] not in cfg['models']:
        raise ValueError('Default model must be included in models.')
    if not 16000 <= cfg['context_window'] <= 1000000:
        raise ValueError('Context window must be between 16000 and 1000000.')
    roots = [Path(cfg[k]) for k in ('provider_codex_home', 'gpt_codex_home', 'broker_root', 'install_bin')]
    for index, root in enumerate(roots):
        if root == Path.home().resolve() or root == Path('/'):
            raise ValueError('Use a dedicated installation directory.')
        for other in roots[index + 1:]:
            if inside(root, other) or inside(other, root):
                raise ValueError('Provider, ChatGPT, broker and bin directories must be separate.')
    cfg['owner'] = OWNER
    return cfg


def installation_path(cfg):
    return Path(cfg['provider_codex_home']) / '.bridge/install.json'


def saved_settings(args):
    cfg = settings(args)
    path = installation_path(cfg)
    if not path.is_file():
        raise ValueError('Install first using setup.sh install (with the same --provider-codex-home).')
    saved = read_json(path)
    if saved.get('owner') != OWNER or saved.get('provider_codex_home') != cfg['provider_codex_home']:
        raise ValueError('Installation ownership check failed.')
    return saved


def update_path(cfg, remove=False):
    profile = Path(cfg['shell_profile'])
    start = '# >>> ' + OWNER + ' ' + cfg['command_name'] + ' >>>'
    end = '# <<< ' + OWNER + ' ' + cfg['command_name'] + ' <<<'
    text = profile.read_text(encoding='utf-8') if profile.exists() else ''
    pattern = re.compile(re.escape(start) + r'\n.*?\n' + re.escape(end) + r'\n?', re.S)
    text = pattern.sub('', text)
    if not remove:
        text += ('' if not text or text.endswith('\n') else '\n') + start + '\nexport PATH=' + shlex.quote(cfg['install_bin']) + ':"$PATH"\n' + end + '\n'
    if profile.exists() or not remove:
        # Keep a user's existing profile permissions and symlink target.
        mode = profile.stat().st_mode & 0o777 if profile.exists() else 0o600
        atomic_write(profile.resolve(), text, mode)


def install(args):
    cfg = settings(args)
    provider = Path(cfg['provider_codex_home'])
    marker = installation_path(cfg)
    if provider.exists() and any(provider.iterdir()):
        if not marker.is_file() or read_json(marker).get('owner') != OWNER:
            raise ValueError('Provider home is not owned by this installer; choose an empty directory.')
    # Validate the CLI before changing files.
    model_catalog = catalog(cfg)
    previous = read_json(marker) if marker.exists() else {}
    cfg['shell_profile'] = previous.get('shell_profile', str(Path(os.environ.get('ZDOTDIR') or Path.home()).expanduser().resolve() / '.zprofile'))
    cfg['path_managed'] = previous.get('path_managed', False) or not args.skip_path_update
    runtime = provider / '.bridge/bridge.py'
    launcher = Path(cfg['install_bin']) / cfg['command_name']
    if launcher.exists() and OWNER not in launcher.read_text(encoding='utf-8'):
        raise ValueError('Refusing to overwrite an unrelated command: ' + str(launcher))
    provider.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(runtime, Path(__file__).read_text(encoding='utf-8'))
    atomic_write(provider / 'config.toml', config_text(cfg))
    write_json(provider / 'models_cache.json', model_catalog)
    write_json(marker, cfg)
    write_launcher(launcher, runtime, 'run', marker)
    if not args.skip_path_update:
        update_path(cfg)
    emit(dict(status='installed', launcher=str(launcher), provider_home=str(provider),
              shell_profile=cfg['shell_profile'] if cfg['path_managed'] else None,
              secret_written=False, new_terminal_required=True))


def key_path(cfg):
    return Path(cfg['provider_codex_home']) / '.bridge/provider-key'


def provider_key(cfg):
    value = os.environ.get(cfg['api_key_environment_variable'], '')
    if value.strip():
        return value
    path = key_path(cfg)
    if path.is_file():
        if path.stat().st_mode & 0o077:
            raise ValueError('Provider key file must have permissions 600.')
        return path.read_text(encoding='utf-8').strip()
    return ''


def set_key(cfg):
    value = getpass.getpass('Enter ' + cfg['api_key_environment_variable'] + ': ').strip()
    if not value:
        raise ValueError('Empty key.')
    atomic_write(key_path(cfg), value + '\n')
    emit(dict(status='configured', storage='owner-only file', value_printed=False))


def refresh_cache(path):
    cache = read_json(path)
    cache['fetched_at'] = now()
    write_json(path, cache)


def keep_cache(path, stop, interval=240):
    while not stop.wait(interval):
        try:
            refresh_cache(path)
        except (OSError, ValueError) as error:
            print('Model catalog refresh failed: ' + str(error), file=sys.stderr)
            return


def wait_child(command, **kwargs):
    # Codex retains the terminal and receives Ctrl+C itself. The parent waits
    # for its actual exit instead of abandoning its child or the keeper.
    child = subprocess.Popen(command, **kwargs)
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    def terminate(signum, frame):
        if child.poll() is None:
            child.send_signal(signum)
    old_term = signal.signal(signal.SIGTERM, terminate)
    try:
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        signal.signal(signal.SIGINT, previous)
        signal.signal(signal.SIGTERM, old_term)


def run_provider(cfg, arguments):
    key = provider_key(cfg)
    if not key:
        raise ValueError('Provider key is missing. Run setup.sh set-key or export ' + cfg['api_key_environment_variable'] + '.')
    path = Path(cfg['provider_codex_home']) / 'models_cache.json'
    if not path.is_file():
        raise ValueError('Provider model catalog is missing; run setup.sh install again.')
    executable = codex_path()
    effort = None
    if arguments and arguments[0].lower() in ['--' + level for level in LEVELS]:
        effort = arguments[0][2:].lower()
        arguments = arguments[1:]
    command = [executable]
    for name, value in overrides(cfg, effort).items():
        command += ['-c', name + '=' + json.dumps(value)]
    env = dict(os.environ, CODEX_HOME=cfg['provider_codex_home'])
    env[cfg['api_key_environment_variable']] = key
    refresh_cache(path)  # Synchronous: Codex never starts against a stale cache.
    stop = threading.Event()
    keeper = threading.Thread(target=keep_cache, args=(path, stop), daemon=True)
    keeper.start()
    try:
        return wait_child(command + arguments, env=env)
    finally:
        stop.set()
        keeper.join()


def test_installation(cfg, live=False):
    provider = Path(cfg['provider_codex_home'])
    result = dict(codex_present=bool(shutil.which('codex')), provider_home=provider.is_dir(),
                  launcher=os.access(Path(cfg['install_bin']) / cfg['command_name'], os.X_OK),
                  catalog=(provider / 'models_cache.json').is_file(),
                  runtime=(provider / '.bridge/bridge.py').is_file(),
                  key_present=bool(provider_key(cfg)), key_value_printed=False,
                  live_test='not-requested')
    if live:
        with tempfile.TemporaryDirectory(prefix='codex-bridge-smoke-') as temporary:
            message = Path(temporary) / 'response.txt'
            code = run_provider(cfg, ['exec', '--ephemeral', '--skip-git-repo-check',
                                      '--output-last-message', str(message),
                                      'Reply with exactly PROVIDER_SMOKE_OK'])
            result['live_test'] = 'passed' if code == 0 and message.is_file() and message.read_text().strip() == 'PROVIDER_SMOKE_OK' else 'failed'
    emit(result)
    return 0 if all(result[k] for k in ('codex_present', 'provider_home', 'launcher', 'catalog', 'runtime', 'key_present')) and result['live_test'] != 'failed' else 1


def register_project(cfg, args):
    codex_path()
    if not args.project_root or not Path(args.project_root).expanduser().is_dir():
        raise ValueError('Project root must be an existing directory.')
    root = Path(args.project_root).expanduser().resolve()
    project_id = token(args.project_id or root.name)
    for protected in (cfg['provider_codex_home'], cfg['gpt_codex_home'], cfg['broker_root'], cfg['install_bin']):
        if inside(root, protected) or inside(protected, root):
            raise ValueError('Project must be separate from installation and credential directories.')
    if not Path(cfg['gpt_codex_home']).is_dir():
        raise ValueError('Normal ChatGPT Codex home not found. Run codex login first.')
    broker = Path(cfg['broker_root'])
    config_path = broker / 'broker.config.json'
    config = read_json(config_path) if config_path.exists() else dict(schema_version=1, projects=[])
    for project in config['projects']:
        if project['id'] != project_id and (inside(root, project['root']) or inside(project['root'], root)):
            raise ValueError('Registered project roots must not overlap.')
    config['projects'] = [p for p in config['projects'] if p['id'] != project_id]
    config['projects'].append(dict(id=project_id, root=str(root), delivery_policy=args.delivery_policy))
    config.update(gpt_codex_home=cfg['gpt_codex_home'], api_key_environment_variable=cfg['api_key_environment_variable'])
    broker.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime = broker / 'bridge.py'
    launcher = Path(cfg['install_bin']) / 'codex-image'
    write_launcher(launcher, runtime, 'image', config_path)
    atomic_write(runtime, Path(__file__).read_text(encoding='utf-8'))
    write_json(config_path, config)
    rule = 'prefix_rule(\n    pattern = ' + json.dumps([str(launcher), '--request-path']) + ',\n    decision = "allow",\n    justification = "Run the registered image broker only.",\n)\n'
    atomic_write(Path(cfg['provider_codex_home']) / 'rules/image-broker.rules', rule)
    emit(dict(status='registered', project_id=project_id, root=str(root), delivery_policy=args.delivery_policy))


def validate_request(config, request_path, broker):
    request_path = Path(request_path).expanduser().resolve()
    projects = [p for p in config['projects'] if inside(p['root'], request_path)]
    if len(projects) != 1:
        raise ValueError('Request must be inside exactly one registered project.')
    if request_path.stat().st_size > 65536:
        raise ValueError('Request exceeds 64 KiB.')
    req = read_json(request_path)
    allowed = {'project_id', 'task_id', 'operation', 'prompt', 'reference_images', 'output_directory', 'max_images'}
    if not isinstance(req, dict) or req.keys() - allowed:
        raise ValueError('Request must be an object with known fields only.')
    project = projects[0]
    if req.get('project_id') != project['id']:
        raise ValueError('project_id mismatch.')
    token(req.get('task_id', ''))
    if req.get('operation') not in ('generate', 'edit'):
        raise ValueError('Invalid operation.')
    if not isinstance(req.get('prompt'), str) or not 10 <= len(req['prompt'].strip()) <= 12000:
        raise ValueError('Invalid prompt.')
    maximum = req.get('max_images', 1)
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError('Invalid max_images.')
    references = req.get('reference_images', [])
    if not isinstance(references, list) or len(references) > 5 or any(not isinstance(r, str) for r in references):
        raise ValueError('Invalid reference_images.')
    refs = [bounded_path(project['root'], r) for r in references]
    if any(not r.is_file() for r in refs):
        raise ValueError('Missing reference image.')
    if req['operation'] == 'edit' and not refs:
        raise ValueError('Edit requires a reference.')
    if project['delivery_policy'] == 'staging':
        stage = bounded_path(project['root'], STAGING)
        out = bounded_path(project['root'], req.get('output_directory') or STAGING / req['task_id'])
        if not inside(stage, out):
            raise ValueError('Output must remain in delegated staging.')
    elif project['delivery_policy'] == 'approval-before-copy':
        if req.get('output_directory'):
            raise ValueError('output_directory forbidden by policy.')
        out = bounded_path(broker, Path('outputs') / token(project['id']) / req['task_id'])
    else:
        raise ValueError('Unknown delivery policy.')
    return project, req, refs, out, maximum


def png_dimensions(path):
    with Path(path).open('rb') as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise ValueError('Invalid PNG: ' + str(path))
    return struct.unpack('>II', header[16:24])


def image_request(config_path, arguments):
    parser = argparse.ArgumentParser(prog='codex-image')
    parser.add_argument('--request-path', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(arguments)
    config = read_json(config_path)
    broker = Path(config_path).parent
    project, req, refs, out, maximum = validate_request(config, args.request_path, broker)
    if args.validate_only:
        emit(dict(status='validated', project_id=project['id'], delivery_policy=project['delivery_policy'], output_directory=str(out)))
        return 0
    with (broker / 'image.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another image task is running.') from None
        generated = Path(config['gpt_codex_home']) / 'generated_images'
        before = set(generated.rglob('*.png'))
        out.mkdir(parents=True, exist_ok=True)
        logs = bounded_path(out, '.bridge')
        logs.mkdir(exist_ok=True)
        prompt = ('Use built-in image generation to ' + req['operation'] + ' no more than ' + str(maximum) +
                  ' image(s). Never use OPENAI_API_KEY. Do not modify project files or reproduce third-party branding. Request: ' + req['prompt'])
        command = [codex_path(), '-c', 'model_provider="openai"', 'exec', '--sandbox', 'workspace-write',
                   '--cd', project['root'], '--skip-git-repo-check', '--ephemeral', '--json',
                   '--output-last-message', str(bounded_path(logs, 'last-message.txt'))]
        for reference in refs:
            command += ['--image', str(reference)]
        env = dict(os.environ, CODEX_HOME=config['gpt_codex_home'])
        env.pop('OPENAI_API_KEY', None)
        env.pop(config['api_key_environment_variable'], None)
        with bounded_path(logs, 'events.jsonl').open('w') as events, bounded_path(logs, 'progress.log').open('w') as progress:
            code = wait_child(command + [prompt], env=env, stdout=events, stderr=progress)
        if code:
            raise ValueError('ChatGPT Codex failed; inspect .bridge/progress.log. Exit code: ' + str(code))
        images = sorted(set(generated.rglob('*.png')) - before)
        if not 1 <= len(images) <= maximum:
            raise ValueError('Unexpected image count: ' + str(len(images)))
        artifacts = []
        for index, source in enumerate(images, 1):
            if not inside(generated, source):
                raise ValueError('Generated image escapes image directory.')
            destination = bounded_path(out, 'image-{:02d}.png'.format(index))
            width, height = png_dimensions(source)
            shutil.copyfile(source, destination)
            digest = hashlib.sha256()
            with destination.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1048576), b''):
                    digest.update(chunk)
            artifacts.append(dict(path=str(destination), sha256=digest.hexdigest(), width=width, height=height))
        manifest = dict(schema_version=1, status='completed', project_id=project['id'], task_id=req['task_id'],
                        delivery_policy=project['delivery_policy'], production_approved=False,
                        provider='Codex built-in image generation via ChatGPT login', artifacts=artifacts)
        write_json(bounded_path(out, 'result.json'), manifest)
        emit(manifest)
    return 0


def uninstall(cfg, dry_run):
    provider = Path(cfg['provider_codex_home'])
    launcher = Path(cfg['install_bin']) / cfg['command_name']
    # Revalidate persisted roots before recursive removal.
    settings(argparse.Namespace(**cfg))
    if launcher.exists() and OWNER not in launcher.read_text(encoding='utf-8'):
        raise ValueError('Launcher has been replaced; refusing to remove it.')
    if not dry_run:
        if cfg['path_managed']:
            update_path(cfg, remove=True)
        launcher.unlink(missing_ok=True)
        shutil.rmtree(provider)
    emit(dict(status='preview' if dry_run else 'uninstalled', paths=[str(launcher), str(provider)],
              normal_codex_home_preserved=cfg['gpt_codex_home'], projects_preserved=True,
              broker_preserved=True, stored_provider_key_removed=not dry_run))


def setup(arguments):
    parser = argparse.ArgumentParser(description='Install the macOS Codex provider bridge (Python 3.9+).')
    parser.add_argument('action', choices=('install', 'set-key', 'register-project', 'test', 'uninstall'), nargs='?', default='install')
    parser.add_argument('--provider-name', default='deepseek')
    parser.add_argument('--base-url', default='https://api.deepseek.com')
    parser.add_argument('--api-key-environment-variable', default='DEEPSEEK_API_KEY')
    parser.add_argument('--models', default='deepseek-flash,deepseek-v4-pro')
    parser.add_argument('--default-model', default='deepseek-flash')
    parser.add_argument('--reasoning-effort', choices=LEVELS, default='max')
    parser.add_argument('--plan-reasoning-effort', choices=LEVELS, default='max')
    parser.add_argument('--context-window', type=int, default=1000000)
    parser.add_argument('--approvals-reviewer', choices=('', 'user', 'auto_review'), default='')
    parser.add_argument('--provider-codex-home', default=str(Path.home() / '.codex-deepseek'))
    parser.add_argument('--gpt-codex-home', default=str(Path.home() / '.codex'))
    parser.add_argument('--install-bin', default=str(Path.home() / '.local/bin'))
    parser.add_argument('--broker-root', default=str(Path.home() / '.codex-image-broker'))
    parser.add_argument('--command-name', default='codex-deepseek')
    parser.add_argument('--project-root')
    parser.add_argument('--project-id')
    parser.add_argument('--delivery-policy', choices=('staging', 'approval-before-copy'), default='staging')
    parser.add_argument('--live-test', action='store_true')
    parser.add_argument('--skip-path-update', action='store_true')
    parser.add_argument('--what-if', action='store_true')
    args = parser.parse_args(arguments)
    if args.what_if and args.action != 'uninstall':
        parser.error('--what-if is supported only for uninstall.')
    if args.action == 'install':
        install(args)
    else:
        cfg = saved_settings(args)
        if args.action == 'set-key':
            set_key(cfg)
        elif args.action == 'register-project':
            register_project(cfg, args)
        elif args.action == 'test':
            return test_installation(cfg, args.live_test)
        elif args.action == 'uninstall':
            uninstall(cfg, args.what_if)
    return 0


def main():
    if sys.version_info < (3, 9):
        raise ValueError('Python 3.9 or newer is required.')
    if sys.platform != 'darwin':
        raise ValueError('Use setup.ps1 on Windows. This entry point supports macOS.')
    mode, arguments = sys.argv[1], sys.argv[2:]
    if mode == 'setup':
        return setup(arguments)
    if mode == 'run':
        return run_provider(read_json(arguments[0]), arguments[1:])
    if mode == 'image':
        return image_request(arguments[0], arguments[1:])
    raise ValueError('Unknown runtime command.')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
