"""Local synthetic HTTP transport load. This is not a production capacity benchmark."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        body = b'{"status":"ready"}'
        self.send_response(200);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length",0)))
        streaming = self.path.endswith("/stream")
        body = b'data: {"type":"token","text":"Synthetic"}\n\ndata: {"type":"done","response":{"answer":"Synthetic"}}\n\n' if streaming else b'{"answer":"Synthetic"}'
        self.send_response(200);self.send_header("Content-Type","text/event-stream" if streaming else "application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass


if __name__ == "__main__":
    import os
    from pathlib import Path
    class Server(ThreadingHTTPServer):
        request_queue_size = 256
        daemon_threads = True
    server = Server(("127.0.0.1",0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        for scenario in ("readiness","stream"):
            subprocess.run([sys.executable,str(Path(__file__).with_name("load_test.py")),"--base-url",f"http://127.0.0.1:{server.server_port}","--scenario",scenario,"--allow-paid-work","--output",f"load-fixture-{scenario}.json"],env={**os.environ,"OREAG_API_KEY":"synthetic","OREAG_PROJECT_ID":"synthetic"},check=True)
    finally:
        server.shutdown();server.server_close();thread.join()
