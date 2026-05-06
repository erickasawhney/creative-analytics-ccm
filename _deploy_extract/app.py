import os
import runpy
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():
    host = os.getenv("HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))

    def run_server():
        try:
            server = ThreadingHTTPServer((host, port), HealthHandler)
            server.serve_forever()
        except OSError:
            # If another process already owns PORT, avoid crashing.
            pass

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()


start_health_server()

# Delegate to the existing Streamlit application script.
APP_SCRIPT = os.path.join(os.path.dirname(__file__), "creative-analytics-ccm.py")
runpy.run_path(APP_SCRIPT, run_name="__main__")
