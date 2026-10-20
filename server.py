import os
import re
import sys
import ssl
import time
import socket
import shutil
import platform
import threading
import subprocess
from datetime import datetime, timezone, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import request, Response, jsonify
from werkzeug.serving import make_server

# Import the existing Engine singletons without modifying nvidia_rp_cleaner.py
from nvidia_rp_cleaner import (
    app,
    engine,
    set_http_session,
    TermColors,
    NVIDIA_BASE_URL,
)

DEFAULT_HTTPS_PORT = int(os.environ.get("SERVER_HTTPS_PORT", 8443))
DEFAULT_HTTP_PORT = int(os.environ.get("SERVER_HTTP_PORT", 5000))
CERT_FILE = os.environ.get("SERVER_CERT_FILE", "localhost.pem")
KEY_FILE = os.environ.get("SERVER_KEY_FILE", "localhost-key.pem")


class ServerRuntimeState:
    """
    Holds live networking state, SSL certificate metadata, LAN IP addresses,
    and connectivity diagnostics so cli.py can inspect and control the server.
    """
    def __init__(self):
        self.lock = threading.RLock()
        self.is_running = False
        self.https_port = DEFAULT_HTTPS_PORT
        self.http_port = DEFAULT_HTTP_PORT
        self.http_redirect_port = DEFAULT_HTTP_PORT  # Backward compatibility alias for cli.py
        self.bind_host = "0.0.0.0"
        self.lan_ip = "127.0.0.1"
        self.all_lan_ips = ["127.0.0.1"]
        self.platform_name = "Unknown"
        self.cert_path = os.path.abspath(CERT_FILE)
        self.key_path = os.path.abspath(KEY_FILE)
        self.cert_trusted = False
        self.cert_trust_detail = "Unverified"
        self.internet_online = False
        self.nvidia_reachable = False
        self.last_net_check = 0.0
        self.last_net_error = None
        self.https_server = None
        self.http_server = None
        self.ipv6_http_server = None
        self.ipv6_https_server = None
        self.server_thread = None
        self.http_thread = None


server_state = ServerRuntimeState()


def detect_platform_environment():
    """
    Detects whether the script is running inside Android Termux, Linux,
    Windows, or macOS so IP discovery and certificate trust adapt dynamically.
    """
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix or os.path.exists("/data/data/com.termux"):
        return "Android (Termux)"
    sys_name = platform.system()
    if sys_name == "Windows":
        return "Windows"
    if sys_name == "Darwin":
        return "macOS"
    if sys_name == "Linux":
        return "Linux"
    return sys_name or "Unknown OS"


def discover_lan_ips():
    """
    Dynamically discovers the device's active Wi-Fi / LAN IPv4 addresses across
    Android Termux, Windows, Linux, and macOS without crashing if offline.
    Returns (primary_lan_ip, list_of_all_lan_ips).
    """
    candidates = []

    def add_ip(ip_str):
        if not ip_str or not isinstance(ip_str, str):
            return
        ip_str = ip_str.strip()
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip_str):
            if not ip_str.startswith("127.") and not ip_str.startswith("169.254.") and ip_str != "0.0.0.0":
                if ip_str not in candidates:
                    candidates.append(ip_str)

    # Method 1: UDP Routing Table Probe
    for target in [("8.8.8.8", 80), ("1.1.1.1", 80), ("192.168.1.1", 80), ("10.0.0.1", 80)]:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(target)
            add_ip(s.getsockname()[0])
            if candidates:
                break
        except Exception:
            pass
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    # Method 2: OS-Specific Interface Commands
    commands_to_try = [
        ["ip", "-4", "addr", "show"],
        ["ifconfig"],
        ["hostname", "-I"],
        ["ipconfig"],
    ]
    for cmd in commands_to_try:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.0,
                encoding="utf-8",
                errors="ignore"
            )
            output = proc.stdout or ""
            if output:
                wlan_matches = re.findall(
                    r"(?:wlan\d+|en\d+|wi-fi|wireless)[\s\S]{1,350}?inet(?: addr:)?\s*(\d{1,3}(?:\.\d{1,3}){3})",
                    output,
                    flags=re.IGNORECASE
                )
                for m in wlan_matches:
                    add_ip(m)

                general_matches = re.findall(
                    r"(?:inet(?: addr:)?|IPv4 Address[.\s]*:)\s*(\d{1,3}(?:\.\d{1,3}){3})",
                    output,
                    flags=re.IGNORECASE
                )
                for m in general_matches:
                    add_ip(m)
        except Exception:
            continue

    # Method 3: Hostname Resolution Fallback
    try:
        hostname = socket.gethostname()
        _, _, ip_list = socket.gethostbyname_ex(hostname)
        for ip in ip_list:
            add_ip(ip)
    except Exception:
        pass

    def score_ip(ip):
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", ip):
            return 2
        return 3

    candidates.sort(key=score_ip)
    primary_ip = candidates[0] if candidates else "127.0.0.1"
    all_ips = candidates if candidates else ["127.0.0.1"]
    return primary_ip, all_ips


