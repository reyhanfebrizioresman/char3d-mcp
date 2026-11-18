"""Selectable TTS in the MCP process. Catalog/casting are offline by default.

Backends implement available/install_hint/voices/synthesize and online/license.
Register another Backend class with register(); never import this package in engine/.
"""
import hashlib
import importlib.metadata
import json
import math
import os
import random
import shutil
import tempfile
import threading
import time
import wave
from pathlib import Path

from . import audio
from .chatterbox import Backend as Chatterbox
from .edge import Backend as Edge
from .f5 import Backend as F5
from .piper import Backend as Piper

REGISTRY = {"piper": Piper, "edge": Edge, "f5": F5, "chatterbox": Chatterbox}
PACKAGES = {"piper": "piper-tts", "edge": "edge-tts", "f5": "f5-tts", "chatterbox": "gradio_client"}
ONLINE_ENGINES = frozenset({"edge", "chatterbox"})


def register(name, backend):
    REGISTRY[name] = backend


def parse_voice(voice=None, engine="piper"):
    if voice is not None and not isinstance(voice, str):
        raise ValueError("voice must be an engine:name string")
    if voice and ":" in voice:
        engine, voice = voice.split(":", 1)
        if not voice.strip():
            raise ValueError("voice spec must include a name after engine:")
    if engine not in REGISTRY:
        raise ValueError(f"Unknown TTS engine {engine!r}; choose {', '.join(REGISTRY)}")
    return engine, voice


_F0_FEMALE = ((0, 11, 17, 30, 55, 80), (290, 270, 225, 215, 205, 195))
_F0_MALE = ((0, 11, 13, 16, 30, 55, 80), (280, 255, 220, 150, 125, 118, 112))


def _interp(table, age):
    ages, values = table
    if age <= ages[0]:
        return values[0]
    for (a0, v0), (a1, v1) in zip(zip(ages, values), zip(ages[1:], values[1:])):
        if age <= a1:
            return v0 + (v1 - v0) * (age - a0) / (a1 - a0)
    return values[-1]


def target_f0(gender, age):
    """Typical speaking F0 (Hz) for gender 0 (female) .. 1 (male) and age in years."""
    gender = min(1., max(0., float(gender)))
    female, male = _interp(_F0_FEMALE, float(age)), _interp(_F0_MALE, float(age))
    return math.exp(math.log(female) * (1 - gender) + math.log(male) * gender)


def controls(rate, pitch):
    rate, pitch = float(rate), float(pitch)
    if not math.isfinite(rate) or not .5 <= rate <= 2:
        raise ValueError("TTS rate must be in 0.5..2.0")
    if not math.isfinite(pitch) or not -12 <= pitch <= 12:
        raise ValueError("TTS pitch must be in -12..12 semitones")
    return rate, pitch


