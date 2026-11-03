"""Serve ~/eggball-live/site on 127.0.0.1:8100 and let any page fetch it (CORS), so the GitHub Pages copy
(bambitp.github.io/eggball-stats/live.html) can load the live pages into itself."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, *args):
        pass


ThreadingHTTPServer(('127.0.0.1', 8100), functools.partial(Handler, directory='/home/metjr/eggball-live/site')).serve_forever()
