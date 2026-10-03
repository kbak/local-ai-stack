"""Browser forward proxy: public HTTP(S) destinations only, DNS pinned at connect."""
import select
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from stack_shared.public_http import public_addresses


def relay_sockets(downstream, upstream):
    downstream.settimeout(30)
    upstream.settimeout(30)
    while True:
        readable, _, _ = select.select([downstream, upstream], [], [], 60)
        if not readable:
            return
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            (upstream if source is downstream else downstream).sendall(data)


class SteelControlRelay(socketserver.BaseRequestHandler):
    """Fixed control-plane destination, never chosen by a page or agent."""
    def handle(self):
        try:
            with socket.create_connection(('steel-browser', self.server.server_address[1]), timeout=20) as upstream:
                relay_sockets(self.request, upstream)
        except OSError:
            pass


class ControlServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def connect_public(host, port):
    if port not in (80, 443):
        raise ValueError("Only HTTP/HTTPS ports are allowed")
    address = public_addresses(host, port)[0]
    return socket.create_connection((address, port), timeout=20)


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    rbufsize = 0  # Leave request bodies on the socket for the tunnel relay.

    def relay(self, upstream):
        # Includes WebSocket and TLS traffic; tunnel destination was approved.
        relay_sockets(self.connection, upstream)

    def do_CONNECT(self):
        try:
            target = urlsplit("//" + self.path)
            if not target.hostname or target.username or target.path:
                raise ValueError("Invalid tunnel destination")
            upstream = connect_public(target.hostname, target.port or 443)
        except (ValueError, OSError):
            self.send_error(403, "Destination blocked or unavailable")
            return
        self.close_connection = True
        with upstream:
            self.send_response(200, "Connection Established")
            self.end_headers()
            self.wfile.flush()
            self.relay(upstream)

    def forward(self):
        try:
            target = urlsplit(self.path)
            if target.scheme != "http" or not target.hostname or target.username:
                raise ValueError("Invalid HTTP destination")
            upstream = connect_public(target.hostname, target.port or 80)
        except (ValueError, OSError):
            self.send_error(403, "Destination blocked or unavailable")
            return
        self.close_connection = True
        with upstream:
            path = target.path or "/"
            if target.query:
                path += "?" + target.query
            # One request per connection prevents reusing a public upstream
            # socket for a subsequent differently addressed proxy request.
            headers = [f"{self.command} {path} HTTP/1.1", f"Host: {target.netloc}"]
            for key, value in self.headers.items():
                if key.lower() not in {"host", "connection", "proxy-connection", "proxy-authorization"}:
                    headers.append(f"{key}: {value}")
            headers.append("Connection: Upgrade" if self.headers.get("Upgrade") else "Connection: close")
            upstream.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("latin-1"))
            self.relay(upstream)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = forward

    def log_message(self, format, *args):
        # Never log page URLs, which may contain account tokens.
        pass


if __name__ == "__main__":
    # Docker does not publish ports from a container on an internal-only
    # network. Preserve the existing host-local Steel UI/CDP endpoints here.
    for port in (3000, 9223):
        server = ControlServer(("0.0.0.0", port), SteelControlRelay)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8094), Proxy).serve_forever()
