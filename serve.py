"""On-demand LAN presentation server. No source directory is exposed."""

import argparse
import ipaddress
import json
import secrets
import socket
import sys
import threading
import time
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import generate


WEB_DIR = Path(__file__).parent / "web"
COOKIE_NAME = "mdslides_session"


def lan_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            # UDP connect selects the local interface without sending a packet.
            probe.connect(("192.0.2.1", 80))
            address = probe.getsockname()[0]
        except OSError as error:
            raise RuntimeError("Impossible de detecter l'IP LAN. Utilisez --address IP.") from error
    if ipaddress.ip_address(address).is_loopback:
        raise RuntimeError("Aucune IP LAN detectee. Utilisez --address IP.")
    return address


class Presentation:
    def __init__(self, source: Path, font: str):
        meta, body = generate.parse_front_matter(source.read_text(encoding="utf-8"))
        self.slides = [slide for slide in generate.parse_content(body) if not generate.is_hidden_slide(slide)]
        if not self.slides:
            raise ValueError("La presentation ne contient aucune slide visible.")
        self.duration = generate.build_timer_seconds(meta)
        self.title = generate.build_page_title(meta)
        # Notes never appear in the HTML sent to the audience.
        public_slides = [{key: value for key, value in slide.items() if key != "notes"} for slide in self.slides]
        html = generate.build_html(
            public_slides, font, generate.build_footer_config(meta), self.title,
            str(source), str(source.parent), generate.normalize_theme(meta.get("theme")), self.duration,
        )
        html = generate.minify_html(html)
        html = html.replace("</head>", '<script src="/client.js" defer></script></head>')
        self.html = html.encode("utf-8")
        self.password = secrets.token_urlsafe(9)
        self.qr_token = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(8)
        self.sessions: set[str] = set()
        self.failures: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()
        self.index = 0
        self.started_at: float | None = None
        self.revision = 0

    def snapshot(self, private: bool) -> dict:
        with self.lock:
            state = {
                "index": self.index, "total": len(self.slides),
                "duration": self.duration,
                "elapsed": 0 if self.started_at is None else max(0, time.monotonic() - self.started_at),
                "running": self.started_at is not None,
                "revision": self.revision, "instance": self.instance,
                "authorized": private, "title": self.title,
            }
            if private:
                state["notes"] = self.slides[self.index].get("notes", [])
            return state

    def command(self, payload: dict) -> None:
        action = payload.get("action")
        with self.lock:
            if action == "next":
                index = self.index + 1
            elif action == "previous":
                index = self.index - 1
            elif action == "first":
                index = 0
            elif action == "last":
                index = len(self.slides) - 1
            elif action == "goto":
                index = payload.get("index")
                if type(index) is not int or not 0 <= index < len(self.slides):
                    raise ValueError("Numero de slide invalide.")
            elif action == "reset_timer":
                self.started_at = time.monotonic() if self.index > 0 and self.duration else None
                self.revision += 1
                return
            else:
                raise ValueError("Commande inconnue.")
            self.index = max(0, min(index, len(self.slides) - 1))
            if self.index > 0 and self.duration and self.started_at is None:
                self.started_at = time.monotonic()
            self.revision += 1

    def login(self, payload: dict, address: str) -> tuple[int, str]:
        with self.lock:
            count, since = self.failures.get(address, (0, time.monotonic()))
            if time.monotonic() - since >= 60:
                count, since = 0, time.monotonic()
            if count >= 10:
                return 429, "Trop de tentatives. Reessayez dans une minute."
            password = payload.get("password")
            token = payload.get("token")
            valid = (
                isinstance(password, str) and secrets.compare_digest(password.encode(), self.password.encode())
            ) or (
                isinstance(token, str) and secrets.compare_digest(token.encode(), self.qr_token.encode())
            )
            if not valid:
                self.failures[address] = (count + 1, since)
                return 401, "Mot de passe ou lien QR incorrect."
            self.failures.pop(address, None)
            session = secrets.token_urlsafe(32)
            self.sessions.add(session)
            return 200, session


class PresentationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], presentation: Presentation, lan_ip: str):
        super().__init__(address, Handler)
        self.presentation = presentation
        self.allowed_hosts = {lan_ip, "127.0.0.1", "localhost", address[0]}