def check_nvidia_and_internet_connectivity(timeout=5.0):
    """
    Verifies whether the device has an active network connection and can reach
    NVIDIA's API endpoint (`integrate.api.nvidia.com`) without crashing.
    """
    primary_ip, all_ips = discover_lan_ips()
    has_lan = primary_ip != "127.0.0.1"

    try:
        nvidia_host = "integrate.api.nvidia.com"
        resolved_ip = socket.gethostbyname(nvidia_host)
    except OSError as dns_err:
        msg = (
            "No Internet / DNS Resolution Failed: Unable to resolve 'integrate.api.nvidia.com'. "
            "Please check that your Wi-Fi or mobile data is turned on."
        )
        with server_state.lock:
            server_state.lan_ip = primary_ip
            server_state.all_lan_ips = all_ips
            server_state.internet_online = False
            server_state.nvidia_reachable = False
            server_state.last_net_check = time.time()
            server_state.last_net_error = msg
        return {
            "ok": False,
            "has_lan": has_lan,
            "lan_ip": primary_ip,
            "nvidia_reachable": False,
            "message": msg,
            "detail": str(dns_err)
        }

    try:
        resp = requests.get(
            f"{NVIDIA_BASE_URL}/models",
            timeout=timeout
        )
        reachable = resp.status_code in [200, 401, 403, 404]
        with server_state.lock:
            server_state.lan_ip = primary_ip
            server_state.all_lan_ips = all_ips
            server_state.internet_online = True
            server_state.nvidia_reachable = reachable
            server_state.last_net_check = time.time()
            server_state.last_net_error = None if reachable else f"HTTP {resp.status_code}"

        return {
            "ok": reachable,
            "has_lan": has_lan,
            "lan_ip": primary_ip,
            "resolved_nvidia_ip": resolved_ip,
            "nvidia_reachable": reachable,
            "message": "Connected to Wi-Fi/Network and NVIDIA NIM API is reachable."
        }
    except requests.exceptions.RequestException as req_err:
        msg = (
            "Network Unreachable: Cannot connect to NVIDIA server (https://integrate.api.nvidia.com). "
            "Check your internet connection, firewall, or VPN."
        )
        with server_state.lock:
            server_state.lan_ip = primary_ip
            server_state.all_lan_ips = all_ips
            server_state.internet_online = False
            server_state.nvidia_reachable = False
            server_state.last_net_check = time.time()
            server_state.last_net_error = msg
        return {
            "ok": False,
            "has_lan": has_lan,
            "lan_ip": primary_ip,
            "nvidia_reachable": False,
            "message": msg,
            "detail": str(req_err)
        }


