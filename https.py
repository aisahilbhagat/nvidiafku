"""
https.py — Zero-Dependency Cross-Platform HTTPS & Certificate Provisioning
==========================================================================
Provides resilient 2-Tier SSL/TLS certificate generation (Persistent Root CA +
SAN Leaf Certificate), OS & Browser Root Store auto-trust, and a Polyglot
HTTP/HTTPS single-port socket multiplexer across:
  - Windows 10 / 11 (PowerShell .NET Root Store + certutil thumbprint verification)
  - Linux (System CA store + Chrome/Brave/Firefox NSS databases across native/Snap/Flatpak)
  - macOS (Login & System Keychain with proper TouchID/GUI prompt timeout)
  - Android Termux (Deliberately skips OS root injection; uses self-signed + HTTP localhost)
"""

import os
import sys
import ssl
import glob
import socket
import shutil
import base64
import hashlib
import tempfile
import subprocess
from datetime import datetime, timezone, timedelta

DEFAULT_CA_CERT_FILE = os.environ.get("SERVER_CA_CERT_FILE", "nvidiafku-root-ca.pem")
DEFAULT_CA_KEY_FILE = os.environ.get("SERVER_CA_KEY_FILE", "nvidiafku-root-ca-key.pem")
DEFAULT_CERT_FILE = os.environ.get("SERVER_CERT_FILE", "localhost.pem")
DEFAULT_KEY_FILE = os.environ.get("SERVER_KEY_FILE", "localhost-key.pem")


def _get_cert_sha1_thumbprint(cert_path):
    """Computes the uppercase hex SHA-1 thumbprint of the first CERTIFICATE block in a PEM file."""
    if not cert_path or not os.path.exists(cert_path):
        return None
    try:
        with open(cert_path, "r", encoding="ascii", errors="ignore") as f:
            pem = f.read()
        start_marker = "-----BEGIN CERTIFICATE-----"
        end_marker = "-----END CERTIFICATE-----"
        s_idx = pem.find(start_marker)
        e_idx = pem.find(end_marker)
        if s_idx == -1 or e_idx == -1:
            return None
        b64_body = pem[s_idx + len(start_marker):e_idx].strip()
        der_bytes = base64.b64decode("".join(b64_body.split()))
        return hashlib.sha1(der_bytes).hexdigest().upper()
    except Exception:
        return None


def _find_all_nss_databases_linux():
    """
    Finds all Chrome/Chromium/Brave NSS databases (~/.pki/nssdb, Snap, Flatpak)
    and Mozilla Firefox profile NSS databases (~/.mozilla/firefox/*) on Linux.
    """
    home = os.path.expanduser("~")
    nss_dirs = []

    # 1. Standard & Snap/Flatpak Chromium/Chrome/Brave NSS DB locations
    candidate_pki_dirs = [
        os.path.join(home, ".pki", "nssdb"),
        os.path.join(home, "snap", "chromium", "current", ".pki", "nssdb"),
        os.path.join(home, "snap", "brave", "current", ".pki", "nssdb"),
        os.path.join(home, ".var", "app", "com.google.Chrome", "config", "pki", "nssdb"),
        os.path.join(home, ".var", "app", "com.brave.Browser", "config", "pki", "nssdb"),
        os.path.join(home, ".var", "app", "org.chromium.Chromium", "config", "pki", "nssdb"),
    ]
    for d in candidate_pki_dirs:
        parent = os.path.dirname(d)
        if os.path.isdir(d) or os.path.isdir(parent):
            nss_dirs.append(d)

    # 2. Firefox profile directories (native, Snap, Flatpak)
    ff_patterns = [
        os.path.join(home, ".mozilla", "firefox", "*.*"),
        os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox", "*.*"),
        os.path.join(home, ".var", "app", "org.mozilla.firefox", ".mozilla", "firefox", "*.*"),
    ]
    for pattern in ff_patterns:
        for prof_dir in glob.glob(pattern):
            if os.path.isdir(prof_dir) and (
                os.path.exists(os.path.join(prof_dir, "cert9.db"))
                or os.path.exists(os.path.join(prof_dir, "prefs.js"))
            ):
                nss_dirs.append(prof_dir)

    return list(dict.fromkeys(nss_dirs))


