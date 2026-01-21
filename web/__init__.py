"""
Web module for Event Bot.

Provides FastAPI-based web server for webhook handling.
"""
from web.server import app, start_web_server, run_server

__all__ = ["app", "start_web_server", "run_server"]