class ResilientNvidiaSession:
    """
    Wraps `requests.Session` with high-concurrency connection pooling, TCP keep-alive,
    and graceful offline/DNS failure interception.
    """
    def __init__(self, pool_connections=100, pool_maxsize=100):
        self._session = requests.Session()
        retry_strategy = Retry(
            total=2,
            connect=1,
            read=1,
            backoff_factor=0.6,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _build_offline_response(self, friendly_message):
        c = TermColors
        now_str = datetime.now().strftime("%H:%M:%S")
        print(
            f"{c.DIM}[{now_str}]{c.RESET} {c.BOLD}{c.RED}⚠️ NETWORK OFFLINE:{c.RESET} "
            f"{c.YELLOW}{friendly_message}{c.RESET}",
            flush=True
        )
        synthetic = requests.Response()
        synthetic.status_code = 503
        synthetic.encoding = "utf-8"
        synthetic.headers["Content-Type"] = "application/json; charset=utf-8"
        payload = {
            "error": {
                "message": friendly_message,
                "type": "network_unavailable",
                "code": "wifi_or_nvidia_unreachable"
            }
        }
        import json
        synthetic._content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return synthetic

    def post(self, url, *args, **kwargs):
        try:
            return self._session.post(url, *args, **kwargs)
        except requests.exceptions.ConnectionError:
            return self._build_offline_response(
                "Device is not connected to Wi-Fi/Internet or cannot reach NVIDIA servers (integrate.api.nvidia.com). "
                "Please reconnect to Wi-Fi and try again."
            )
        except requests.exceptions.Timeout:
            return self._build_offline_response(
                "Connection to NVIDIA server timed out. Your internet connection may be unstable or NVIDIA NIM is overloaded."
            )
        except requests.exceptions.RequestException as e:
            return self._build_offline_response(
                f"Network error while communicating with NVIDIA server: {str(e)}"
            )

    def get(self, url, *args, **kwargs):
        try:
            return self._session.get(url, *args, **kwargs)
        except requests.exceptions.RequestException as e:
            return self._build_offline_response(
                f"Unable to reach NVIDIA server: {str(e)}"
            )

    def __getattr__(self, name):
        return getattr(self._session, name)


def auto_trust_certificate_cross_platform(cert_path, platform_name):
    """
    Attempts to register `localhost.pem` in the local OS/Browser certificate store
    so Chrome, Edge, Brave, and Safari trust `https://localhost:8443` and `https://<LAN_IP>:8443`
    without throwing `NET::ERR_CERT_AUTHORITY_INVALID`.
    Also always safe because plain HTTP on port 5000 & 8443 is simultaneously enabled!
    """
    try:
        if platform_name == "Windows":
            # Check if already in Windows CurrentUser Root store to avoid repeated popup prompts
            check_proc = subprocess.run(
                ["certutil", "-user", "-verifystore", "Root", "NVIDIAFKU Local Root CA"],
                capture_output=True,
                text=True,
                timeout=4
            )
            if check_proc.returncode == 0:
                return True, "Trusted in Windows User Root Store"

            add_proc = subprocess.run(
                ["certutil", "-user", "-addstore", "-f", "Root", cert_path],
                capture_output=True,
                text=True,
                timeout=15
            )
            if add_proc.returncode == 0:
                return True, "Installed into Windows User Root Store"
            return False, "Windows Root Store skipped (Use http://localhost:5000 for zero warnings)"

        elif platform_name == "Linux":
            # Install into user NSS database (~/.pki/nssdb) used by Chrome/Edge/Brave on Linux
            nss_dir = os.path.expanduser("~/.pki/nssdb")
            if shutil.which("certutil") and os.path.isdir(nss_dir):
                res = subprocess.run(
                    [
                        "certutil", "-d", f"sql:{nss_dir}",
                        "-A", "-t", "C,,",
                        "-n", "NVIDIAFKU Local Root CA",
                        "-i", cert_path
                    ],
                    capture_output=True,
                    timeout=5
                )
                if res.returncode == 0:
                    return True, "Trusted in Linux Browser NSS Store (~/.pki/nssdb)"
            return False, "Use http://localhost:5000 for instant warning-free connection"

        elif platform_name == "macOS":
            # Attempt non-interactive login keychain trust
            login_kc = os.path.expanduser("~/Library/Keychains/login.keychain-db")
            if os.path.exists(login_kc):
                res = subprocess.run(
                    ["security", "add-trusted-cert", "-r", "trustRoot", "-k", login_kc, cert_path],
                    capture_output=True,
                    timeout=5
                )
                if res.returncode == 0:
                    return True, "Trusted in macOS Login Keychain"
            return False, "Use http://localhost:5000 for instant warning-free connection"

        elif "Termux" in platform_name:
            # On Android Termux, http://localhost:5000 is natively a W3C Secure Context in Android Chrome/Brave
            return True, "Termux Localhost Secure Context Active (http://localhost:5000 & https://8443)"

    except Exception as e:
        return False, f"Auto-trust skipped ({type(e).__name__})"

    return False, "Self-signed certificate active"


def ensure_ssl_certificates(cert_file=CERT_FILE, key_file=KEY_FILE, lan_ips=None):
    """
    Ensures `localhost.pem` and `localhost-key.pem` exist, cover both `localhost` (127.0.0.1)
    and active Wi-Fi LAN IPs via Subject Alternative Names (SAN), and include modern
    KeyUsage + ExtendedKeyUsage (serverAuth) extensions required by Edge/Chrome/Safari.
    """
    cert_path = os.path.abspath(cert_file)
    key_path = os.path.abspath(key_file)
    ips = list(set(["127.0.0.1"] + [ip for ip in (lan_ips or []) if ip]))

    # Strategy 0: If the user has `mkcert` installed on Windows/macOS/Linux/Termux, use it!
    if shutil.which("mkcert"):
        try:
            subprocess.run(["mkcert", "-install"], capture_output=True, timeout=10)
            mk_cmd = ["mkcert", "-cert-file", cert_path, "-key-file", key_path, "localhost", "127.0.0.1", "::1"] + [
                ip for ip in ips if ip != "127.0.0.1"
            ]
            res = subprocess.run(mk_cmd, capture_output=True, timeout=10)
            if res.returncode == 0 and os.path.exists(cert_path) and os.path.exists(key_path):
                with server_state.lock:
                    server_state.cert_trusted = True
                    server_state.cert_trust_detail = "Trusted via mkcert Root CA"
                return cert_path, key_path
        except Exception:
            pass

    # Check if existing certificate is valid and covers current LAN IPs
    regenerate = True
    if os.path.exists(cert_path) and os.path.exists(key_path):
        try:
            test_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            test_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            # Check if current primary LAN IP is inside the cert SANs
            import ipaddress
            from cryptography import x509
            with open(cert_path, "rb") as cf:
                existing_cert = x509.load_pem_x509_certificate(cf.read())
            san_ext = existing_cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            cert_ips = [str(ip_obj) for ip_obj in san_ext.value.get_values_for_type(x509.IPAddress)]
            if all(ip in cert_ips for ip in ips):
                regenerate = False
        except Exception:
            regenerate = True

    if regenerate:
        # Strategy 1: Generate compliant X.509 Root CA + SAN Certificate using `cryptography`
        try:
            import ipaddress
            from cryptography import x509
            from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa

            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NVIDIAFKU Local Root CA"),
                x509.NameAttribute(NameOID.COMMON_NAME, "NVIDIAFKU Local Root CA"),
            ])

            san_entries = [
                x509.DNSName("localhost"),
                x509.DNSName("*.local"),
            ]
            for ip_str in ips:
                try:
                    san_entries.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
                except Exception:
                    pass

            now_utc = datetime.now(timezone.utc)
            # Modern Chrome/Edge/Safari reject certs valid for >398 days unless they are Root CAs
            # with explicit KeyUsage (key_cert_sign + digital_signature + key_encipherment)
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now_utc - timedelta(days=1))
                .not_valid_after(now_utc + timedelta(days=397))
                .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(
                    x509.KeyUsage(
                        digital_signature=True,
                        content_commitment=False,
                        key_encipherment=True,
                        data_encipherment=False,
                        key_agreement=False,
                        key_cert_sign=True,
                        crl_sign=True,
                        encipher_only=False,
                        decipher_only=False,
                    ),
                    critical=True,
                )
                .add_extension(
                    x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                    critical=False,
                )
                .sign(private_key, hashes.SHA256())
            )

            with open(key_path, "wb") as kf:
                kf.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )

            with open(cert_path, "wb") as cf:
                cf.write(cert.public_bytes(serialization.Encoding.PEM))
        except Exception:
            # Strategy 2: Fallback to `openssl` CLI (Termux, Linux, macOS, Git-for-Windows)
            try:
                san_list = ["DNS:localhost", "IP:127.0.0.1"] + [f"IP:{ip}" for ip in ips if ip != "127.0.0.1"]
                san_ext = ",".join(san_list)
                cmd = [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key_path,
                    "-out", cert_path,
                    "-days", "397",
                    "-subj", "/CN=NVIDIAFKU Local Root CA",
                    "-addext", f"subjectAltName={san_ext}"
                ]
                res = subprocess.run(cmd, capture_output=True, timeout=10)
                if res.returncode != 0:
                    cmd_basic = [
                        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", key_path,
                        "-out", cert_path,
                        "-days", "397",
                        "-subj", "/CN=NVIDIAFKU Local Root CA"
                    ]
                    subprocess.run(cmd_basic, capture_output=True, timeout=10, check=True)
            except Exception as e:
                raise RuntimeError(
                    f"Could not generate '{cert_file}' and '{key_file}'. "
                    f"Install 'cryptography' (`pip install cryptography`) or 'openssl'. Details: {e}"
                )

    # Attempt OS certificate store registration so https://localhost:8443 has no red screen
    trusted_ok, trust_msg = auto_trust_certificate_cross_platform(cert_path, server_state.platform_name)
    with server_state.lock:
        server_state.cert_trusted = trusted_ok
        server_state.cert_trust_detail = trust_msg

    return cert_path, key_path


