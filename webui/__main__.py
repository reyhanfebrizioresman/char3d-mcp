import argparse
import os

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="char3d — studio lokal")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CHAR3D_WEBUI_PORT", "8765")))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port harus berada di antara 1 dan 65535")
    from .app import create_app

    print(f"char3d Studio → http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(create_app(args.port), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
