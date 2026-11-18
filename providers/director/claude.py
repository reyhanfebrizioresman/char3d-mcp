"""Anthropic SDK 2.10 Messages API, used only after explicit consent."""
import inspect
import json

from .common import DirectorError, PRIVACY, SCHEMA, effort, model, user_prompt
from .prompts import system_blocks


class Backend:
    online = True

    def __init__(self):
        self.usage = {}
        self.model = model()
        self.calls = 0

    @staticmethod
    def available():
        try:
            import anthropic
            # Construction resolves local configuration, but never requests a token
            # or makes an HTTP call. The SDK owns env/profile/WIF precedence.
            with anthropic.Anthropic() as client:
                return bool(client.api_key or client.auth_token or client.credentials)
        except Exception:
            return False

    def metadata(self):
        # Usage input_tokens excludes cache tokens. 5-minute cache writes/reads
        # use Opus 5.5 list prices: $5/$0.20 per MTok. Repairs are included.
        cost = (self.usage.get('input_tokens', 0) * 4 + self.usage.get('output_tokens', 0) * 20 +
                self.usage.get('cache_creation_input_tokens', 0) * 5 +
                self.usage.get('cache_read_input_tokens', 0) * .20) / 1_000_000
        return dict(model=self.model, usage=self.usage, cost_usd_estimate=round(cost, 6),
                    cost_basis='Estimasi tarif Opus 5.5: input $4, output $20, cache tulis 5m $5, baca $0.20 / MTok; termasuk perbaikan.',
                    privacy=PRIVACY, requests=self.calls)

    def generate(self, opts, previous=None, feedback=None):
        import anthropic
        output_schema, blocks = SCHEMA, system_blocks()
        if opts.get('task') == 'world':
            from .world import contract
            output_schema, prompt = contract()
            blocks = [{'type': 'text', 'text': prompt, 'cache_control': {'type': 'ephemeral'}}]
        try:
            with anthropic.Anthropic(timeout=180.0, max_retries=0) as client:
                args = dict(model=self.model, max_tokens=16000, stream=False,
                            system=blocks, messages=[{'role': 'user', 'content': user_prompt(opts, previous, feedback)}],
                            output_config={'effort': effort(), 'format': {'type': 'json_schema', 'schema': output_schema}})
                # Inspect the installed SDK, never send unsupported beta kwargs.
                create = client.beta.messages.create
                if {'fallbacks', 'output_config'} <= set(inspect.signature(create).parameters):
                    args.update(betas=['server-side-fallback-2026-07-01'], fallbacks='default')
                else:
                    create = client.messages.create
                self.calls += 1
                response = create(**args)
                self.model = response.model
                usage = response.usage.model_dump()
                for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
                    self.usage[key] = self.usage.get(key, 0) + (usage.get(key) or 0)
                # Do not inspect content on refusal/truncation (including partial JSON).
                if response.stop_reason == 'refusal':
                    raise DirectorError('Claude menolak permintaan ini; draf offline digunakan.')
                if response.stop_reason == 'max_tokens':
                    raise DirectorError('Jawaban Claude terpotong karena batas token; draf offline digunakan.')
                if response.stop_reason not in ('end_turn', 'stop_sequence'):
                    raise DirectorError('Claude belum menyelesaikan jawaban; draf offline digunakan.')
                content = ''.join(block.text for block in response.content if block.type == 'text')
                return json.loads(content)
        except anthropic.AuthenticationError:
            raise DirectorError('Autentikasi Claude gagal. Periksa konfigurasi Anthropic di ~/.config/char3d/env; draf offline digunakan.') from None
        except anthropic.RateLimitError:
            raise DirectorError('Batas permintaan atau kuota Claude tercapai. Coba lagi nanti; draf offline digunakan.') from None
        except anthropic.APIConnectionError:
            raise DirectorError('Tidak dapat terhubung ke Anthropic atau waktu tunggu habis; draf offline digunakan.') from None
        except anthropic.APIStatusError:
            raise DirectorError('Layanan Anthropic mengembalikan kesalahan; draf offline digunakan.') from None
        except (json.JSONDecodeError, TypeError, AttributeError):
            raise DirectorError('Jawaban Claude tidak berupa JSON terstruktur yang lengkap; draf offline digunakan.') from None
