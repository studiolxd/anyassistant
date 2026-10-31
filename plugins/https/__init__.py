"""HTTPS on the local network, with a certificate authority of its own: the page becomes a
secure one (microphone, camera) in any browser, without Chrome's flag.

- Once, it makes its authority (https/ca.pem and its key, in your data folder: the key
  never leaves the Mac) and, with it, a certificate for anyassistant.local, the Mac's
  .local name, its addresses on the network and localhost. When an address changes,
  the certificate is made again (the authority stays: devices keep trusting it).
- Each device installs the authority once: http://<mac>:8080/https/ca.crt (the Mac app
  shows its QR). Then https://anyassistant.local:8443 (or the address) is secure.
- It serves the same server over HTTPS on «https_port», besides HTTP (which keeps working).
"""

import asyncio
import datetime
import ipaddress
import logging
import socket
import ssl

from aiohttp import web as http

import options
import paths
import settings
import web
from options import Option

log = logging.getLogger("https")
FOLDER = paths.HOME / "https"
CA, CA_KEY = FOLDER / "ca.pem", FOLDER / "ca-key.pem"
CERT, KEY = FOLDER / "server.pem", FOLDER / "server-key.pem"
NAME = "anyassistant.local"
DAYS = 397  # what browsers accept for a server certificate; made again before it ends

options.add(Option("https_port", 8443, "the HTTPS port (the page with a certificate devices trust)", "server",
                   "int"))


def addresses() -> list[str]:
    """The Mac's IPv4 addresses on the network (and 127.0.0.1)."""
    found = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:  # the one that reaches the network, even if the hostname doesn't resolve to it
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(found)


def local_name() -> str:
    """The Mac's Bonjour name (System Settings → Sharing: «MacBook-Air-de-Suvi.local»)."""
    import subprocess

    try:
        found = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=3)
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip() + ".local"
    except (OSError, subprocess.SubprocessError):
        pass
    return socket.gethostname().split(".")[0] + ".local"


def names() -> list[str]:
    return sorted({NAME, local_name(), "localhost"})


def _authority():
    """The authority: made once, kept (devices that installed it keep trusting it)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    if CA.exists() and CA_KEY.exists():
        key = serialization.load_pem_private_key(CA_KEY.read_bytes(), None)
        return x509.load_pem_x509_certificate(CA.read_bytes()), key
    FOLDER.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # RSA: old devices too
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"AnyAssistant on {socket.gethostname()}"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AnyAssistant")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    CA_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                         serialization.NoEncryption()))
    CA_KEY.chmod(0o600)
    CA.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("certificate authority made: %s", CA)
    return cert, key


def _current() -> bool:
    """Whether the server certificate covers today's names and addresses, and isn't ending."""
    from cryptography import x509

    if not (CERT.exists() and KEY.exists()):
        return False
    cert = x509.load_pem_x509_certificate(CERT.read_bytes())
    alt = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    covered = set(alt.get_values_for_type(x509.DNSName)) | {str(a) for a in alt.get_values_for_type(x509.IPAddress)}
    ending = cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc) < datetime.timedelta(days=30)
    return not ending and set(names()) | set(addresses()) <= covered


def certificate():
    """The server's certificate and key files, made (again) if needed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    if _current():
        return CERT, KEY
    authority, authority_key = _authority()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    alt = [x509.DNSName(n) for n in names()] + [x509.IPAddress(ipaddress.ip_address(a)) for a in addresses()]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)]))
            .issuer_name(authority.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=DAYS))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(authority_key.public_key()),
                           critical=False)
            .sign(authority_key, hashes.SHA256()))
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
    KEY.chmod(0o600)
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + CA.read_bytes())  # with its authority
    log.info("certificate for %s", ", ".join(names() + addresses()))
    return CERT, KEY


def port() -> int:
    return settings.get("https_port") or 8443


# --- The authority, for the devices (only the certificate: its key never leaves the Mac) ---

@web.route("GET", "/https/ca.crt")
async def _authority_file(request):
    """What a device installs once (Android: Settings → Security → Install a certificate → CA)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    certificate()
    der = x509.load_pem_x509_certificate(CA.read_bytes()).public_bytes(serialization.Encoding.DER)
    return http.Response(body=der, content_type="application/x-x509-ca-cert",
                         headers={"Content-Disposition": 'attachment; filename="AnyAssistant.crt"'})


@web.route("GET", "/https/info")
async def _info(request):
    """For the Mac app: where it is served, and where to get the authority."""
    return http.json_response({"port": port(), "names": names(), "addresses": addresses(),
                               "authority": "/https/ca.crt"})


# --- Serving the same server over HTTPS ---

@web.startup
async def serve(app):
    import kernel

    if not kernel.enabled("https"):
        return
    try:
        cert, key = await asyncio.get_running_loop().run_in_executor(None, certificate)
    except Exception as e:  # a certificate that can't be made mustn't stop the server
        log.warning("no HTTPS: %r", e)
        return
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert, key)
    # The same application as on HTTP (aiohttp's own way to make a server for it).
    handler = app._make_handler(loop=asyncio.get_running_loop(), access_log=logging.getLogger("aiohttp.access"))
    host = settings.get("host") or "0.0.0.0"
    try:
        server = await asyncio.get_running_loop().create_server(handler, host, port(), ssl=context)
    except OSError as e:
        log.warning("no HTTPS on port %s: %r", port(), e)
        return
    log.info("HTTPS on https://%s:%s", NAME, port())

    async def stop():
        server.close()
        await handler.shutdown(3)

    web.close_on_exit.append(stop)