class PolyglotHTTPAndHTTPSServer:
    """
    Smart Single-Port Multiplexer on Port 8443!
    Peeks at the first byte of every incoming connection on Port 8443:
      - If byte == 0x16 (TLS ClientHello): Wraps the socket in SSL/TLS (`https://...:8443`).
      - If byte is plain ASCII ('G', 'P', 'O', etc.): Passes the raw socket directly
        to Flask/Werkzeug so `http://localhost:8443` and `http://<LAN_IP>:8443` ALSO
        work natively without SSL errors or redirect loops!
    """
    @staticmethod
    def wrap_wsgi_server_polyglot(wsgi_server, ssl_context):
        raw_socket = wsgi_server.socket

        class PolyglotSocketWrapper:
            def __init__(self, base_sock):
                self._base_sock = base_sock

            def accept(self):
                client_sock, client_addr = self._base_sock.accept()
                try:
                    client_sock.settimeout(5.0)
                    first_byte = client_sock.recv(1, socket.MSG_PEEK)
                    if first_byte and first_byte[0] == 0x16:
                        # TLS Handshake detected -> Serve over HTTPS!
                        tls_sock = ssl_context.wrap_socket(client_sock, server_side=True)
                        return tls_sock, client_addr
                    else:
                        # Plain HTTP request detected -> Serve directly over HTTP without SSL error!
                        return client_sock, client_addr
                except Exception:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                    raise

            def __getattr__(self, name):
                return getattr(self._base_sock, name)

        wsgi_server.socket = PolyglotSocketWrapper(raw_socket)
        return wsgi_server


