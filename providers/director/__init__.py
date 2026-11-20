"""Director registry in the MCP process. No engine calls, even for validation."""
from . import claude, claude_cli, offline
from .common import DirectorError, LIGHTING, PRIVACY, SUBSCRIPTION, model, options, safe_result, validate

REGISTRY = {'offline': offline.Backend, 'claude': claude.Backend, 'claude_cli': claude_cli.Backend}


def register(name, backend):
    REGISTRY[name] = backend


def status():
    configured = claude.Backend.available()
    cli = claude_cli.Backend.available()
    return {'generators': {
        'offline': {'available': True, 'online': False, 'label': 'Offline · gratis'},
        'claude': {'available': configured, 'configured': configured, 'online': True,
                   'label': 'Claude API · berbayar', 'model': model(), 'privacy': PRIVACY,
                   'estimate': 'Biasanya sekitar $0.05–$0.25 per draf; batas 16000 token output sekitar $0.32 + input per permintaan, perbaikan bisa menambah biaya.'},
        'claude_cli': {'available': cli, 'online': True, 'label': 'Claude langganan · via Claude Code',
                       'model': model(), 'auth': 'Diperiksa pada panggilan pertama', 'billing_note': SUBSCRIPTION, 'privacy': PRIVACY},
    }, 'default': 'offline', 'auto_with_consent': 'claude_cli' if cli else 'claude' if configured else 'offline'}


def online_request(arguments):
    name = arguments.get('generator', 'auto')
    return name in ('claude', 'claude_cli') or name == 'auto' and arguments.get('consent') is True


def direct(idea, generator='auto', language='id', duration_s=30, characters=None,
           style=None, look=None, location=None, seed=0, consent=False):
    opts = options(idea, language, duration_s, characters, style, look, location, seed)
    if generator != 'auto' and generator not in REGISTRY:
        raise ValueError('Generator harus auto, offline, claude, atau claude_cli.')
    if generator == 'auto':
        generator = ('claude_cli' if consent is True and claude_cli.Backend.available() else
                     'claude' if consent is True and claude.Backend.available() else 'offline')
        notes = ['Auto memilih offline karena layanan online belum disetujui atau belum tersedia.'] if generator == 'offline' else []
    else:
        notes = []
    factory = REGISTRY[generator]
    if factory.online and consent is not True:
        raise ValueError('Persetujuan diperlukan: ide dan opsi akan dikirim ke Anthropic. Gunakan consent=True atau pilih offline.')
    requested = generator
    backend = factory()
    payload = None
    plan = None
    fallback_reason = None
    try:
        if not backend.available():
            raise DirectorError('Generator belum dikonfigurasi; draf offline digunakan.')
        payload = backend.generate(opts)
        for attempt in range(2):
            try:
                plan = validate(payload, opts)
                feedback = plan['warnings']
            except ValueError as exc:
                plan, feedback = None, [str(exc)]
            if not feedback:
                break
            if not attempt and backend.online:
                notes.append('Draf diperiksa parser dan menjalani satu putaran perbaikan.')
                payload = backend.generate(opts, previous=payload, feedback=feedback)
                continue
            if plan is None:
                raise DirectorError('Naskah generator tetap tidak valid setelah pemeriksaan; draf offline digunakan.')
            notes.extend(feedback)
            break
    except Exception as exc:
        # Never expose provider exception strings: SDK bodies may contain credentials.
        fallback_reason = str(exc) if isinstance(exc, DirectorError) else 'Generasi online gagal; draf offline digunakan.'
        notes.append(fallback_reason)
        generator = 'offline'
        payload = offline.Backend().generate(opts)
        plan = validate(payload, opts)
    from .treatment import markdown
    if '## Treatment' not in payload['brief']:
        payload['brief'] += '\n\n' + markdown(payload['treatment'],language)
    result = {**payload, 'generator': generator, 'plan': plan,
              'build_options': {'language': language, 'lighting': LIGHTING[(plan.get('look') or {}).get('preset', 'none')],
                                'camera': 'directed', 'seed': seed, 'treatment': payload['treatment'],
                                **({'tool': 'script_to_film'} if plan.get('scenes') else {})},
              'warnings': list(dict.fromkeys(notes + payload['warnings'] + plan['warnings']))}
    if factory.online:
        result.update(backend.metadata())
        result['requested_generator'] = requested
        if fallback_reason:
            result['fallback_reason'] = fallback_reason
    return safe_result(result)
