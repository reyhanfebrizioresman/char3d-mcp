"""One offline CPU F5 model, JSON-lines on stdin/stdout. Run with F5's Python.

Only this subprocess imports torch. stdout belongs exclusively to the protocol;
third-party progress/logging goes to stderr. Parent EOF exits and releases RAM.
"""
import contextlib
import json
import os
import socket
import sys
import time
from concurrent.futures import Future


class SerialChunks:
    """F5's CPU chunks share a model and mutable text caches; run on one thread.

    The upstream default executor can evaluate several chunks on that same model
    at once and multiplies CPU pools. Native torch kernels still use the configured
    intra-op threads. Future keeps the upstream result/exception contract intact.
    """
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, function, *args, **kwargs):
        result = Future()
        try:
            result.set_result(function(*args, **kwargs))
        except Exception as exc:
            result.set_exception(exc)
        return result


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      WANDB_MODE="disabled", TOKENIZERS_PARALLELISM="false")
    # Offline means no network even if a dependency ignores Hugging Face flags.
    def offline(*args, **kwargs):
        raise RuntimeError("F5 offline worker blocked network access; install missing files explicitly")
    socket.socket.connect = offline
    socket.create_connection = offline
    protocol = sys.stdout
    model = None
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            started, cpu = time.perf_counter(), time.process_time()
            with contextlib.redirect_stdout(sys.stderr):
                if request["op"] == "init":
                    import torch
                    torch.set_num_threads(int(request.get("threads", 2)))
                    torch.set_num_interop_threads(1)
                    # F5 reads WAV references only. Recent torchaudio routes load
                    # through optional torchcodec/FFmpeg shared libraries, which
                    # are often incompatible with a CPU install. Decode locally
                    # with the already-required libsndfile instead.
                    import torchaudio
                    import soundfile
                    def load_wav(path, *args, **kwargs):
                        samples, sr = soundfile.read(path, dtype='float32', always_2d=True)
                        return torch.from_numpy(samples.T.copy()), sr
                    torchaudio.load = load_wav
                    from f5_tts.infer import utils_infer
                    utils_infer.ThreadPoolExecutor = SerialChunks
                    from f5_tts.api import F5TTS
                    model = F5TTS(model="F5TTS_Base", ckpt_file=request["checkpoint"],
                                  vocab_file=request["vocab"], vocoder_local_path=request["vocoder"],
                                  device="cpu")
                    if request.get('quantize'):
                        # CPU-only optional dynamic int8 linear layers; float
                        # attention/convolutions and vocoder remain unchanged.
                        model.ema_model = torch.ao.quantization.quantize_dynamic(
                            model.ema_model, {torch.nn.Linear}, dtype=torch.qint8)
                    result = dict(ready=True)
                elif request["op"] == "synthesize":
                    if model is None:
                        raise RuntimeError("Worker not initialized")
                    if not request["reference_text"].strip():
                        raise ValueError("Reference transcript required; ASR/downloads are disabled")
                    samples, rate, _ = model.infer(
                        ref_file=request["voice_reference"], ref_text=request["reference_text"],
                        gen_text=request["text"], speed=request["rate"], seed=0,
                        nfe_step=request["steps"], show_info=lambda *a: None, progress=None)
                    import soundfile
                    # Preserve float headroom until the shared speech normalizer;
                    # quantizing/clipping here would be irreversible upstream.
                    soundfile.write(request["output"], samples, rate, subtype="FLOAT")
                    result = dict(sample_rate=rate, duration_s=len(samples)/rate)
                else:
                    raise ValueError("Unknown worker operation")
            result.update(wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
                          chunk_execution='serial', torch_threads=torch.get_num_threads())
            response = dict(id=request["id"], ok=True, result=result)
        except Exception as exc:
            response = dict(id=request.get("id"), ok=False, error=f"{type(exc).__name__}: {exc}")
        protocol.write(json.dumps(response)+"\n")
        protocol.flush()


if __name__ == "__main__":
    main()