_middleware_attached = False


def _apply_universal_cors_headers(response):
    """
    Applies WhatWG Fetch & Chrome Private Network Access (CORS-RFC1918) compliant headers.
    Crucially avoids combining `Access-Control-Allow-Origin: *` with
    `Access-Control-Allow-Credentials: true`, which causes Chrome/Edge/Brave on
    Android & Windows to abort `fetch('http://localhost:5000/...')` with `Failed to fetch`.
    """
    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers.pop("Access-Control-Allow-Credentials", None)

    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"

    req_headers = request.headers.get("Access-Control-Request-Headers")
    if req_headers:
        response.headers["Access-Control-Allow-Headers"] = req_headers
    else:
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-Requested-With, Accept, Origin, "
            "X-Thinking, X-Enable-Thinking, X-Model-Override, X-RP-Mode, OpenAI-Beta, HTTP-Referer, X-Title"
        )

    # Required by Chrome / Edge / Brave for HTTPS websites calling http://127.0.0.1 or http://localhost
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def attach_server_middleware_and_routes():
    """
    Attaches Private Network Access (CORS-RFC1918) headers for LAN & localhost browsers,
    pre-request Wi-Fi/internet guard, `/v1/engine/cert.crt` for mobile LAN certificate
    installation, and `/v1/engine/network` onto the imported Flask `app` without
    modifying `nvidia_rp_cleaner.py`.
    """
    global _middleware_attached
    if _middleware_attached:
        return

    app.url_map.strict_slashes = False

    @app.before_request
    def network_guard_and_preflight():
        # Handle CORS + Private Network preflight immediately with exact Origin reflection
        if request.method == "OPTIONS":
            resp = Response(status=204)
            return _apply_universal_cors_headers(resp)

        # Pre-flight check on chat completions if Wi-Fi/Internet is completely down
        if request.path.endswith("/chat/completions") and request.method == "POST":
            try:
                socket.gethostbyname("integrate.api.nvidia.com")
                with server_state.lock:
                    server_state.internet_online = True
            except OSError:
                with server_state.lock:
                    server_state.internet_online = False
                    server_state.nvidia_reachable = False
                c = TermColors
                now_str = datetime.now().strftime("%H:%M:%S")
                print(
                    f"{c.DIM}[{now_str}]{c.RESET} {c.BOLD}{c.RED}❌ NO INTERNET / WI-FI DISCONNECTED:{c.RESET} "
                    f"{c.YELLOW}Cannot reach NVIDIA server (integrate.api.nvidia.com).{c.RESET}",
                    flush=True
                )
                err_resp = jsonify({
                    "error": {
                        "message": (
                            "No Internet Connection: Your device is offline or not connected to Wi-Fi, "
                            "so the server cannot reach NVIDIA's API (integrate.api.nvidia.com). "
                            "Please check your Wi-Fi / mobile data connection and try again."
                        ),
                        "type": "network_offline_error",
                        "code": "nvidia_unreachable"
                    }
                })
                err_resp.status_code = 503
                return _apply_universal_cors_headers(err_resp)

    @app.after_request
    def add_lan_and_private_network_headers(response):
        # Preserve valid Origin reflection instead of overwriting with "*"
        return _apply_universal_cors_headers(response)

    @app.route("/v1/engine/cert.crt", methods=["GET"])
    @app.route("/cert.crt", methods=["GET"])
    def download_lan_certificate():
        """
        Allows any phone/tablet/PC on the Wi-Fi LAN to visit `http://<LAN_IP>:5000/cert.crt`
        and install the certificate with one tap if they want trusted HTTPS over LAN.
        """
        if os.path.exists(server_state.cert_path):
            with open(server_state.cert_path, "rb") as f:
                pem_bytes = f.read()
            return Response(
                pem_bytes,
                status=200,
                mimetype="application/x-x509-ca-cert",
                headers={"Content-Disposition": 'attachment; filename="nvidiafku-ca.crt"'}
            )
        return jsonify({"error": "Certificate file not found"}), 404

    @app.route("/v1/engine/network", methods=["GET"])
    def engine_network_diagnostics():
        """REST endpoint for cli.py to inspect live LAN IP, HTTP/HTTPS URLs, and NVIDIA reachability."""
        refresh = request.args.get("refresh", "false").lower() in ["1", "true", "yes"]
        if refresh or (time.time() - server_state.last_net_check > 30):
            check_nvidia_and_internet_connectivity(timeout=3.0)

        with server_state.lock:
            return jsonify({
                "status": "running" if server_state.is_running else "idle",
                "dual_stack_http_https": True,
                "platform": server_state.platform_name,
                "https_port": server_state.https_port,
                "http_port": server_state.http_port,
                "localhost_http_url": f"http://127.0.0.1:{server_state.http_port}/v1/chat/completions",
                "localhost_url": f"https://localhost:{server_state.https_port}/v1/chat/completions",
                "lan_http_url": f"http://{server_state.lan_ip}:{server_state.http_port}/v1/chat/completions",
                "lan_url": f"https://{server_state.lan_ip}:{server_state.https_port}/v1/chat/completions",
                "lan_cert_download": f"http://{server_state.lan_ip}:{server_state.http_port}/cert.crt",
                "lan_ip": server_state.lan_ip,
                "all_lan_ips": server_state.all_lan_ips,
                "ssl_cert": server_state.cert_path,
                "ssl_key": server_state.key_path,
                "cert_trusted": server_state.cert_trusted,
                "cert_trust_detail": server_state.cert_trust_detail,
                "internet_online": server_state.internet_online,
                "nvidia_reachable": server_state.nvidia_reachable,
                "last_network_error": server_state.last_net_error,
            })

    _middleware_attached = True


