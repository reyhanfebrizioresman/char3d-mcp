"""Offline F5 client. No torch imports; one cancellable subprocess per session."""
import atexit
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tempfile

from . import audio

DEFAULT_PYTHON = "~/.local/share/char3d/f5-venv/bin/python"
REFERENCE_TEXT = ("Selamat pagi, hari ini udara terasa sejuk. Saya senang bisa berbagi cerita "
                  "dengan kalian. Mari kita mulai perjalanan ini bersama.")
BUILTINS = {
    'female_adult': dict(gender='female', age=30, pitch=-3.1),
    'male_adult': dict(gender='male', age=35, pitch=-12.),
    'elder': dict(gender='male', age=70, pitch=-12., rate=.91),
    'child': dict(gender='variant', age=10, pitch=1.),
}
VERSION = 'f5-worker-2'
REFERENCE_LOCK = threading.Lock()


class Worker:
    """Serial protocol, bounded diagnostics, hard timeout/cancellation and reaping."""
    def __init__(self, script=None):
        self.lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.process = None
        self.identity = None
        self.responses = None
        self.errors = deque(maxlen=20)
        self.serial = 0
        self.script = script or str(Path(__file__).with_name('f5_worker.py'))

    def close(self):
        with self.state_lock:
            process, self.process = self.process, None
            self.identity = None
            if process:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()

    cancel = close

    def _exchange(self, request, timeout):
        process = self.process
        self.serial += 1
        request = dict(request, id=self.serial)
        try:
            process.stdin.write(json.dumps(request)+'\n')
            process.stdin.flush()
            response = self.responses.get(timeout=timeout)
            if response is None:
                raise RuntimeError('worker exited: '+' '.join(self.errors)[-3000:])
            response = json.loads(response)
            if response.get('id') != self.serial:
                raise RuntimeError('worker protocol response ID mismatch')
            if not response.get('ok'):
                raise RuntimeError(response.get('error', 'unknown worker error'))
            return response['result']
        except queue.Empty:
            self.close()
            raise TimeoutError(f'F5 exceeded {timeout:g}s; worker stopped. Reduce text or increase CHAR3D_F5_TIMEOUT.') from None
        except (OSError, ValueError, AttributeError) as exc:
            self.close()
            raise RuntimeError(f'F5 worker protocol failed: {exc}') from exc

    def infer(self, python, assets, request):
        with self.lock:
            timeout = float(os.environ.get('CHAR3D_F5_TIMEOUT', '600'))
            quantize = os.environ.get('CHAR3D_F5_QUANTIZE', '0') == '1'
            threads = int(os.environ.get('CHAR3D_F5_THREADS', '2'))
            script_stat = Path(self.script).stat()
            identity = (python, tuple(assets.items()), quantize, threads,
                        script_stat.st_size, script_stat.st_mtime_ns)
            if self.identity != identity or self.process is None or self.process.poll() is not None:
                self.close()
                env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                           HF_HUB_DISABLE_TELEMETRY='1', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2',
                           NUMBA_CACHE_DIR=str(Path(tempfile.gettempdir())/'char3d-f5-numba'),
                           MPLCONFIGDIR=str(Path(tempfile.gettempdir())/'char3d-f5-matplotlib'))
                with self.state_lock:
                    self.process = subprocess.Popen([python, '-u', self.script],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, bufsize=1, env=env)
                responses = self.responses = queue.Queue()
                self.errors.clear()
                def read_stdout(stream):
                    try:
                        for line in stream:
                            responses.put(line)
                    except (OSError, ValueError):
                        pass
                    finally:
                        responses.put(None)
                def read_stderr(stream):
                    try:
                        for line in stream:
                            self.errors.append(line.strip()[:1000])
                    except (OSError, ValueError):
                        pass
                threading.Thread(target=read_stdout, args=(self.process.stdout,), daemon=True).start()
                threading.Thread(target=read_stderr, args=(self.process.stderr,), daemon=True).start()
                try:
                    self._exchange(dict(op='init', **assets, threads=threads, quantize=quantize), timeout)
                except BaseException:
                    self.close()
                    raise
                self.identity = identity
            try:
                return self._exchange(dict(op='synthesize', **request), timeout)
            except BaseException:
                self.close()
                raise


