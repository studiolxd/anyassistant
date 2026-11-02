"""HTTPS checked by the system (server/trust.py), and a voice that can't be got ready doesn't stop
the server (a fresh Windows failed to download Kokoro's model: «CERTIFICATE_VERIFY_FAILED», and the
server started again and again)."""

import ssl

import trust
import tts


def test_the_system_checks_https(monkeypatch):
    import truststore

    called = []
    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: called.append(True))
    trust.system_certificates()
    assert called


def test_without_truststore_it_goes_on(monkeypatch):
    import truststore

    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    trust.system_certificates()  # no exception: Python's own certificates, as before


def test_a_voice_that_cant_be_got_ready_doesnt_stop_the_server(caplog):
    class Failing(tts.Voice):
        def synthesize(self, text):
            raise ssl.SSLCertVerificationError("certificate verify failed")

    Failing().warm_up()  # no exception
    assert "isn't ready yet" in caplog.text