def _start_optional_ipv6_loopback_listener(port, ssl_ctx=None):
    """
    On Windows 11 and Android, `localhost` often resolves to IPv6 `::1` first.
    If Werkzeug only listens on IPv4 `0.0.0.0`, `fetch('http://localhost:5000')` fails!
    This spins up an auxiliary `::1` listener so both `localhost` (IPv6) and `127.0.0.1` (IPv4) work.
    """
    if not getattr(socket, "has_ipv6", False):
        return None
    try:
        srv_v6 = make_server("::1", port, app, threaded=True)
        if ssl_ctx is not None:
            PolyglotHTTPAndHTTPSServer.wrap_wsgi_server_polyglot(srv_v6, ssl_ctx)
        t_v6 = threading.Thread(
            target=srv_v6.serve_forever,
            name=f"IPv6Loopback_{port}",
            daemon=True
        )
        t_v6.start()
        return srv_v6
    except Exception:
        return None


def start_plain_http_engine_listener(http_port):
    """
    Runs the full Flask `app` on plain `http://0.0.0.0:5000` (and IPv6 `[::1]:5000`)
    simultaneously alongside Port 8443!
    Why this fixes Windows, Linux, macOS, and Android Termux 100% of the time:
      - Modern browsers treat `http://127.0.0.1:5000` and `http://localhost:5000` as a
        natively trusted W3C Secure Context.
      - HTTPS sites like JanitorAI, Chub, SillyTavern, and VS Code extensions can call
        `http://127.0.0.1:5000/v1/chat/completions` or `http://localhost:5000/v1/chat/completions`
        directly without EVER hitting `NET::ERR_CERT_AUTHORITY_INVALID` or `Failed to fetch`!
    """
    try:
        srv = make_server("0.0.0.0", http_port, app, threaded=True)
        t = threading.Thread(target=srv.serve_forever, name="PlainHTTPEngineThread", daemon=True)
        t.start()
        v6_srv = _start_optional_ipv6_loopback_listener(http_port, ssl_ctx=None)
        with server_state.lock:
            server_state.ipv6_http_server = v6_srv
        return srv, t
    except OSError:
        return None, None


