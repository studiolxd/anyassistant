"""Bonjour: the server announces itself on the local network as «_anyassistant._tcp», so
the apps (the Mac's, Android's, iPhone's) find it without an address to type, and an
address that changes (another Wi-Fi) doesn't matter.

    dns-sd -B _anyassistant._tcp          to see it from the Mac's terminal

The announcement carries the port, the assistant's name, whether pairing is on and the
HTTPS port if the plugin «https» is on (a TXT record: name=Jarvis pairing=1 https=8443
version=1). It also gives the Mac the name anyassistant.local (for devices that resolve
.local names: not old Androids, which use the address). macOS's own dns-sd does it while the
server runs; turn the plugin off and it stops being announced.
"""

import asyncio
import logging
import socket

import kernel
import settings
import web

log = logging.getLogger("bonjour")
SERVICE = "_anyassistant._tcp"
_process = None


def record() -> list[str]:
    """The TXT record: what an app wants to know before connecting."""
    found = [f"name={settings.get('name') or 'Jarvis'}", f"pairing={1 if kernel.enabled('pairing') else 0}"]
    if kernel.enabled("https"):
        found.append(f"https={settings.get('https_port') or 8443}")
    return found + ["version=1"]


def address() -> str | None:
    """The Mac's address on the network, for anyassistant.local."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


@web.startup
async def announce(app):
    global _process
    if not kernel.enabled("bonjour"):
        return
    port = settings.get("port") or 8080
    instance = f"AnyAssistant on {socket.gethostname().split('.')[0]}"
    try:
        ip = address()
        # -P: the service and, with it, the name anyassistant.local → the Mac's address.
        command = (["dns-sd", "-P", instance, SERVICE, "local", str(port), "anyassistant.local", ip, *record()]
                   if ip else ["dns-sd", "-R", instance, SERVICE, "local", str(port), *record()])
        _process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        log.info("announced on the network as «%s» (%s, port %s)", instance, SERVICE, port)
    except OSError as e:
        log.warning("couldn't announce it on the network: %r", e)

    async def stop():
        if _process and _process.returncode is None:
            _process.terminate()
            await _process.wait()

    web.close_on_exit.append(stop)
