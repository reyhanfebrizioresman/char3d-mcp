"""Provenance formatting from assets actually referenced by a scene or film."""
import json

TTS_NOTES = {
 'piper': ('Piper runtime GPL-3.0; voice: personal use pending dataset licence clarification', 'Offline synthesis; voice model licence is separate from runtime'),
 'edge': ('edge-tts LGPL-3.0; Microsoft voice/service terms apply', 'Online: text sent to Microsoft through an unofficial API'),
 'f5': ('F5 code MIT; Indonesian finetune Apache-2.0; upstream base weights CC-BY-NC', 'Offline inference; references require permission; synthetic Piper references retain its voice limitation'),
 'chatterbox': ('Chatterbox MIT; hosted service terms also apply', 'Online: text/reference sent to Hugging Face / ResembleAI'),
}


def collect(evidence):
    records = []
    def add(kind, name, licence, path=None, **extra):
        records.append(dict(kind=kind, name=name, licence=licence, path=path, **extra))
    for asset in evidence.get('mpfb', []):
        add('MPFB', asset['name'], 'CC0', asset.get('path'), pack=asset.get('pack', 'system'))
    for font in evidence.get('soundfonts', []):
        add('SoundFont', font.get('name', 'GeneralUser GS'), font.get('licence', 'GeneralUser GS licence (see licence file)'), font['path'],
            licence_file=font.get('licence_file'), sha256=font.get('sha256'))
    for voice in evidence.get('voices', []):
        engine = voice.get('engine', str(voice.get('voice','')).split(':')[0])
        licence, privacy = TTS_NOTES.get(engine, ('Unknown model licence — check source', 'User-supplied provenance'))
        add('TTS', voice.get('voice', engine), licence, voice.get('path'), engine=engine, privacy=privacy)
    for model in evidence.get('whisper', []):
        add('ASR', 'Whisper '+model, 'MIT (Whisper code and model); faster-whisper MIT', privacy='Local transcription')
    for font in evidence.get('fonts', []):
        add('Font', font.get('name') or font['path'], font.get('licence') or 'system font — check licence',
            font['path'], licence_file=font.get('licence_file'))
    for path in evidence.get('imports', []):
        add('User asset', path, 'User-supplied; user is responsible for permissions and attribution', path)
    for generator in evidence.get('procedural', []):
        add('Generator', generator, 'Original char3d procedural generator')
    unique = {json.dumps(r, sort_keys=True): r for r in records}
    records = sorted(unique.values(), key=lambda r: (r['kind'], r['name'], r.get('path') or ''))
    return dict(assets=records, asset_count=len(records),
                notes=['Inventory of referenced assets, not a grant of rights.',
                       'Missing provenance is labelled; legacy projects may need source records.'])


def text(report):
    lines = ['CREDITS', '', *report['notes'], '']
    for r in report['assets']:
        lines.append(f"{r['kind']}: {r['name']}\n  Licence: {r['licence']}")
        lines += [f'  {k}: {v}' for k, v in r.items() if k not in ('kind', 'name', 'licence') and v]
    return '\n'.join(lines)+'\n'