WORKER = Worker()
atexit.register(WORKER.close)


class Backend:
    online = False
    license = ('F5 code MIT; Indonesian finetune Apache-2.0; base weights CC-BY-NC, '
               'personal/non-commercial. Builtin references are synthetic Piper derivatives; '
               'news_tts dataset rights unclear, personal use only.')

    def __init__(self, root):
        self.root = Path(root)/'f5'
        self.python = str(Path(os.environ.get('CHAR3D_F5_PYTHON', DEFAULT_PYTHON)).expanduser())
        self.reference_dir = Path(os.environ.get('CHAR3D_WORKSPACE', 'output')).resolve()/'imports/audio/tts/f5_references'

    def install_hint(self):
        return 'scripts/install_tts.sh f5 --yes'

    def assets(self):
        sites = sorted(Path(self.python).parent.parent.glob('lib/python*/site-packages'))
        checkpoint = next((p for p in (self.root/'f5-id-v1/model.safetensors', self.root/'model.safetensors')
                           if p.is_file()), self.root/'f5-id-v1/model.safetensors')
        vocab = next((p for p in [self.root/'vocab.txt'] + [
            s/'f5_tts/infer/examples/vocab.txt' for s in sites] if p.is_file()), self.root/'vocab.txt')
        vocoder = self.root/'vocos'
        if not all((vocoder/f).is_file() for f in ('config.yaml', 'pytorch_model.bin')):
            cache = Path(os.environ.get('HF_HUB_CACHE', os.path.join(os.environ.get('HF_HOME', '~/.cache/huggingface'), 'hub'))).expanduser()
            repo = cache/'models--charactr--vocos-mel-24khz'
            ref = repo/'refs/main'
            if ref.is_file():
                vocoder = repo/'snapshots'/ref.read_text().strip()
        return dict(checkpoint=str(checkpoint), vocab=str(vocab), vocoder=str(vocoder))

    def missing(self):
        assets = self.assets()
        required = [self.python, assets['checkpoint'], assets['vocab'],
                    str(Path(assets['vocoder'])/'config.yaml'), str(Path(assets['vocoder'])/'pytorch_model.bin')]
        return [p for p in required if not Path(p).is_file()]

    def available(self):
        return not self.missing()

    def voices(self, language=None):
        installed = self.available()
        from .piper import Backend as Piper, DEFAULT_VOICE
        piper = Piper(self.root.parent)
        result = []
        for name, cfg in BUILTINS.items():
            if not language or language == 'id':
                result.append(dict(id='f5:'+name, name=name, language='id', gender=cfg['gender'],
                                   age=cfg['age'], installed=installed and piper.available() and piper.model_path(DEFAULT_VOICE) is not None,
                                   source='synthetic Piper; personal use'))
        for file in sorted((self.root/'voices').glob('*.json')):
            try:
                cfg = self.config(file.stem)
            except (ValueError, OSError):
                continue
            lang = cfg.get('language', 'id')
            if not language or lang.startswith(language):
                result.append(dict(id='f5:'+file.stem, name=file.stem, language=lang,
                                   gender=cfg.get('gender', 'variant'), age=cfg.get('age', 30),
                                   installed=installed, source=cfg.get('source', 'user/permitted')))
        return result

    def config(self, name):
        if not name or Path(name).name != name:
            raise ValueError('F5 voice must be a registered name')
        if name in BUILTINS:
            return dict(BUILTINS[name], builtin=name, reference_text=REFERENCE_TEXT, language='id')
        path = self.root/'voices'/(name+'.json')
        cfg = json.loads(path.read_text())
        if not isinstance(cfg, dict):
            raise ValueError('F5 voice JSON must be an object')
        return self.reference_config(cfg.get('voice_reference', ''), cfg.get('reference_text', ''), path.parent, cfg)

    def reference_config(self, reference, transcript, base=None, cfg=None):
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError('F5 requires the exact reference_text transcript; ASR is disabled')
        ref = Path(reference).expanduser()
        ref = ref if ref.is_absolute() else Path(base or self.reference_dir)/ref
        if not ref.is_file():
            raise ValueError('F5 needs voice_reference WAV and exact reference_text; use only own/permitted voices')
        if ref.suffix.lower() != '.wav':
            raise ValueError('F5 reference must be a WAV file')
        return dict(cfg or {}, voice_reference=str(ref.resolve()), reference_text=transcript)

    def fingerprint(self, voice, config=None):
        cfg = config or self.config(voice)
        content = dict(cfg)
        if 'builtin' in cfg:
            from .piper import Backend as Piper, DEFAULT_VOICE
            content['piper'] = Piper(self.root.parent).fingerprint(DEFAULT_VOICE)
        if 'voice_reference' in cfg:
            content['reference_hash'] = hashlib.sha256(Path(cfg['voice_reference']).read_bytes()).hexdigest()
        content['assets'] = {p: [Path(p).stat().st_size, Path(p).stat().st_mtime_ns]
            for p in [self.python, self.assets()['checkpoint'], self.assets()['vocab'],
                      str(Path(self.assets()['vocoder'])/'config.yaml'),
                      str(Path(self.assets()['vocoder'])/'pytorch_model.bin')] if Path(p).is_file()}
        content.update(version=VERSION, steps=int(os.environ.get('CHAR3D_F5_STEPS', '32')),
                       quantize=os.environ.get('CHAR3D_F5_QUANTIZE', '0'),
                       threads=os.environ.get('CHAR3D_F5_THREADS', '2'))
        content['worker_sha256'] = hashlib.sha256(Path(__file__).with_name('f5_worker.py').read_bytes()).hexdigest()
        # The F5 distribution lives outside this interpreter, so the registry's
        # importlib.metadata lookup cannot supply its actual runtime version.
        content['runtime'] = {file.parent.name: hashlib.sha256(file.read_bytes()).hexdigest()
            for site in Path(self.python).parent.parent.glob('lib/python*/site-packages')
            for package in ('f5_tts', 'torch', 'torchaudio', 'vocos')
            for file in site.glob(package+'-*.dist-info/METADATA')}
        return json.dumps(content, sort_keys=True)

    def _reference(self, cfg):
        with REFERENCE_LOCK:
            return self._make_reference(cfg)

    def _make_reference(self, cfg):
        if 'builtin' not in cfg or 'voice_reference' in cfg:
            return cfg
        from .piper import Backend as Piper, DEFAULT_VOICE
        piper = Piper(self.root.parent)
        # Reference identity does not depend on the F5 inference quality settings.
        identity = json.dumps(dict(cfg, piper=piper.fingerprint(DEFAULT_VOICE)), sort_keys=True)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        path = self.reference_dir/(digest+'.wav')
        if not path.is_file():
            import tempfile
            self.reference_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.reference_dir) as temp:
                raw = Path(temp)/'ref.wav'
                piper.synthesize(REFERENCE_TEXT, DEFAULT_VOICE, 'id', cfg.get('rate', 1.), cfg['pitch'], raw)
                samples, rate = audio.read(raw)
                audio.write(raw, audio.normalize(samples, rate), rate)
                os.replace(raw, path)
        return dict(cfg, voice_reference=str(path))

    def synthesize(self, text, voice, language, rate, pitch, out_path, config=None):
        if not self.available():
            raise RuntimeError(f'F5 missing local files: {self.missing()}. No download attempted. Run: {self.install_hint()}')
        if language != 'id':
            raise ValueError('Installed f5-id-v1 voices support Indonesian (language=id)')
        cfg = self._reference(config or self.config(voice))
        steps = int(os.environ.get('CHAR3D_F5_STEPS', '32'))
        if steps not in (8, 16, 24, 32, 64):
            raise ValueError('CHAR3D_F5_STEPS must be 8, 16, 24, 32 or 64')
        result = WORKER.infer(self.python, self.assets(), dict(text=text, rate=rate, steps=steps,
            voice_reference=cfg['voice_reference'], reference_text=cfg['reference_text'], output=str(out_path)))
        if pitch:
            samples, sr = audio.read(out_path)
            shifted = audio.pitch_shift(samples, pitch, sr)
            peak = float(abs(shifted).max(initial=0))
            if peak > .98:
                shifted *= .98/peak  # retain headroom before intermediate PCM
            audio.write(out_path, shifted, sr)
        result['real_time_factor'] = result['wall_seconds']/max(result['duration_s'], .01)
        return result

    def close(self):
        WORKER.close()

    cancel = close
