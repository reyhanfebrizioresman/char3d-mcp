"""Pure text Claude Code subprocess, isolated from project tools and MCP."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .common import DirectorError, PRIVACY, SCHEMA, SUBSCRIPTION, effort, model, user_prompt
from .prompts import SYSTEM


def discover():
    explicit = os.environ.get('CHAR3D_CLAUDE_BIN')
    if explicit:
        path = Path(explicit).expanduser()
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    path = shutil.which('claude')
    if path:
        return path
    root = Path.home() / '.config/Claude/claude-code'
    def version(path):
        return tuple(int(n) for n in re.findall(r'\d+', path.parent.parent.name))
    found = [p for p in root.glob('*/*/claude') if p.is_file() and os.access(p, os.X_OK)]
    return str(max(found, key=lambda p: (version(p), p.stat().st_mtime))) if found else None


class Backend:
    online = True

    def __init__(self):
        self.model = model()
        self.usage = {}
        self.calls = 0

    @staticmethod
    def available():
        return discover() is not None

    def metadata(self):
        return dict(model=self.model, usage=self.usage, billing='subscription',
                    billing_note=SUBSCRIPTION, privacy=PRIVACY, requests=self.calls)

    def generate(self, opts, previous=None, feedback=None):
        binary = discover()
        if not binary:
            raise DirectorError('Claude Code tidak ditemukan. Atur CHAR3D_CLAUDE_BIN; draf offline digunakan.')
        output_schema, system_prompt = SCHEMA, SYSTEM
        if opts.get('task') == 'world':
            from .world import contract
            output_schema, system_prompt = contract()
        argv = [binary, '-p', '--output-format', 'json', '--json-schema', json.dumps(output_schema),
                '--model', model(), '--effort', effort(), '--system-prompt', system_prompt,
                '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                '--no-session-persistence', '--permission-mode', 'dontAsk',
                '--safe-mode', '--setting-sources', '', '--disable-slash-commands',
                '--no-chrome', '--exclude-dynamic-system-prompt-sections']
        env = dict(os.environ)
        # The subscription route must not accidentally bill a configured API key,
        # custom API gateway, or recursively inherit an active CLI session.
        for key in list(env):
            if key.startswith('ANTHROPIC_') or key in ('CLAUDECODE', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
                env.pop(key, None)
        try:
            with tempfile.TemporaryDirectory(prefix='char3d-director-') as cwd:
                self.calls += 1
                completed = subprocess.run(argv, input=user_prompt(opts, previous, feedback),
                                           capture_output=True, text=True, cwd=cwd, env=env, timeout=300)
            try:
                envelope = json.loads(completed.stdout)
            except (ValueError, TypeError):
                raise DirectorError('Claude Code tidak mengembalikan JSON lengkap; draf offline digunakan.') from None
            if not isinstance(envelope, dict):
                raise DirectorError('Format hasil Claude Code tidak dikenali; draf offline digunakan.')
            for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
                value = envelope.get('usage', {}).get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    self.usage[key] = self.usage.get(key, 0) + value
            models = envelope.get('modelUsage') or {}
            if models:
                self.model = ', '.join(models)
            result = envelope.get('result', '')
            error_text = str(result) + completed.stderr
            if re.search(r'not logged in|/login|authentication|unauthorized|oauth.*(?:expired|invalid)', error_text, re.I):
                raise DirectorError('Claude Code belum login. Jalankan `claude` sekali di terminal lalu login; draf offline digunakan.')
            if completed.returncode or envelope.get('is_error'):
                raise DirectorError('Claude Code gagal atau kuota langganan habis; draf offline digunakan.')
            if envelope.get('stop_reason') in ('refusal', 'max_tokens'):
                raise DirectorError('Claude Code menolak atau memotong jawaban; draf offline digunakan.')
            # --json-schema uses structured_output; result is the plain text
            # fallback in JSON print mode. No transcripts/session IDs are returned.
            payload = envelope.get('structured_output')
            if payload is None:
                payload = json.loads(result)
            return payload
        except subprocess.TimeoutExpired:
            raise DirectorError('Claude Code melewati batas waktu 5 menit; draf offline digunakan.') from None
        except OSError:
            raise DirectorError('Claude Code tidak dapat dijalankan di lingkungan ini; draf offline digunakan.') from None
        except (json.JSONDecodeError, TypeError, AttributeError):
            raise DirectorError('Hasil Claude Code tidak lengkap; draf offline digunakan.') from None
