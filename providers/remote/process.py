"""Bounded transport subprocesses, including ProxyCommand descendants and inherited pipes."""
import os
import signal
import subprocess


def run_bounded(argv, *, input=None, timeout=30, env=None, text=False, encoding='utf-8', **unused):
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    data = input.encode(encoding) if isinstance(input, str) else input
    try:
        stdout, stderr = proc.communicate(data, timeout=timeout)
    except BaseException:
        # Killing only ssh leaves a hung jump ssh holding stdout/stderr open. Kill
        # this owned session's process group and never perform an unbounded drain.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe:
                pipe.close()
        raise
    if text:
        stdout, stderr = stdout.decode(encoding, errors='replace'), stderr.decode(encoding, errors='replace')
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
