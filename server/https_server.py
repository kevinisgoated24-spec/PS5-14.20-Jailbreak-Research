#!/usr/bin/env python3
"""
https_server.py — Dual HTTP+HTTPS server for PS5 jailbreak delivery
HTTPS port 443 (PS5 browser requires HTTPS for some APIs)
HTTP  port 8080 (log endpoint — PS5 sends GET /log?t=TAG&d=DATA)

Usage: python https_server.py
Logs saved to: ps5_results/http_log.txt

Requires: openssl cert (server.crt + server.key) in same directory
Generate: openssl req -x509 -newkey rsa:2048 -keyout server.key -out server.crt -days 365 -nodes
"""
import http.server
import ssl
import threading
import os
import urllib.parse
from datetime import datetime

LOG_DIR = 'ps5_results'
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'http_log.txt')

# Serve from the exploit/ directory (one level up from server/)
SERVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'exploit')
SERVE_DIR = os.path.normpath(SERVE_DIR)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/log':
            params = urllib.parse.parse_qs(parsed.query)
            tag = params.get('t', ['?'])[0]
            data = params.get('d', [''])[0]
            ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            line = f'[{ts}] [{tag}] {data}'
            print(line)
            with open(LOG_FILE, 'a') as f:
                f.write(line + '\n')
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            super().do_GET()

    def log_message(self, fmt, *args):
        pass  # silence default access log

def run_http(port=8080):
    server = http.server.HTTPServer(('0.0.0.0', port), Handler)
    print(f'[*] HTTP  log server on :{port}')
    server.serve_forever()

def run_https(port=443):
    server = http.server.HTTPServer(('0.0.0.0', port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        cert_dir = os.path.dirname(os.path.abspath(__file__))
        ctx.load_cert_chain(
            os.path.join(cert_dir, 'server.crt'),
            os.path.join(cert_dir, 'server.key')
        )
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print(f'[*] HTTPS serve  on :{port} (dir={SERVE_DIR})')
    except FileNotFoundError:
        print('[!] No server.crt/server.key found — HTTPS disabled, HTTP only')
        print('[!] Generate: openssl req -x509 -newkey rsa:2048 -keyout server/server.key -out server/server.crt -days 365 -nodes')
        return
    server.serve_forever()

if __name__ == '__main__':
    print(f'[*] Serving exploit dir: {SERVE_DIR}')
    t1 = threading.Thread(target=run_http, daemon=True)
    t1.start()
    run_https()
