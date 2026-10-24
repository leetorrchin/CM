"""python -m crowd_server [--host 0.0.0.0] [--port 8000]"""
import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    uvicorn.run("crowd_server.app:app_factory", factory=True, host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
