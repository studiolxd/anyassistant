"""The plugin «https»: its own authority, a certificate for the Mac's names and addresses."""

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