class Handler(BaseHTTPRequestHandler):
    server: PresentationServer

    def log_message(self, format: str, *args) -> None:
        # Do not log URLs, credentials, or cookies.
        pass

    def respond(self, status: int, body: bytes, content_type: str, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # A phone can disconnect while a response is being written.
            return

    def json_response(self, status: int, data: dict, cookie: str | None = None) -> None:
        self.respond(status, json.dumps(data).encode(), "application/json; charset=utf-8", cookie)

    def allowed_request(self) -> bool:
        peer = ipaddress.ip_address(self.client_address[0])
        host = self.headers.get("Host", "")
        expected_hosts = {f"{name}:{self.server.server_port}" for name in self.server.allowed_hosts}
        if self.server.server_port == 80:
            expected_hosts.update(self.server.allowed_hosts)
        if not (peer.is_private or peer.is_loopback) or host not in expected_hosts:
            self.json_response(403, {"error": "Acces reserve au reseau local et aux adresses affichees."})
            return False
        return True

    def authorized(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        session = cookie.get(COOKIE_NAME)
        with self.server.presentation.lock:
            return session is not None and session.value in self.server.presentation.sessions

    def do_GET(self) -> None:
        if not self.allowed_request():
            return
        url = urlsplit(self.path)
        mode = parse_qs(url.query).get("mode", [""])[0]
        if url.path == "/" and mode in {"remote", "presenter"}:
            self.respond(200, (WEB_DIR / "remote.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path in {"/", "/slides"}:
            self.respond(200, self.server.presentation.html, "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self.json_response(200, self.server.presentation.snapshot(self.authorized()))
        elif url.path in {"/client.js", "/remote.js"}:
            self.respond(200, (WEB_DIR / url.path[1:]).read_bytes(), "text/javascript; charset=utf-8")
        else:
            self.json_response(404, {"error": "Ressource introuvable."})

    def do_POST(self) -> None:
        if not self.allowed_request():
            return
        # All clients send an explicit same-origin header, preventing CSRF and rebinding.
        expected_origin = f"http://{self.headers['Host']}"
        if self.headers.get("Origin") != expected_origin or self.headers.get("X-Mdslides") != "1":
            self.json_response(403, {"error": "Origine de la requete interdite."})
            return
        path = urlsplit(self.path).path
        if path not in {"/api/auth", "/api/command", "/api/logout"}:
            self.json_response(404, {"error": "Ressource introuvable."})
            return
        if path != "/api/auth" and not self.authorized():
            self.json_response(401, {"error": "Authentification requise."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Taille de requete invalide.")
            self.connection.settimeout(5)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Objet JSON attendu.")
        except (ValueError, UnicodeDecodeError, TimeoutError) as error:
            self.json_response(400, {"error": str(error)})
            return
        if path == "/api/auth":
            status, result = self.server.presentation.login(payload, self.client_address[0])
            if status != 200:
                self.json_response(status, {"error": result})
            else:
                self.json_response(200, {"ok": True}, f"{COOKIE_NAME}={result}; HttpOnly; SameSite=Strict; Path=/")
        elif path == "/api/logout":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            with self.server.presentation.lock:
                self.server.presentation.sessions.discard(cookie[COOKIE_NAME].value)
            self.json_response(200, {"ok": True}, f"{COOKIE_NAME}=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/")
        else:
            try:
                self.server.presentation.command(payload)
            except ValueError as error:
                self.json_response(400, {"error": str(error)})
                return
            self.json_response(200, self.server.presentation.snapshot(True))


def serve(source_file: str, font: str, args: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Diffusion des slides et telecommande sur le LAN.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--address", help="IP IPv4 de la machine sur le LAN (detection automatique par defaut)")
    options, _ = parser.parse_known_args(args)
    if not 0 <= options.port <= 65535:
        parser.error("--port doit etre compris entre 0 et 65535.")
    try:
        import qrcode
    except ImportError as error:
        raise RuntimeError("Installez les dependances : python3 -m pip install -r requirements.txt") from error
    ip = options.address or lan_address()
    parsed_ip = ipaddress.ip_address(ip)
    if parsed_ip.version != 4 or not parsed_ip.is_private or parsed_ip.is_unspecified:
        raise ValueError("--address doit etre une adresse IPv4 locale de cette machine.")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind((ip, 0))
    presentation = Presentation(Path(source_file).resolve(), font)
    with PresentationServer(("0.0.0.0", options.port), presentation, ip) as server:
        base = f"http://{ip}:{server.server_port}"
        remote = f"{base}/?mode=remote"
        qr = qrcode.QRCode(border=4)
        qr.add_data(f"{remote}#token={presentation.qr_token}")
        qr.make(fit=True)
        print(f"\nDiffusion : {base}/")
        print(f"Telecommande : {remote}")
        print(f"Mot de passe : {presentation.password}")
        print(f"Presentateur local : http://127.0.0.1:{server.server_port}/?mode=presenter#token={presentation.qr_token}")
        print("\nScannez ce QR code pour acceder directement a la telecommande :")
        qr.print_ascii(out=sys.stdout, invert=True)
        print("\nMeme reseau requis. Gardez le QR code prive. Ctrl+C pour arreter.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServeur arrete.")
