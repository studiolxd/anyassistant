"""Bonjour: the server announces itself on the local network as «_anyassistant._tcp», so
the apps (the Mac's, Android's, iPhone's) find it without an address to type, and an
address that changes (another network) doesn't matter.

    dns-sd -B _anyassistant._tcp          to see it from the Mac's terminal

The announcement carries the port, the assistant's name, whether pairing is on and the
HTTPS port if the plugin «https» is on (a TXT record: name=Jarvis pairing=1 https=443
version=1). It also gives the Mac the name anyassistant.local (for devices that resolve
.local names: not old Androids, which use the address). On the Mac, macOS's own dns-sd does
it while the server runs; on Windows and Linux, zeroconf (Python). Turn the plugin off and it
stops being announced.
"""

import asyncio
import logging
import socket
import sys

import kernel
import settings
import web

log = logging.getLogger("bonjour")
SERVICE = "_anyassistant._tcp"


def record() -> list[str]:
    """The TXT record: what an app wants to know before connecting."""
    found = [f"name={settings.get('name') or 'Jarvis'}", f"pairing={1 if kernel.enabled('pairing') else 0}",
             f"port={settings.get('port') or 8080}", f"computer={socket.gethostname().split('.')[0]}"]
    if kernel.enabled("https"):
        found.append(f"https={settings.get('https_port') or 443}")
    ip = address()
    if ip:  # its address now: an app that knew another one (the Mac's IP changed) finds it again
        found.append(f"address={ip}")
    return found + ["version=1"]


def address() -> str | None:
    """The Mac's address on the network, for anyassistant.local."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


CHECK = 60  # seconds between looks at its address (another network, a new IP from the router)


@web.startup
async def announce(app):
    """Announced while the server runs; again whenever its address changes (the old one is withdrawn)."""
    if not kernel.enabled("bonjour"):
        return
    state = {"stop": None, "ip": None}

    async def follow():
        while True:
            ip = address()
            if ip != state["ip"]:
                if state["stop"]:
                    await state["stop"]()
                    log.info("its address changed (%s → %s): announced again", state["ip"], ip)
                state["ip"] = ip
                state["stop"] = await _announce(ip)
            await asyncio.sleep(CHECK)

    task = asyncio.ensure_future(follow())

    async def stop():
        task.cancel()
        if state["stop"]:
            await state["stop"]()

    web.close_on_exit.append(stop)


async def _announce(ip: str | None):
    """Announces it at this address; what withdraws it (None if it couldn't)."""
    port = settings.get("port") or 8080
    instance = f"AnyAssistant on {socket.gethostname().split('.')[0]}"
    if sys.platform != "darwin":
        return await _zeroconf(instance, port, ip)
    try:
        # -P: the service and, with it, the name anyassistant.local → the Mac's address.
        command = (["dns-sd", "-P", instance, SERVICE, "local", str(port), "anyassistant.local", ip, *record()]
                   if ip else ["dns-sd", "-R", instance, SERVICE, "local", str(port), *record()])
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        log.info("announced on the network as «%s» (%s, port %s, %s)", instance, SERVICE, port, ip or "no address")
    except OSError as e:
        log.warning("couldn't announce it on the network: %r", e)
        return None

    async def stop():
        if process.returncode is None:
            process.terminate()
            await process.wait()

    return stop


async def _zeroconf(instance: str, port: int, ip: str | None):
    """Windows and Linux: the same announcement and name, from Python."""
    from zeroconf import IPVersion, ServiceInfo
    from zeroconf.asyncio import AsyncZeroconf

    if not ip:
        log.warning("couldn't announce it on the network: no network address")
        return None
    info = ServiceInfo(f"{SERVICE}.local.", f"{instance}.{SERVICE}.local.", port=port,
                       properties=dict(r.split("=", 1) for r in record()),
                       server="anyassistant.local.", addresses=[socket.inet_aton(ip)])
    zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
    try:
        await zeroconf.async_register_service(info)
        log.info("announced on the network as «%s» (%s, port %s, anyassistant.local → %s)", instance, SERVICE, port, ip)
    except Exception as e:  # another one with that name, no multicast…
        log.warning("couldn't announce it on the network: %r", e)
        await zeroconf.async_close()
        return None

    async def stop():
        await zeroconf.async_unregister_service(info)
        await zeroconf.async_close()

    return stop
