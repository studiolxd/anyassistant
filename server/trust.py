"""HTTPS checked by the system, not by Python's own copy of OpenSSL: models, plugins, the community's
catalog… On Windows Python's OpenSSL knows only the root certificates already in the store, and
Windows fetches the rest when one of its own programs needs them, so on a fresh Windows a download
failed with «CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate» (the server didn't
start: its voice is downloaded the first time). truststore (pip uses it too) asks the system, as a
browser does; with a company's or an antivirus's own certificate too. Once, at the start."""

import logging

log = logging.getLogger("trust")


def system_certificates():
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception as e:  # without it, Python's own: as before
        log.warning("HTTPS checked by Python's own certificates (%s)", e)