def auto_trust_certificate_cross_platform(ca_cert_path, platform_name):
    """
    Registers the Root CA (`nvidiafku-root-ca.pem`) in the local OS & Browser certificate stores
    across Windows, Linux, and macOS so Chrome, Edge, Brave, Firefox, and Safari trust
    `https://localhost:8443` and `https://<LAN_IP>:8443` without `NET::ERR_CERT_AUTHORITY_INVALID`.
    On Android Termux, intentionally skips OS Root injection by design.
    """
    if not ca_cert_path or not os.path.exists(ca_cert_path):
        return False, "No SSL certificate file (HTTP Localhost Mode Active)"

    # Android Termux: Intentionally skip root injection as Android blocks user store auto-injection
    if "Termux" in str(platform_name) or "Android" in str(platform_name):
        return False, "Skipped by choice on Android Termux (http://127.0.0.1:5000 & self-signed https://8443 active)"

    thumbprint = _get_cert_sha1_thumbprint(ca_cert_path)

    try:
        # =====================================================================
        # WINDOWS: Verify by exact SHA-1 Thumbprint & Inject via .NET Store / certutil
        # =====================================================================
        if platform_name == "Windows":
            ps_exe = shutil.which("powershell") or shutil.which("pwsh")

            # 1. Check if the exact SHA-1 thumbprint is already in CurrentUser\Root or LocalMachine\Root
            if ps_exe and thumbprint:
                check_ps = (
                    f"$c = Get-ChildItem -Path Cert:\\CurrentUser\\Root,Cert:\\LocalMachine\\Root "
                    f"-ErrorAction SilentlyContinue | Where-Object {{ $_.Thumbprint -eq '{thumbprint}' }}; "
                    f"if ($c) {{ exit 0 }} else {{ exit 1 }}"
                )
                chk = subprocess.run(
                    [ps_exe, "-NoProfile", "-NonInteractive", "-Command", check_ps],
                    capture_output=True,
                    timeout=8,
                )
                if chk.returncode == 0:
                    return True, f"Trusted in Windows Root Store (SHA1: {thumbprint[:10]}...)"

            # 2. Inject via PowerShell .NET X509Store (Cleanly removes stale NVIDIAFKU certs first)
            if ps_exe:
                escaped_path = ca_cert_path.replace("\\", "\\\\")
                inject_ps = f"""
$ErrorActionPreference = "Stop"
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2("{escaped_path}")
$store = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "CurrentUser")
$store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
# Remove older stale NVIDIAFKU Root CA certs with different thumbprints
foreach ($existing in $store.Certificates) {{
    if ($existing.Subject -like "*NVIDIAFKU Local Root CA*" -and $existing.Thumbprint -ne $cert.Thumbprint) {{
        try {{ $store.Remove($existing) }} catch {{}}
    }}
}}
if (-not ($store.Certificates | Where-Object {{ $_.Thumbprint -eq $cert.Thumbprint }})) {{
    $store.Add($cert)
}}
$store.Close()
"""
                # Allow 60 seconds in case Windows displays the CurrentUser Root CA confirmation dialog
                res = subprocess.run(
                    [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", inject_ps],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if res.returncode == 0:
                    return True, "Installed into Windows CurrentUser Root Store"

            # 3. Fallback to certutil with 60s timeout for user dialog confirmation
            add_proc = subprocess.run(
                ["certutil", "-user", "-addstore", "-f", "Root", ca_cert_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if add_proc.returncode == 0:
                return True, "Installed into Windows User Root Store via certutil"

            return False, "Windows Root Store prompt declined or skipped (http://127.0.0.1:5000 ready)"

        # =====================================================================
        # LINUX: Inject into Browser NSS DBs (Chrome/Brave/Firefox) + System CA Store
        # =====================================================================
        elif platform_name == "Linux":
            trusted_targets = []

            # 1. Inject into all NSS Databases (Chrome, Brave, Chromium, Firefox across native/Snap/Flatpak)
            certutil_bin = shutil.which("certutil")
            if certutil_bin:
                nss_dirs = _find_all_nss_databases_linux()
                if not nss_dirs:
                    default_nss = os.path.expanduser("~/.pki/nssdb")
                    os.makedirs(default_nss, exist_ok=True)
                    nss_dirs = [default_nss]

                for nss_dir in nss_dirs:
                    os.makedirs(nss_dir, exist_ok=True)
                    # Initialize NSS DB if cert9.db does not exist yet
                    if not os.path.exists(os.path.join(nss_dir, "cert9.db")):
                        subprocess.run(
                            [certutil_bin, "-d", f"sql:{nss_dir}", "-N", "--empty-password"],
                            capture_output=True,
                            timeout=5,
                        )
                    # Delete any stale entry with the same nickname before adding fresh CA
                    subprocess.run(
                        [certutil_bin, "-d", f"sql:{nss_dir}", "-D", "-n", "NVIDIAFKU Local Root CA"],
                        capture_output=True,
                        timeout=5,
                    )
                    res = subprocess.run(
                        [
                            certutil_bin,
                            "-d",
                            f"sql:{nss_dir}",
                            "-A",
                            "-t",
                            "CT,C,C",
                            "-n",
                            "NVIDIAFKU Local Root CA",
                            "-i",
                            ca_cert_path,
                        ],
                        capture_output=True,
                        timeout=8,
                    )
                    if res.returncode == 0:
                        trusted_targets.append(os.path.basename(os.path.dirname(nss_dir)) or "nssdb")

            # 2. Inject into Linux System-Wide Trust Store if running as root or passwordless sudo
            sys_trust_Commands = [
                # Debian / Ubuntu / Kali / Mint
                ("/usr/local/share/ca-certificates/nvidiafku-root-ca.crt", ["update-ca-certificates"]),
                # Arch / Manjaro
                ("/etc/ca-certificates/trust-source/anchors/nvidiafku-root-ca.crt", ["trust", "extract-compat"]),
                # Fedora / RHEL / CentOS / openSUSE
                ("/etc/pki/ca-trust/source/anchors/nvidiafku-root-ca.crt", ["update-ca-trust", "extract"]),
            ]
            is_root = hasattr(os, "geteuid") and os.geteuid() == 0
            sudo_non_interactive = False
            if not is_root and shutil.which("sudo"):
                sudo_chk = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=3)
                sudo_non_interactive = (sudo_chk.returncode == 0)

            for dest_cert, update_cmd in sys_trust_Commands:
                dest_dir = os.path.dirname(dest_cert)
                if os.path.isdir(dest_dir) and shutil.which(update_cmd[0]):
                    try:
                        if is_root:
                            shutil.copyfile(ca_cert_path, dest_cert)
                            os.chmod(dest_cert, 0o644)
                            up_res = subprocess.run(update_cmd, capture_output=True, timeout=15)
                            if up_res.returncode == 0:
                                trusted_targets.append("System-CA")
                                break
                        elif sudo_non_interactive:
                            subprocess.run(["sudo", "-n", "cp", ca_cert_path, dest_cert], capture_output=True, timeout=5)
                            subprocess.run(["sudo", "-n", "chmod", "644", dest_cert], capture_output=True, timeout=5)
                            up_res = subprocess.run(["sudo", "-n"] + update_cmd, capture_output=True, timeout=15)
                            if up_res.returncode == 0:
                                trusted_targets.append("System-CA")
                                break
                    except Exception:
                        pass

            if trusted_targets:
                return True, f"Trusted in Linux ({', '.join(dict.fromkeys(trusted_targets))})"
            if not certutil_bin:
                return False, "Missing 'certutil' (Install 'libnss3-tools' or 'nss' for Linux browser auto-trust)"
            return False, "Linux auto-trust skipped (http://127.0.0.1:5000 active)"

        # =====================================================================
        # MACOS: Verify with `security verify-cert` & Inject into Login Keychain
        # =====================================================================
        elif platform_name == "macOS":
            # 1. Check if already trusted by macOS Security Framework
            verify_res = subprocess.run(
                ["security", "verify-cert", "-c", ca_cert_path],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if verify_res.returncode == 0:
                return True, "Verified & Trusted in macOS Keychain"

            # 2. Resolve active user login keychain path dynamically
            login_kc = os.path.expanduser("~/Library/Keychains/login.keychain-db")
            if not os.path.exists(login_kc):
                alt_kc = os.path.expanduser("~/Library/Keychains/login.keychain")
                if os.path.exists(alt_kc):
                    login_kc = alt_kc

            if os.path.exists(login_kc):
                # Give the user up to 60 seconds to approve the macOS TouchID / Keychain password prompt
                res = subprocess.run(
                    [
                        "security",
                        "add-trusted-cert",
                        "-r",
                        "trustRoot",
                        "-p",
                        "ssl",
                        "-k",
                        login_kc,
                        ca_cert_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if res.returncode == 0:
                    return True, "Trusted in macOS Login Keychain"

            return False, "macOS Keychain prompt skipped or declined (http://127.0.0.1:5000 active)"

    except Exception as e:
        return False, f"Auto-trust skipped ({type(e).__name__})"

    return False, "Self-signed certificate active"


def _generate_2tier_via_cryptography(ca_cert_path, ca_key_path, cert_path, key_path, ips):
    """
    Generates a proper 2-Tier PKI hierarchy using `cryptography`:
      1. Persistent Root CA (`nvidiafku-root-ca.pem`) with `CA:TRUE`, `keyCertSign`, `cRLSign`
      2. Server Leaf Certificate (`localhost.pem`) signed by the Root CA with `CA:FALSE`,
         `serverAuth`, `digitalSignature`, `keyEncipherment`, and all SAN DNS/IPs.
    Writes the full certificate chain (Leaf + Root CA) to `cert_path` and Root CA to `ca_cert_path`.
    """
    try:
        import ipaddress
        from cryptography import x509
        from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        now_utc = datetime.now(timezone.utc)

        # 1. Load existing Root CA if valid, otherwise create a new persistent Root CA
        ca_key = None
        ca_cert = None
        if os.path.exists(ca_cert_path) and os.path.exists(ca_key_path):
            try:
                with open(ca_key_path, "rb") as kf:
                    ca_key = serialization.load_pem_private_key(kf.read(), password=None)
                with open(ca_cert_path, "rb") as cf:
                    ca_cert = x509.load_pem_x509_certificate(cf.read())
            except Exception:
                ca_key, ca_cert = None, None

        if ca_key is None or ca_cert is None:
            ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            ca_subject = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NVIDIAFKU Local Root CA"),
                x509.NameAttribute(NameOID.COMMON_NAME, "NVIDIAFKU Local Root CA"),
            ])
            ca_cert = (
                x509.CertificateBuilder()
                .subject_name(ca_subject)
                .issuer_name(ca_subject)
                .public_key(ca_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now_utc - timedelta(days=1))
                .not_valid_after(now_utc + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(
                    x509.KeyUsage(
                        digital_signature=True,
                        content_commitment=False,
                        key_encipherment=False,
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
                    x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                    critical=False,
                )
                .sign(ca_key, hashes.SHA256())
            )
            with open(ca_key_path, "wb") as kf:
                kf.write(
                    ca_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
            with open(ca_cert_path, "wb") as cf:
                cf.write(ca_cert.public_bytes(serialization.Encoding.PEM))

        # 2. Generate Server Leaf Key & Certificate signed by Root CA (CA:FALSE)
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf_subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NVIDIAFKU Local Server"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])

        san_entries = [
            x509.DNSName("localhost"),
            x509.DNSName("*.localhost"),
            x509.DNSName("*.local"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address("::1")),
        ]
        for ip_str in ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj not in [ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")]:
                    san_entries.append(x509.IPAddress(ip_obj))
            except Exception:
                pass

        leaf_cert = (
            x509.CertificateBuilder()
            .subject_name(leaf_subject)
            .issuer_name(ca_cert.subject)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now_utc - timedelta(days=1))
            .not_valid_after(now_utc + timedelta(days=397))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        with open(key_path, "wb") as kf:
            kf.write(
                leaf_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        # Write Leaf + Root CA chain into cert_path
        with open(cert_path, "wb") as cf:
            cf.write(leaf_cert.public_bytes(serialization.Encoding.PEM))
            cf.write(ca_cert.public_bytes(serialization.Encoding.PEM))

        return True
    except Exception:
        return False


def _generate_2tier_via_windows_powershell(ca_cert_path, ca_key_path, cert_path, key_path, ips):
    """
    Zero-dependency Windows 10/11 2-Tier Root CA + Signed Server Leaf generator!
    Uses built-in Windows .NET `System.Security.Cryptography` via PowerShell to:
      1. Create a Root CA (`CA:TRUE`) and export `nvidiafku-root-ca.pem`
      2. Sign a Server Leaf Certificate (`CA:FALSE`, `SAN=localhost, 127.0.0.1, ::1, LAN_IPs`)
      3. Export `localhost.pem` and `localhost-key.pem`
    """
    if os.name != "nt":
        return False

    ps_exe = shutil.which("powershell") or shutil.which("pwsh")
    if not ps_exe:
        return False

    ip_array_ps = ",".join([f'"{ip}"' for ip in (["127.0.0.1", "::1"] + list(ips or [])) if ip])
    ca_cert_esc = ca_cert_path.replace("\\", "\\\\")
    ca_key_esc = ca_key_path.replace("\\", "\\\\")
    cert_esc = cert_path.replace("\\", "\\\\")
    key_esc = key_path.replace("\\", "\\\\")

    ps_script = f"""
$ErrorActionPreference = "Stop"

# 1. Create Root CA (CA:TRUE)
$caRsa = [System.Security.Cryptography.RSA]::Create(2048)
$caReq = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
    "CN=NVIDIAFKU Local Root CA, O=NVIDIAFKU Local Root CA, C=US",
    $caRsa,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256,
    [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
)
$caReq.CertificateExtensions.Add(
    [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $true, 0, $true)
)
$caKeyUsage = [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign -bor `
              [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::CrlSign -bor `
              [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature
$caReq.CertificateExtensions.Add(
    [System.Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new($caKeyUsage, $true)
)
$caReq.CertificateExtensions.Add(
    [System.Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($caReq.PublicKey, $false)
)

$notBefore = [System.DateTimeOffset]::UtcNow.AddDays(-1)
$caNotAfter = [System.DateTimeOffset]::UtcNow.AddDays(3650)
$caCert = $caReq.CreateSelfSigned($notBefore, $caNotAfter)

$caCertBytes = $caCert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
$caCertB64 = [System.Convert]::ToBase64String($caCertBytes, [System.Base64FormattingOptions]::InsertLineBreaks)
$caCertPem = "-----BEGIN CERTIFICATE-----`r`n" + $caCertB64 + "`r`n-----END CERTIFICATE-----`r`n"
[System.IO.File]::WriteAllText("{ca_cert_esc}", $caCertPem, [System.Text.Encoding]::ASCII)

$caPrivBytes = $caRsa.ExportRSAPrivateKey()
$caPrivB64 = [System.Convert]::ToBase64String($caPrivBytes, [System.Base64FormattingOptions]::InsertLineBreaks)
$caPrivPem = "-----BEGIN RSA PRIVATE KEY-----`r`n" + $caPrivB64 + "`r`n-----END RSA PRIVATE KEY-----`r`n"
[System.IO.File]::WriteAllText("{ca_key_esc}", $caPrivPem, [System.Text.Encoding]::ASCII)

# 2. Create Server Leaf Certificate (CA:FALSE) signed by Root CA
$leafRsa = [System.Security.Cryptography.RSA]::Create(2048)
$leafReq = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
    "CN=localhost, O=NVIDIAFKU Local Server, C=US",
    $leafRsa,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256,
    [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
)
$leafReq.CertificateExtensions.Add(
    [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true)
)
$leafKeyUsage = [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor `
                [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment
$leafReq.CertificateExtensions.Add(
    [System.Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new($leafKeyUsage, $true)
)
$oidCollection = [System.Security.Cryptography.OidCollection]::new()
[void]$oidCollection.Add([System.Security.Cryptography.Oid]::new("1.3.6.1.5.5.7.3.1"))
[void]$oidCollection.Add([System.Security.Cryptography.Oid]::new("1.3.6.1.5.5.7.3.2"))
$leafReq.CertificateExtensions.Add(
    [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($oidCollection, $false)
)

$sanBuilder = [System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
$sanBuilder.AddDnsName("localhost")
$sanBuilder.AddDnsName("*.localhost")
$sanBuilder.AddDnsName("*.local")
$ipList = @({ip_array_ps})
foreach ($ipStr in $ipList) {{
    try {{
        $parsedIp = [System.Net.IPAddress]::Parse($ipStr)
        $sanBuilder.AddIpAddress($parsedIp)
    }} catch {{}}
}}
$leafReq.CertificateExtensions.Add($sanBuilder.Build())

$serialBytes = New-Object byte[] 16
[System.Security.Cryptography.RandomNumberGenerator]::Fill($serialBytes)
$serialBytes[0] = $serialBytes[0] -band 0x7F
$leafNotAfter = [System.DateTimeOffset]::UtcNow.AddDays(397)
$leafCert = $leafReq.Create($caCert, $notBefore, $leafNotAfter, $serialBytes)

$leafCertBytes = $leafCert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
$leafCertB64 = [System.Convert]::ToBase64String($leafCertBytes, [System.Base64FormattingOptions]::InsertLineBreaks)
$leafCertPem = "-----BEGIN CERTIFICATE-----`r`n" + $leafCertB64 + "`r`n-----END CERTIFICATE-----`r`n" + $caCertPem
[System.IO.File]::WriteAllText("{cert_esc}", $leafCertPem, [System.Text.Encoding]::ASCII)

$leafPrivBytes = $leafRsa.ExportRSAPrivateKey()
$leafPrivB64 = [System.Convert]::ToBase64String($leafPrivBytes, [System.Base64FormattingOptions]::InsertLineBreaks)
$leafPrivPem = "-----BEGIN RSA PRIVATE KEY-----`r`n" + $leafPrivB64 + "`r`n-----END RSA PRIVATE KEY-----`r`n"
[System.IO.File]::WriteAllText("{key_esc}", $leafPrivPem, [System.Text.Encoding]::ASCII)
"""
    try:
        res = subprocess.run(
            [ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if res.returncode == 0 and os.path.exists(cert_path) and os.path.exists(key_path):
            test_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            test_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            return True
    except Exception:
        pass
    return False


def _find_openssl_executable():
    """
    Finds `openssl` on PATH, inside Android Termux `$PREFIX/bin`, or inside common
    Windows Git / Conda / MSYS2 folders when standard PATH doesn't include it.
    """
    found = shutil.which("openssl") or shutil.which("openssl-tool")
    if found:
        return found

    termux_prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    for bin_name in ("openssl", "openssl-tool"):
        candidate = os.path.join(termux_prefix, "bin", bin_name)
        if os.path.exists(candidate):
            return candidate

    if os.name == "nt":
        common_win_paths = [
            r"C:\Program Files\Git\usr\bin\openssl.exe",
            r"C:\Program Files\Git\mingw64\bin\openssl.exe",
            r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
            r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\usr\bin\openssl.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\mingw64\bin\openssl.exe"),
        ]
        for candidate in common_win_paths:
            if os.path.exists(candidate):
                return candidate
    return None


def _generate_2tier_via_openssl(ca_cert_path, ca_key_path, cert_path, key_path, ips):
    """
    Generates a 2-Tier Root CA + Signed SAN Server Leaf Certificate via OpenSSL CLI
    using a temporary OpenSSL `.cnf` file so all versions of OpenSSL (1.1.1, 3.x, LibreSSL)
    properly embed `basicConstraints`, `keyUsage`, `extendedKeyUsage`, and `subjectAltName`.
    """
    openssl_bin = _find_openssl_executable()
    if not openssl_bin:
        return False

    try:
        # 1. Generate Root CA if not already present
        if not (os.path.exists(ca_cert_path) and os.path.exists(ca_key_path)):
            ca_cnf_content = (
                "[req]\n"
                "distinguished_name = req_dn\n"
                "x509_extensions = v3_ca\n"
                "prompt = no\n\n"
                "[req_dn]\n"
                "C = US\n"
                "O = NVIDIAFKU Local Root CA\n"
                "CN = NVIDIAFKU Local Root CA\n\n"
                "[v3_ca]\n"
                "basicConstraints = critical, CA:TRUE, pathlen:0\n"
                "keyUsage = critical, digitalSignature, keyCertSign, cRLSign\n"
                "subjectKeyIdentifier = hash\n"
            )
            with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as ca_cnf:
                ca_cnf.write(ca_cnf_content)
                ca_cnf_path = ca_cnf.name

            try:
                subprocess.run(
                    [
                        openssl_bin, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", ca_key_path,
                        "-out", ca_cert_path,
                        "-days", "3650",
                        "-sha256",
                        "-config", ca_cnf_path,
                        "-extensions", "v3_ca",
                    ],
                    capture_output=True,
                    timeout=15,
                    check=True,
                )
            finally:
                try:
                    os.remove(ca_cnf_path)
                except Exception:
                    pass

        # 2. Generate Server Leaf CSR & Sign with Root CA
        san_entries = ["DNS:localhost", "DNS:*.localhost", "DNS:*.local", "IP:127.0.0.1", "IP:::1"]
        for ip_str in ips:
            if ip_str and ip_str not in ("127.0.0.1", "::1"):
                san_entries.append(f"IP:{ip_str}")
        san_line = ", ".join(san_entries)

        leaf_cnf_content = (
            "[req]\n"
            "distinguished_name = req_dn\n"
            "prompt = no\n\n"
            "[req_dn]\n"
            "C = US\n"
            "O = NVIDIAFKU Local Server\n"
            "CN = localhost\n\n"
            "[v3_leaf]\n"
            "basicConstraints = critical, CA:FALSE\n"
            "keyUsage = critical, digitalSignature, keyEncipherment\n"
            "extendedKeyUsage = serverAuth, clientAuth\n"
            f"subjectAltName = {san_line}\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as leaf_cnf:
            leaf_cnf.write(leaf_cnf_content)
            leaf_cnf_path = leaf_cnf.name

        csr_path = leaf_cnf_path + ".csr"
        leaf_only_path = leaf_cnf_path + ".crt"
        try:
            subprocess.run(
                [
                    openssl_bin, "req", "-new", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key_path,
                    "-out", csr_path,
                    "-config", leaf_cnf_path,
                ],
                capture_output=True,
                timeout=15,
                check=True,
            )
            subprocess.run(
                [
                    openssl_bin, "x509", "-req",
                    "-in", csr_path,
                    "-CA", ca_cert_path,
                    "-CAkey", ca_key_path,
                    "-CAcreateserial",
                    "-out", leaf_only_path,
                    "-days", "397",
                    "-sha256",
                    "-extfile", leaf_cnf_path,
                    "-extensions", "v3_leaf",
                ],
                capture_output=True,
                timeout=15,
                check=True,
            )
            # Bundle Leaf + Root CA into cert_path
            with open(leaf_only_path, "rb") as lf, open(ca_cert_path, "rb") as caf, open(cert_path, "wb") as out_f:
                out_f.write(lf.read())
                out_f.write(caf.read())
        finally:
            for tmp_p in (leaf_cnf_path, csr_path, leaf_only_path, ca_cert_path + ".srl"):
                try:
                    if os.path.exists(tmp_p):
                        os.remove(tmp_p)
                except Exception:
                    pass

        return os.path.exists(cert_path) and os.path.exists(key_path)
    except Exception:
        return False


def _generate_pure_python_2tier(ca_cert_path, ca_key_path, cert_path, key_path, ips):
    """
    100% Pure-Python Standard Library 2-Tier X.509 v3 Root CA + Signed Server Leaf Generator!
    Works on Android Termux, Windows, Linux, and macOS with ZERO external packages or binaries.
    Includes full BasicConstraints, KeyUsage, ExtendedKeyUsage (serverAuth), and SAN extensions.
    """
    import random

    def _is_probable_prime(n, k=16):
        if n < 2:
            return False
        for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53):
            if n % p == 0:
                return n == p
        d = n - 1
        s = 0
        while d % 2 == 0:
            d //= 2
            s += 1
        rng = random.SystemRandom()
        for _ in range(k):
            a = rng.randrange(2, n - 1)
            x = pow(a, d, n)
            if x == 1 or x == n - 1:
                continue
            for _ in range(s - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                return False
        return True

    def _gen_prime(bits=1024):
        rng = random.SystemRandom()
        while True:
            cand = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
            if _is_probable_prime(cand):
                return cand

    def _der_len(length):
        if length < 0x80:
            return bytes([length])
        b = length.to_bytes((length.bit_length() + 7) // 8, "big")
        return bytes([0x80 | len(b)]) + b

    def _der_tlv(tag, content):
        return bytes([tag]) + _der_len(len(content)) + content

    def _der_int(n):
        if n == 0:
            return _der_tlv(0x02, b"\x00")
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        if b[0] & 0x80:
            b = b"\x00" + b
        return _der_tlv(0x02, b)

    def _der_seq(items):
        return _der_tlv(0x30, b"".join(items))

    def _der_set(items):
        return _der_tlv(0x31, b"".join(items))

    def _der_oid(oid_str):
        parts = [int(x) for x in oid_str.split(".")]
        out = bytearray([40 * parts[0] + parts[1]])
        for val in parts[2:]:
            if val == 0:
                out.append(0)
            else:
                buf = bytearray()
                while val > 0:
                    buf.insert(0, val & 0x7F)
                    val >>= 7
                for i in range(len(buf) - 1):
                    buf[i] |= 0x80
                out.extend(buf)
        return _der_tlv(0x06, bytes(out))

    def _der_utf8(s):
        return _der_tlv(0x0C, s.encode("utf-8"))

    def _der_utctime(dt):
        return _der_tlv(0x17, dt.strftime("%y%m%d%H%M%SZ").encode("ascii"))

    def _der_bitstring(b, unused_bits=0):
        return _der_tlv(0x03, bytes([unused_bits]) + b)

    def _der_octetstring(b):
        return _der_tlv(0x04, b)

    def _gen_rsa_keypair():
        e = 65537
        while True:
            p = _gen_prime(1024)
            q = _gen_prime(1024)
            if p != q and ((p - 1) % e != 0) and ((q - 1) % e != 0):
                n = p * q
                if n.bit_length() == 2048:
                    break
        phi = (p - 1) * (q - 1)
        d = pow(e, -1, phi)
        dp = d % (p - 1)
        dq = d % (q - 1)
        qinv = pow(q, -1, p)
        priv_der = _der_seq([
            _der_int(0), _der_int(n), _der_int(e), _der_int(d),
            _der_int(p), _der_int(q), _der_int(dp), _der_int(dq), _der_int(qinv),
        ])
        pub_der = _der_seq([_der_int(n), _der_int(e)])
        alg_rsa = _der_seq([_der_oid("1.2.840.113549.1.1.1"), _der_tlv(0x05, b"")])
        spki_der = _der_seq([alg_rsa, _der_bitstring(pub_der)])
        return n, d, priv_der, spki_der

    def _sign_tbs(tbs_bytes, signer_n, signer_d):
        alg_sha256_rsa = _der_seq([_der_oid("1.2.840.113549.1.1.11"), _der_tlv(0x05, b"")])
        digest = hashlib.sha256(tbs_bytes).digest()
        digest_info = b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20" + digest
        pad_len = 256 - len(digest_info) - 3
        em = b"\x00\x01" + (b"\xff" * pad_len) + b"\x00" + digest_info
        sig_int = pow(int.from_bytes(em, "big"), signer_d, signer_n)
        sig_bytes = sig_int.to_bytes(256, "big")
        return _der_seq([tbs_bytes, alg_sha256_rsa, _der_bitstring(sig_bytes)])

    def _to_pem(label, der_bytes):
        b64 = base64.encodebytes(der_bytes).decode("ascii").replace("\n", "")
        lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
        return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"

    try:
        alg_sha256_rsa = _der_seq([_der_oid("1.2.840.113549.1.1.11"), _der_tlv(0x05, b"")])
        now_utc = datetime.now(timezone.utc)

        # 1. Build Root CA (CA:TRUE)
        ca_n, ca_d, ca_priv_der, ca_spki_der = _gen_rsa_keypair()
        ca_name = _der_seq([
            _der_set([_der_seq([_der_oid("2.5.4.10"), _der_utf8("NVIDIAFKU Local Root CA")])]),
            _der_set([_der_seq([_der_oid("2.5.4.3"), _der_utf8("NVIDIAFKU Local Root CA")])]),
        ])
        ca_validity = _der_seq([
            _der_utctime(now_utc - timedelta(days=1)),
            _der_utctime(now_utc + timedelta(days=3650)),
        ])
        ext_ca_bc = _der_seq([
            _der_oid("2.5.29.19"),
            _der_tlv(0x01, b"\xff"),
            _der_octetstring(_der_seq([_der_tlv(0x01, b"\xff")])),
        ])
        # KeyUsage: digitalSignature (bit 0), keyCertSign (bit 5), cRLSign (bit 6) -> 0x86 with 1 unused bit
        ext_ca_ku = _der_seq([
            _der_oid("2.5.29.15"),
            _der_tlv(0x01, b"\xff"),
            _der_octetstring(_der_bitstring(b"\x86", unused_bits=1)),
        ])
        ca_exts = _der_tlv(0xA3, _der_seq([ext_ca_bc, ext_ca_ku]))
        ca_serial = random.SystemRandom().getrandbits(120) | 1
        ca_tbs = _der_seq([
            _der_tlv(0xA0, _der_int(2)),
            _der_int(ca_serial),
            alg_sha256_rsa,
            ca_name,
            ca_validity,
            ca_name,
            ca_spki_der,
            ca_exts,
        ])
        ca_cert_der = _sign_tbs(ca_tbs, ca_n, ca_d)

        # 2. Build Server Leaf Certificate (CA:FALSE) signed by Root CA
        leaf_n, leaf_d, leaf_priv_der, leaf_spki_der = _gen_rsa_keypair()
        leaf_name = _der_seq([
            _der_set([_der_seq([_der_oid("2.5.4.10"), _der_utf8("NVIDIAFKU Local Server")])]),
            _der_set([_der_seq([_der_oid("2.5.4.3"), _der_utf8("localhost")])]),
        ])
        leaf_validity = _der_seq([
            _der_utctime(now_utc - timedelta(days=1)),
            _der_utctime(now_utc + timedelta(days=397)),
        ])
        ext_leaf_bc = _der_seq([
            _der_oid("2.5.29.19"),
            _der_tlv(0x01, b"\xff"),
            _der_octetstring(_der_seq([])),  # CA:FALSE
        ])
        # KeyUsage: digitalSignature (bit 0) + keyEncipherment (bit 2) -> 0xA0 with 5 unused bits
        ext_leaf_ku = _der_seq([
            _der_oid("2.5.29.15"),
            _der_tlv(0x01, b"\xff"),
            _der_octetstring(_der_bitstring(b"\xa0", unused_bits=5)),
        ])
        # ExtendedKeyUsage: serverAuth (1.3.6.1.5.5.7.3.1), clientAuth (1.3.6.1.5.5.7.3.2)
        ext_leaf_eku = _der_seq([
            _der_oid("2.5.29.37"),
            _der_octetstring(_der_seq([
                _der_oid("1.3.6.1.5.5.7.3.1"),
                _der_oid("1.3.6.1.5.5.7.3.2"),
            ])),
        ])
        san_items = [
            _der_tlv(0x82, b"localhost"),
            _der_tlv(0x82, b"*.localhost"),
            _der_tlv(0x82, b"*.local"),
        ]
        for ip_str in ips:
            try:
                packed_ip = socket.inet_aton(ip_str)
                san_items.append(_der_tlv(0x87, packed_ip))
            except Exception:
                pass
        ext_leaf_san = _der_seq([
            _der_oid("2.5.29.17"),
            _der_octetstring(_der_seq(san_items)),
        ])
        leaf_exts = _der_tlv(0xA3, _der_seq([ext_leaf_bc, ext_leaf_ku, ext_leaf_eku, ext_leaf_san]))
        leaf_serial = random.SystemRandom().getrandbits(120) | 1
        leaf_tbs = _der_seq([
            _der_tlv(0xA0, _der_int(2)),
            _der_int(leaf_serial),
            alg_sha256_rsa,
            ca_name,
            leaf_validity,
            leaf_name,
            leaf_spki_der,
            leaf_exts,
        ])
        leaf_cert_der = _sign_tbs(leaf_tbs, ca_n, ca_d)

        ca_pem = _to_pem("CERTIFICATE", ca_cert_der)
        leaf_pem = _to_pem("CERTIFICATE", leaf_cert_der)

        with open(ca_key_path, "w", encoding="ascii") as kf:
            kf.write(_to_pem("RSA PRIVATE KEY", ca_priv_der))
        with open(ca_cert_path, "w", encoding="ascii") as cf:
            cf.write(ca_pem)

        with open(key_path, "w", encoding="ascii") as kf:
            kf.write(_to_pem("RSA PRIVATE KEY", leaf_priv_der))
        with open(cert_path, "w", encoding="ascii") as cf:
            cf.write(leaf_pem + ca_pem)

        test_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        test_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return True
    except Exception:
        return False


def ensure_ssl_certificates(cert_file=DEFAULT_CERT_FILE, key_file=DEFAULT_KEY_FILE, lan_ips=None, platform_name="Unknown"):
    """
    Universal, crash-proof 2-Tier SSL certificate orchestrator:
      1. Tries `mkcert` (if installed)
      2. Re-uses existing valid 2-Tier `nvidiafku-root-ca.pem` + `localhost.pem` & `localhost-key.pem`
      3. Tries `cryptography` 2-Tier Root CA + Leaf generator
      4. Tries native Windows PowerShell .NET 2-Tier Root CA + Leaf generator
      5. Tries `openssl` 2-Tier Root CA + Leaf generator
      6. Tries Pure-Python 2-Tier Root CA + Leaf generator
      7. Injects `nvidiafku-root-ca.pem` into the OS/Browser Root Store on Windows, Linux, and macOS.
    """
    cert_path = os.path.abspath(cert_file)
    key_path = os.path.abspath(key_file)
    cert_dir = os.path.dirname(cert_path)
    ca_cert_path = os.path.join(cert_dir, DEFAULT_CA_CERT_FILE)
    ca_key_path = os.path.join(cert_dir, DEFAULT_CA_KEY_FILE)

    ips = list(dict.fromkeys(["127.0.0.1"] + [ip for ip in (lan_ips or []) if ip]))

    # Strategy 0: mkcert
    if shutil.which("mkcert"):
        try:
            subprocess.run(["mkcert", "-install"], capture_output=True, timeout=30)
            mk_cmd = ["mkcert", "-cert-file", cert_path, "-key-file", key_path, "localhost", "127.0.0.1", "::1"] + [
                ip for ip in ips if ip != "127.0.0.1"
            ]
            res = subprocess.run(mk_cmd, capture_output=True, timeout=15)
            if res.returncode == 0 and os.path.exists(cert_path) and os.path.exists(key_path):
                # Copy mkcert's rootCA.pem to ca_cert_path if available so /cert.crt downloads the Root CA
                caroot_proc = subprocess.run(["mkcert", "-CAROOT"], capture_output=True, text=True, timeout=5)
                if caroot_proc.returncode == 0:
                    mk_root = os.path.join(caroot_proc.stdout.strip(), "rootCA.pem")
                    if os.path.exists(mk_root):
                        shutil.copyfile(mk_root, ca_cert_path)
                return cert_path, key_path, True, "Trusted via mkcert Root CA"
        except Exception:
            pass

    # Check if existing 2-Tier certificate pair (Root CA + Leaf Chain) exists and loads cleanly
    need_generate = True
    if os.path.exists(cert_path) and os.path.exists(key_path) and os.path.exists(ca_cert_path):
        try:
            with open(cert_path, "r", encoding="ascii", errors="ignore") as f:
                pem_text = f.read()
            # Ensure cert_path contains the 2-tier chain (Leaf + Root CA) and not an old single self-signed cert
            if pem_text.count("-----BEGIN CERTIFICATE-----") >= 2:
                test_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                test_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
                need_generate = False
        except Exception:
            need_generate = True

    if need_generate:
        generated_ok = (
            _generate_2tier_via_cryptography(ca_cert_path, ca_key_path, cert_path, key_path, ips)
            or _generate_2tier_via_windows_powershell(ca_cert_path, ca_key_path, cert_path, key_path, ips)
            or _generate_2tier_via_openssl(ca_cert_path, ca_key_path, cert_path, key_path, ips)
            or _generate_pure_python_2tier(ca_cert_path, ca_key_path, cert_path, key_path, ips)
        )
        if not generated_ok:
            return (
                None,
                None,
                False,
                "HTTPS unavailable (No SSL generator found — Running safely on HTTP Port 5000 & 8443)",
            )

    # Inject the Root CA (ca_cert_path) into the OS & Browser Trust Stores
    target_ca_to_trust = ca_cert_path if os.path.exists(ca_cert_path) else cert_path
    trusted_ok, trust_msg = auto_trust_certificate_cross_platform(target_ca_to_trust, platform_name)
    return cert_path, key_path, trusted_ok, trust_msg


def create_ssl_context(cert_path, key_path):
    """
    Safely constructs an `ssl.SSLContext` if `cert_path` and `key_path` exist and are valid.
    Returns `None` instead of crashing if certificates are unavailable.
    """
    if not cert_path or not key_path:
        return None
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return ctx
    except Exception:
        return None


class PolyglotHTTPAndHTTPSServer:
    """
    Smart Single-Port Multiplexer on Port 8443!
    Peeks at the first byte of every incoming connection on Port 8443:
      - If byte == 0x16 (TLS ClientHello) and `ssl_context` is available:
        Wraps the socket in SSL/TLS (`https://...:8443`).
      - If byte is plain ASCII ('G', 'P', 'O', etc.) or if SSL is unavailable:
        Passes the raw socket directly to Flask/Werkzeug so `http://localhost:8443`
        and `http://<LAN_IP>:8443` ALSO work natively without SSL errors!
    """
    @staticmethod
    def wrap_wsgi_server_polyglot(wsgi_server, ssl_context):
        if ssl_context is None:
            return wsgi_server

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
                        tls_sock = ssl_context.wrap_socket(client_sock, server_side=True)
                        return tls_sock, client_addr
                    else:
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