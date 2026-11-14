"""Entry point executed *inside* Blender.

    blender -b --factory-startup --python engine/bootstrap.py -- --port 9876 --workspace ./output

Starts a blocking JSON-lines RPC server on localhost. Blender's Python API is
not thread-safe, so every request is handled sequentially on the main thread.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import server  # noqa: E402


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9876)
    p.add_argument("--workspace", default=os.path.join(ROOT, "output"))
    args = p.parse_args(argv)
    server.serve(args.host, args.port, os.path.abspath(args.workspace))


main()
