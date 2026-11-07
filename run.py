#!/usr/bin/env python3
"""HDD Hunter — surveille les prix des disques durs serveur 24 h/24.
Interface : http://127.0.0.1:8777"""
import logging
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

import uvicorn

from hddhunter import db
from hddhunter.scanner import Scanner
from hddhunter.web import create_app


def main():
    handlers = [RotatingFileHandler(db.DATA / "hddhunter.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%d/%m %H:%M:%S", handlers=handlers)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = db.load_config()
    scanner = Scanner()
    threading.Thread(target=scanner.loop, daemon=True, name="scanner").start()
    if "--open" in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[f"http://127.0.0.1:{cfg['port']}"]).start()
    uvicorn.run(create_app(scanner), host="127.0.0.1", port=cfg["port"], log_level="warning")


if __name__ == "__main__":
    main()
