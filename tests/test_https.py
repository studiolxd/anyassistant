"""The plugin «https»: its own authority, a certificate for the Mac's names and addresses."""

import pytest

import kernel


def test_a_certificate_for_the_mac_signed_by_its_own_authority(tmp_path, monkeypatch):
    from cryptography import x509

    https = kernel.load("https")
    for name in ("FOLDER", "CA", "CA_KEY", "CERT", "KEY"):
        monkeypatch.setattr(https, name, tmp_path / getattr(https, name).name)
    monkeypatch.setattr(https, "addresses", lambda: ["127.0.0.1", "192.168.1.20"])
    cert, key = https.certificate()
    made = x509.load_pem_x509_certificate(cert.read_bytes())
    alt = made.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "anyassistant.local" in alt.get_values_for_type(x509.DNSName)
    assert "192.168.1.20" in {str(a) for a in alt.get_values_for_type(x509.IPAddress)}
    authority = https.CA.read_bytes()
    assert made.issuer == x509.load_pem_x509_certificate(authority).subject

    https.certificate()  # nothing changed: the same certificate
    assert x509.load_pem_x509_certificate(cert.read_bytes()).serial_number == made.serial_number
    monkeypatch.setattr(https, "addresses", lambda: ["127.0.0.1", "192.168.1.33"])  # another network
    https.certificate()
    assert x509.load_pem_x509_certificate(cert.read_bytes()).serial_number != made.serial_number
    assert https.CA.read_bytes() == authority  # the devices keep trusting it


def test_another_device_on_http_goes_to_the_https_page(monkeypatch):
    """With «https» on, the page on plain HTTP sends another device to HTTPS (where it may use the
    microphone); the Mac itself stays."""
    import asyncio

    import kernel
    from aiohttp import web as http
    from aiohttp.test_utils import make_mocked_request
    from plugins import page

    https = kernel.load("https")

    monkeypatch.setattr(kernel, "module", lambda name: https if name == "https" else None)
    monkeypatch.setattr(https, "port", lambda: 443)
    tablet = make_mocked_request("GET", "/?code=1", headers={"Host": "192.168.86.32:8080"},
                                 transport=type("T", (), {"get_extra_info": lambda self, k, d=None:
                                                          ("192.168.86.34", 5000) if k == "peername" else d})())
    with pytest.raises(http.HTTPFound) as moved:
        asyncio.run(page._index(tablet))
    assert moved.value.location == "https://192.168.86.32/?code=1"


def test_an_apps_view_of_its_theme_stays_on_http(monkeypatch):
    """The apps' web view of a theme (?app) isn't sent to HTTPS: the app has the microphone, and it
    opens the page at the address it already trusts."""
    import asyncio

    import kernel
    from aiohttp.test_utils import make_mocked_request
    from plugins import page

    https = kernel.load("https")

    monkeypatch.setattr(kernel, "module", lambda name: https if name == "https" else None)
    monkeypatch.setattr(https, "port", lambda: 443)
    phone = make_mocked_request("GET", "/?app&theme=orb", headers={"Host": "192.168.86.32:8080"},
                                transport=type("T", (), {"get_extra_info": lambda self, k, d=None:
                                                         ("192.168.86.34", 5000) if k == "peername" else d})())
    response = asyncio.run(page._index(phone))
    assert response.status == 200 and "/web/app.js" in response.text