def cache_key(engine, voice, text, language, rate, pitch, version):
    value = [engine, voice, text, language, float(rate), float(pitch), version, audio.DSP_VERSION]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class TTS:
    def __init__(self, workspace, model_dir=None):
        self.workspace = Path(workspace).resolve()
        self.root = Path(model_dir or os.environ.get("CHAR3D_TTS_DIR", "~/.local/share/char3d/tts")).expanduser()
        self.backends = {name: factory(self.root) for name, factory in REGISTRY.items()}
        self._lock = threading.Lock()

    def catalog(self, language=None, engine=None):
        if engine:
            parse_voice(None, engine)
        names = [engine] if engine else list(self.backends)
        engines = {}
        voices = []
        for name in names:
            backend = self.backends[name]
            installed = backend.available()
            entries = (backend.voices(language, refresh=engine == "edge") if name == "edge"
                       else backend.voices(language))
            engines[name] = {"installed": installed, "online": backend.online,
                             "license": backend.license, "install_hint": backend.install_hint()}
            if backend.online:
                engines[name]["privacy"] = backend.privacy
            voices.extend(entries)
        return {"engines": engines, "voices": voices}

    def cast(self, characters, engine="piper", language="id", seed=0, overrides=None):
        """Deterministic casting; never refreshes an online catalog or creates files."""
        parse_voice(None, engine)
        overrides = overrides or {}
        result, used = {}, set()
        lang = "id" if language in (None, "auto") else language
        for char in characters:
            ident = char["id"]
            override = overrides.get(ident, {})
            if isinstance(override, str):
                override = {"voice": override}
            char = dict(char, **override)
            chosen, name = parse_voice(char.get("voice"), char.get("engine", engine))
            backend = self.backends[chosen]
            gender, age = float(char.get("gender", .5)), float(char.get("age", 28))
            candidates = backend.voices(lang)
            if not name:
                matching = [v for v in candidates if v["gender"] == ("female" if gender < .5 else "male")]
                options = matching or candidates
                installed = [v for v in options if v.get("installed")]
                options = installed or options
                if options:
                    name = options[0]["id"].split(":", 1)[1]
            rng = random.Random(hashlib.sha256(f"{seed}:{ident}:{gender}:{age}".encode()).digest())
            if chosen == "piper":
                # Single-speaker Piper voices: shift the speaker's own F0 to a typical
                # F0 for this gender/age (PSOLA + proportional formant shift).
                base_f0 = backend.base_f0(name) if name and hasattr(backend, "base_f0") else 210.
                base = 12 * math.log2(target_f0(gender, age) / base_f0)
                pitch = round(max(-12., min(12., base + rng.uniform(-.6, .6))), 2)
            else:
                base = 2.0 if age < 16 else -.8 if age > 55 else 0
                pitch = round(base + rng.uniform(-.45, .45), 2)
            rate = round((.94 if age > 55 else 1.03 if age < 16 else 1) + rng.uniform(-.025, .025), 3)
            # Descriptive hints ("suara berat"/"deep voice") shift the cast, not replace it.
            pitch = max(-12., min(12., pitch + float(char.get("pitch_offset", 0))))
            # Ensure same-gender casts still have distinct profiles, including Edge pairs;
            # step away from the ±12 limit when a profile is already pinned there.
            step = .8 if gender < .5 else -.8
            while (chosen, name, round(pitch)) in used:
                if not -12 <= pitch + step <= 12:
                    step = -step
                pitch += step
            used.add((chosen, name, round(pitch)))
            rate, pitch = controls(char.get("rate", rate), char.get("pitch", round(pitch, 2)))
            usable = backend.available() and bool(name)
            if chosen in ("piper", "f5"):
                usable = usable and any(v["id"] == f"{chosen}:{name}" and v.get("installed")
                                        for v in backend.voices())
            result[ident] = {"engine": chosen, "voice": f"{chosen}:{name}" if name else None,
                             "pitch": pitch, "rate": rate, "online": backend.online,
                             "available": usable}
        return result

    def synthesize(self, text, voice=None, engine="piper", language="id", rate=1., pitch=0.,
                   gender=None, output=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("TTS text must not be empty")
        rate, pitch = controls(rate, pitch)
        engine, name = parse_voice(voice, engine)
        backend = self.backends[engine]
        lang = "id" if language in (None, "auto") else language
        if name is None:
            profile = self.cast([{"id": "speaker", "gender": gender if gender is not None else .5}],
                                engine, lang)["speaker"]
            if not profile["voice"]:
                raise RuntimeError(f"No {engine} voice for {lang}. Run: {backend.install_hint()}")
            _, name = parse_voice(profile["voice"], engine)
        if not backend.available():
            raise RuntimeError(f"{engine} TTS is unavailable. Run: {backend.install_hint()}")
        try:
            version = importlib.metadata.version(PACKAGES.get(engine, engine))
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        if hasattr(backend, "fingerprint"):
            version += ":" + backend.fingerprint(name)
        key = cache_key(engine, name, text, lang, rate, pitch, version)
        imports = self.workspace / "imports"
        folder = imports / "audio" / "tts"
        path = folder / (key + ".wav")
        target = None
        if output:
            target = (imports / output).resolve()
            if not target.is_relative_to(imports.resolve()) or target.suffix.lower() != ".wav":
                raise ValueError("TTS output must be a .wav path inside workspace/imports/")
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            cached = False
            if path.is_file():
                try:
                    with wave.open(str(path), "rb") as wav:
                        cached = (wav.getframerate() == audio.SAMPLE_RATE and wav.getnchannels() == 1
                                  and wav.getsampwidth() == 2 and wav.getnframes() > 0)
                except (wave.Error, EOFError):
                    pass
            if not cached:
                with tempfile.TemporaryDirectory(dir=folder) as tmp:
                    raw = Path(tmp) / "raw.wav"
                    backend.synthesize(text, name, lang, rate, pitch, raw)
                    samples, sr = audio.read(raw)
                    normalized = Path(tmp) / "normalized.wav"
                    audio.write(normalized, audio.normalize(samples, sr), sr)
                    os.replace(normalized, path)
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
            if target and target != path:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                path = target
        result = {"path": path.relative_to(imports).as_posix(), "duration_s": round(duration, 6),
                  "sample_rate": audio.SAMPLE_RATE, "engine": engine, "voice": f"{engine}:{name}",
                  "rate": rate, "pitch": pitch, "cached": cached}
        if backend.online:
            result["privacy"] = backend.privacy
        return result

    def prepare(self, lines, casting, language="id"):
        """Copy/prepare script beats or dialog lines. Existing recordings always win.

        Backend failures keep mouth-only behavior with an actionable warning; no
        retries on another engine (especially an online engine).
        """
        started = time.perf_counter()
        prepared, files, warnings, privacy = [], [], [], []
        failed = set()
        for source in lines:
            line = dict(source)
            ident = line.get("say", line.get("speaker"))
            profile = casting.get(ident)
            if ident and line.get("text") and not line.get("audio") and profile and ident not in failed:
                backend = self.backends[profile["engine"]]
                if profile["voice"] and backend.online and backend.available():
                    privacy.append(backend.privacy)
                try:
                    if not profile["voice"]:
                        raise RuntimeError(f"No voice for {language}. Run: {self.backends[profile['engine']].install_hint()}")
                    result = self.synthesize(line["text"], voice=profile["voice"],
                                             engine=profile["engine"], language=language,
                                             rate=profile["rate"], pitch=profile["pitch"])
                    line["audio"] = str(self.workspace / "imports" / result["path"])
                    line["tts_generated"] = True
                    files.append(dict(result, character=ident))
                    if result.get("privacy"):
                        privacy.append(result["privacy"])
                except Exception as exc:
                    warnings.append(f"{ident}: TTS unavailable; keeping mouth motion only. {exc}")
                    failed.add(ident)
            prepared.append(line)
        return prepared, {"generated_files": files, "cache_hits": sum(f["cached"] for f in files),
                          "warnings": warnings, "privacy": list(dict.fromkeys(privacy)),
                          "tts_seconds": round(time.perf_counter() - started, 4)}


def online_request(tool, arguments):
    """Shared UI consent predicate; inspects parsed descriptors as well as dicts."""
    if tool == "text_to_speech":
        engine, _ = parse_voice(arguments.get("voice"), arguments.get("engine", "piper"))
        return bool(REGISTRY[engine].online)
    if tool not in {"script_to_scene", "dialog"}:
        return False
    if not arguments.get("voice", tool == "script_to_scene") or arguments.get("build", True) is False:
        return False
    if tool == "script_to_scene":
        from engine.script_plan import parse_script
        characters = parse_script(arguments.get("script", ""))["characters"]
    else:
        characters = []
    choices = [arguments.get("tts_engine", "piper")]
    for char in characters:
        choices.append(parse_voice(char.get("voice"), arguments.get("tts_engine", "piper"))[0])
    for profile in arguments.get("voices", {}).values():
        profile = {"voice": profile} if isinstance(profile, str) else profile
        choices.append(parse_voice(profile.get("voice"), profile.get("engine", arguments.get("tts_engine", "piper")))[0])
    return any(REGISTRY[name].online for name in choices)