def configure_engine_networking(pool_connections=100, pool_maxsize=100):
    """
    Replaces `nvidia_rp_cleaner.py`'s default HTTP session with our high-concurrency,
    offline-safe `ResilientNvidiaSession` and attaches Dual-Stack HTTP/HTTPS + LAN middleware.
    """
    resilient_session = ResilientNvidiaSession(
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize
    )
    set_http_session(resilient_session)
    attach_server_middleware_and_routes()


def get_network_status(refresh=True):
    """
    Programmatic helper for `cli.py` to query LAN IP, OS platform, HTTP/HTTPS URLs,
    certificate trust status, and live NVIDIA server connectivity.
    """
    if refresh:
        check_nvidia_and_internet_connectivity(timeout=3.5)
    with server_state.lock:
        return {
            "is_running": server_state.is_running,
            "platform": server_state.platform_name,
            "https_port": server_state.https_port,
            "http_port": server_state.http_port,
            "lan_ip": server_state.lan_ip,
            "all_lan_ips": list(server_state.all_lan_ips),
            "localhost_http_endpoint": f"http://127.0.0.1:{server_state.http_port}/v1/chat/completions",
            "localhost_endpoint": f"https://localhost:{server_state.https_port}/v1/chat/completions",
            "lan_http_endpoint": f"http://{server_state.lan_ip}:{server_state.http_port}/v1/chat/completions",
            "lan_endpoint": f"https://{server_state.lan_ip}:{server_state.https_port}/v1/chat/completions",
            "cert_file": server_state.cert_path,
            "key_file": server_state.key_path,
            "cert_trusted": server_state.cert_trusted,
            "cert_trust_detail": server_state.cert_trust_detail,
            "internet_online": server_state.internet_online,
            "nvidia_reachable": server_state.nvidia_reachable,
            "last_error": server_state.last_net_error,
        }


def print_server_banner():
    """Prints a colorful diagnostic banner showing both No-Cert HTTP and Trusted HTTPS URLs."""
    c = TermColors
    with server_state.lock:
        https_port = server_state.https_port
        http_port = server_state.http_port
        lan_ip = server_state.lan_ip
        plat = server_state.platform_name
        net_ok = server_state.nvidia_reachable
        net_err = server_state.last_net_error
        trust_detail = server_state.cert_trust_detail

    print(f"{c.BOLD}{c.CYAN}" + "=" * 78 + f"{c.RESET}")
    print(f"{c.BOLD}{c.GREEN}🔒 NVIDIA NIM DUAL-STACK HTTP + HTTPS & LAN SERVER (server.py){c.RESET}")
    print(f"{c.CYAN}💻 Platform Detected  : {c.WHITE}{plat}{c.RESET}")
    print(f"{c.CYAN}🛡️  Cert Status        : {c.WHITE}{trust_detail}{c.RESET}")
    print(f"{c.CYAN}🏠 Localhost (No-Warn): {c.BOLD}{c.GREEN}http://127.0.0.1:{http_port}/v1/chat/completions{c.RESET}")
    print(f"{c.CYAN}🔐 Localhost (HTTPS)  : {c.BOLD}{c.GREEN}https://localhost:{https_port}/v1/chat/completions{c.RESET}")

    if lan_ip and lan_ip != "127.0.0.1":
        print(f"{c.CYAN}📡 Wi-Fi LAN (HTTPS)  : {c.BOLD}{c.GREEN}https://{lan_ip}:{https_port}/v1/chat/completions{c.RESET}")
        print(f"{c.CYAN}📡 Wi-Fi LAN (HTTP)   : {c.BOLD}{c.GREEN}http://{lan_ip}:{http_port}/v1/chat/completions{c.RESET}")
    else:
        print(
            f"{c.YELLOW}📡 Wi-Fi / LAN        : OFFLINE "
            f"(Using localhost:{http_port} & localhost:{https_port}){c.RESET}"
        )

    if net_ok:
        print(f"{c.CYAN}🌐 NVIDIA Upstream    : {c.BOLD}{c.GREEN}✅ ONLINE (integrate.api.nvidia.com reachable){c.RESET}")
    else:
        print(f"{c.CYAN}🌐 NVIDIA Upstream    : {c.BOLD}{c.RED}⚠️ OFFLINE / UNREACHABLE{c.RESET}")
        if net_err:
            print(f"{c.YELLOW}   ↳ Diagnostic       : {net_err}{c.RESET}")

    print(f"{c.MAGENTA}🤖 Active Model       : {c.BOLD}{engine.config['active_model']}{c.RESET}")
    print(f"{c.BOLD}{c.CYAN}" + "=" * 78 + f"{c.RESET}", flush=True)


def start_server(
    host="0.0.0.0",
    port=DEFAULT_HTTPS_PORT,
    cert_file=CERT_FILE,
    key_file=KEY_FILE,
    enable_http_redirect=True,
    http_redirect_port=DEFAULT_HTTP_PORT,
    background=False,
    use_flask_run=False,
):
    """
    Launches the Dual-Stack HTTP (Port 5000) + Polyglot HTTPS/HTTP (Port 8443) server:
      1. Auto-generates & installs `localhost.pem` into the OS Root Store where supported.
      2. Serves plain HTTP on Port 5000 (`http://localhost:5000/v1`) so browsers on
         Windows, Linux, macOS, and Android Termux NEVER show a certificate error.
      3. Serves HTTPS (and plain HTTP fallback) on Port 8443 (`https://localhost:8443/v1`
         and `https://<LAN_IP>:8443/v1`) for encrypted LAN and local connections.
    """
    with server_state.lock:
        if server_state.is_running:
            return get_network_status(refresh=False)

        server_state.platform_name = detect_platform_environment()
        server_state.https_port = int(port)
        server_state.http_port = int(http_redirect_port)
        server_state.http_redirect_port = int(http_redirect_port)
        server_state.bind_host = host

    # 1. Configure engine's HTTP session & attach middleware
    configure_engine_networking()

    # 2. Discover LAN IPs & check NVIDIA upstream connectivity
    check_nvidia_and_internet_connectivity(timeout=4.0)

    # 3. Ensure SSL certificates exist with LAN IP SANs + attempt OS Root Store auto-trust
    cert_path, key_path = ensure_ssl_certificates(
        cert_file=cert_file,
        key_file=key_file,
        lan_ips=server_state.all_lan_ips
    )
    with server_state.lock:
        server_state.cert_path = cert_path
        server_state.key_path = key_path

    # 4. Start full plain-HTTP Engine listener on Port 5000 (Zero Cert Warnings on all devices!)
    if http_redirect_port and http_redirect_port != port:
        http_srv, http_thread = start_plain_http_engine_listener(http_redirect_port)
        with server_state.lock:
            server_state.http_server = http_srv
            server_state.http_thread = http_thread

    # 5. Print status & diagnostics banner
    print_server_banner()

    # 6. Optional direct `app.run` fallback
    if use_flask_run and not background:
        with server_state.lock:
            server_state.is_running = True
        try:
            app.run(
                host=host,
                port=port,
                ssl_context=(cert_path, key_path),
                threaded=True,
                use_reloader=False
            )
        finally:
            with server_state.lock:
                server_state.is_running = False
        return get_network_status(refresh=False)

    # 7. Create Polyglot HTTPS + HTTP server on Port 8443
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

    wsgi_srv = make_server(host, port, app, threaded=True)
    PolyglotHTTPAndHTTPSServer.wrap_wsgi_server_polyglot(wsgi_srv, ssl_ctx)
    v6_https_srv = _start_optional_ipv6_loopback_listener(port, ssl_ctx=ssl_ctx)

    with server_state.lock:
        server_state.https_server = wsgi_srv
        server_state.ipv6_https_server = v6_https_srv
        server_state.is_running = True

    if background:
        t = threading.Thread(target=wsgi_srv.serve_forever, name="NVIDIANIMHTTPSServer", daemon=True)
        t.start()
        with server_state.lock:
            server_state.server_thread = t
        return get_network_status(refresh=False)
    else:
        try:
            wsgi_srv.serve_forever()
        except KeyboardInterrupt:
            stop_server()
        return get_network_status(refresh=False)


def stop_server():
    """Gracefully shuts down both the Port 8443 HTTPS server and Port 5000 HTTP server."""
    with server_state.lock:
        for srv_attr in ("https_server", "http_server", "ipv6_https_server", "ipv6_http_server"):
            srv_obj = getattr(server_state, srv_attr, None)
            if srv_obj:
                try:
                    srv_obj.shutdown()
                except Exception:
                    pass
                setattr(server_state, srv_attr, None)

        server_state.is_running = False
    return {"status": "stopped"}