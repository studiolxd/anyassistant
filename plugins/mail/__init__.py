"""Mail accounts that aren't Gmail (Gmail goes through bin/gog): IMAP to receive, SMTP to send.

    "mail_accounts": [{"name": "Trabajo", "address": "yo@dominio.com",
                       "imap": "imap.dominio.com:993", "smtp": "smtp.dominio.com:465"}]

Optional per account: "user" (when the login isn't the address), "folder" (INBOX). The
password is in the system's keychain (service «AnyAssistant mail», the address as account: the
macOS Keychain; Windows' Credential Manager or Linux's Secret Service, through keyring), never
in settings.json: `bin/anyassistant mail add yo@dominio.com` asks for it, guesses the servers
of the known providers, tries them and saves the account (plugins/mail/cli.py); the Mac app
does the same in its settings («Mail accounts», through /admin/mail, only from the Mac).

What it brings:
- unread(account): the unread emails (who, subject), without marking them read: for the
  plugin «email-notices» and the morning summary's count.
- Tools for the LLM: list_mail, read_mail (nothing is marked read), send_mail (with your «yes»).
"""

import email
import email.header
import email.policy
import email.utils
import html
import imaplib
import logging
import re
import smtplib
import ssl
import subprocess
import sys
from dataclasses import dataclass
from email.message import EmailMessage

from aiohttp import web as http

import options
import settings
import web
from options import Option
from tools import ToolError, tool

log = logging.getLogger("mail")
KEYCHAIN = "AnyAssistant mail"
TIMEOUT = 20

options.add(Option("mail_accounts", [], "mail accounts besides Gmail (IMAP and SMTP); add them with "
                   "`bin/anyassistant mail add you@domain.com` (the password goes to the Keychain)", "assistant",
                   "json", live=True))

# Servers of the known providers, by the address's domain: (imap, smtp).
KNOWN = {
    ("icloud.com", "me.com", "mac.com"): ("imap.mail.me.com:993", "smtp.mail.me.com:587"),
    ("outlook.com", "hotmail.com", "live.com", "outlook.es", "hotmail.es"): ("outlook.office365.com:993",
                                                                             "smtp.office365.com:587"),
    ("gmail.com", "googlemail.com"): ("imap.gmail.com:993", "smtp.gmail.com:465"),
    ("yahoo.com", "yahoo.es"): ("imap.mail.yahoo.com:993", "smtp.mail.yahoo.com:465"),
    ("gmx.com", "gmx.es", "gmx.net"): ("imap.gmx.com:993", "mail.gmx.com:587"),
    ("zoho.com", "zohomail.com"): ("imap.zoho.eu:993", "smtp.zoho.eu:465"),
}


@dataclass
class Mail:
    id: str  # «<account>:<uid>»
    sender: str
    subject: str
    date: str = ""


def guess(address: str) -> tuple[str, str]:
    """The IMAP and SMTP servers for an address: a known provider's, or imap./smtp. its domain."""
    domain = address.rsplit("@", 1)[-1].lower()
    for domains, servers in KNOWN.items():
        if domain in domains:
            return servers
    return f"imap.{domain}:993", f"smtp.{domain}:465"


def accounts() -> list[dict]:
    found = settings.get("mail_accounts") or []
    return [a for a in found if isinstance(a, dict) and a.get("address")]


def account(name: str = "") -> dict:
    """An account by its name or address; the first one if none is given."""
    found = accounts()
    if not found:
        raise ToolError("there are no mail accounts (bin/anyassistant mail add)")
    if not name:
        return found[0]
    wanted = name.strip().lower()
    for a in found:
        if wanted in (str(a.get("name", "")).lower(), a["address"].lower()):
            return a
    raise ToolError(f"no account «{name}»; there are: {', '.join(label(a) for a in found)}")


def label(a: dict) -> str:
    return a.get("name") or a["address"]


def _server(text: str, port: int) -> tuple[str, int]:
    host, _, given = text.partition(":")
    return host, int(given or port)


# --- The password, in the keychain ---

def password(address: str) -> str | None:
    if sys.platform != "darwin":
        import keyring

        return keyring.get_password(KEYCHAIN, address)
    done = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN, "-a", address, "-w"],
                          capture_output=True, text=True)
    return done.stdout.rstrip("\n") if done.returncode == 0 else None


def save_password(address: str, secret: str):
    if sys.platform != "darwin":
        import keyring

        return keyring.set_password(KEYCHAIN, address, secret)
    subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN, "-a", address, "-w", secret],
                   check=True, capture_output=True)


def forget_password(address: str):
    if sys.platform != "darwin":
        import keyring
        import keyring.errors

        try:
            keyring.delete_password(KEYCHAIN, address)
        except keyring.errors.PasswordDeleteError:
            pass
        return
    subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN, "-a", address], capture_output=True)


# --- IMAP: receiving ---

def _imap(a: dict, secret: str | None = None) -> imaplib.IMAP4:
    host, port = _server(a.get("imap") or guess(a["address"])[0], 993)
    secret = secret if secret is not None else password(a["address"])
    if not secret:
        raise ToolError(f"no password for {a['address']} in the Keychain (bin/anyassistant mail add)")
    box = (imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT) if port == 993
           else imaplib.IMAP4(host, port, timeout=TIMEOUT))
    if port != 993:
        box.starttls(ssl.create_default_context())
    box.login(a.get("user") or a["address"], secret)
    return box


def _decoded(value) -> str:
    return str(email.header.make_header(email.header.decode_header(value or ""))).strip()


def _sender(value: str) -> str:
    name, address = email.utils.parseaddr(_decoded(value))
    return name or address


def _messages(a: dict, criteria: str, most: int) -> list[Mail]:
    """The newest `most` that match (headers only, nothing marked read)."""
    box = _imap(a)
    try:
        box.select(a.get("folder") or "INBOX", readonly=True)
        _, data = box.uid("SEARCH", None, criteria)
        uids = (data[0] or b"").split()[-most:][::-1]
        found = []
        for uid in uids:
            _, parts = box.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
            headers = email.message_from_bytes(raw)
            found.append(Mail(f"{label(a)}:{uid.decode()}", _sender(headers.get("From")),
                              _decoded(headers.get("Subject")), headers.get("Date", "")))
        return found
    finally:
        try:
            box.logout()
        except Exception:
            pass


def unread(a: dict, most: int = 50) -> list[Mail] | None:
    """The unread ones (newest first); None if the account can't be read now."""
    try:
        return _messages(a, "UNSEEN", most)
    except Exception as e:
        log.warning("%s: %r", label(a), e)
        return None


def unread_count(a: dict) -> int | None:
    """How many unread (all of them, not only the newest)."""
    try:
        box = _imap(a)
        try:
            box.select(a.get("folder") or "INBOX", readonly=True)
            _, data = box.uid("SEARCH", None, "UNSEEN")
            return len((data[0] or b"").split())
        finally:
            box.logout()
    except Exception as e:
        log.warning("%s: %r", label(a), e)
        return None


def _text(message) -> str:
    """The readable text of an email: its plain part, or its HTML without tags."""
    plain = html_part = None
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        if part.get_content_type() == "text/plain" and plain is None:
            plain = part.get_content()
        elif part.get_content_type() == "text/html" and html_part is None:
            html_part = part.get_content()
    if plain:
        return plain.strip()
    text = re.sub(r"(?is)<(script|style).*?</\1>|<[^>]+>", " ", html_part or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def read(mail_id: str) -> str:
    name, _, uid = mail_id.rpartition(":")
    a = account(name)
    box = _imap(a)
    try:
        box.select(a.get("folder") or "INBOX", readonly=True)
        _, parts = box.uid("FETCH", uid, "(BODY.PEEK[])")
        raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
        if raw is None:
            raise ToolError(f"no email {mail_id}")
        message = email.message_from_bytes(raw, policy=email.policy.default)
        return (f"From: {message.get('From')}\nTo: {message.get('To')}\nDate: {message.get('Date')}\n"
                f"Subject: {message.get('Subject')}\n\n{_text(message)[:8000]}")
    finally:
        box.logout()


# --- SMTP: sending ---

def send(a: dict, to: str, subject: str, body: str, secret: str | None = None):
    host, port = _server(a.get("smtp") or guess(a["address"])[1], 465)
    secret = secret if secret is not None else password(a["address"])
    if not secret:
        raise ToolError(f"no password for {a['address']} in the Keychain (bin/anyassistant mail add)")
    message = EmailMessage()
    message["From"] = email.utils.formataddr((a.get("from_name") or "", a["address"]))
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid(domain=a["address"].rsplit("@", 1)[-1])
    message.set_content(body)
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=TIMEOUT)
    else:
        server = smtplib.SMTP(host, port, timeout=TIMEOUT)
        server.starttls(context=context)
    with server:
        server.login(a.get("user") or a["address"], secret)
        server.send_message(message)
    _keep_sent(a, message)


def _keep_sent(a: dict, message: EmailMessage):
    """A copy in its Sent folder (the one IMAP marks \\Sent), as a mail app does; if it can't, never mind."""
    try:
        box = _imap(a)
        try:
            _, folders = box.list()
            sent = next((f.decode() for f in folders or [] if b"\\Sent" in f), None)
            if sent:
                name = sent.rsplit(' "', 1)[-1].rstrip('"') if ' "' in sent else sent.split()[-1]
                box.append(f'"{name}"', "\\Seen", imaplib.Time2Internaldate(email.utils.localtime()),
                           message.as_bytes())
        finally:
            box.logout()
    except Exception as e:
        log.info("no copy in Sent (%s): %r", label(a), e)


# --- Adding, trying, removing (bin/anyassistant mail, the Mac app) ---

def new_account(address: str, name: str = "", imap: str = "", smtp: str = "", user: str = "") -> dict:
    """An account with the servers guessed where not given."""
    address = address.strip()
    guessed = guess(address)
    a = {"name": name.strip() or address.split("@")[-1].split(".")[0].capitalize(), "address": address,
         "imap": imap.strip() or guessed[0], "smtp": smtp.strip() or guessed[1]}
    if user.strip():
        a["user"] = user.strip()
    return a


def check(a: dict, secret: str) -> list[str]:
    """What fails with these servers and password (empty: IMAP and SMTP work)."""
    problems = []
    try:
        _imap(a, secret).logout()
    except Exception as e:
        problems.append(f"IMAP {a['imap']}: {e}")
    host, port = _server(a["smtp"], 465)
    try:
        context = ssl.create_default_context()
        server = (smtplib.SMTP_SSL(host, port, context=context, timeout=TIMEOUT) if port == 465
                  else smtplib.SMTP(host, port, timeout=TIMEOUT))
        with server:
            if port != 465:
                server.starttls(context=context)
            server.login(a.get("user") or a["address"], secret)
    except Exception as e:
        problems.append(f"SMTP {a['smtp']}: {e}")
    return problems


def keep(a: dict, secret: str):
    """Saves it (the password in the Keychain; the account, replacing one with its address)."""
    save_password(a["address"], secret)
    others = [x for x in accounts() if x["address"].lower() != a["address"].lower()]
    settings.save(mail_accounts=others + [a])
    settings.refresh()


def remove(a: dict):
    settings.save(mail_accounts=[x for x in accounts() if x["address"].lower() != a["address"].lower()])
    settings.refresh()
    forget_password(a["address"])


# --- The Mac's own accounts (System Settings → Internet Accounts) ---

MAC_ACCOUNTS = "~/Library/Accounts/Accounts4.sqlite"


def _archived(blob):
    """A value the Accounts database keeps archived (NSKeyedArchiver): the plain one."""
    import plistlib

    try:
        found = plistlib.loads(blob)
    except Exception:
        return None
    if isinstance(found, dict) and "$objects" in found:
        objects = found["$objects"]
        return objects[1] if len(objects) > 1 else None
    return found


def on_the_mac() -> list[dict] | None:
    """The Mac's IMAP accounts, with their servers (not their passwords: macOS keeps those to itself);
    None if it can't read them (AnyAssistant needs Full Disk Access)."""
    import os
    import sqlite3

    path = os.path.expanduser(MAC_ACCOUNTS)
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = db.execute("""SELECT a.Z_PK, t.ZIDENTIFIER, a.ZUSERNAME, a.ZACCOUNTDESCRIPTION, p.ZKEY, p.ZVALUE
                             FROM ZACCOUNT a JOIN ZACCOUNTTYPE t ON a.ZACCOUNTTYPE = t.Z_PK
                             LEFT JOIN ZACCOUNTPROPERTY p ON p.ZOWNER = a.Z_PK
                             WHERE t.ZIDENTIFIER IN ('com.apple.account.IMAP', 'com.apple.account.SMTP')""").fetchall()
        db.close()
    except Exception as e:
        log.info("the Mac's accounts can't be read: %r", e)
        return None
    found: dict = {}
    for pk, kind, user, description, key, value in rows:
        one = found.setdefault(pk, {"kind": kind.rsplit(".", 1)[-1], "user": user or "", "name": description or ""})
        if key in ("Hostname", "PortNumber", "IdentityEmailAddress"):
            one[key] = _archived(value)
    smtp = {a["user"].lower(): a for a in found.values() if a["kind"] == "SMTP" and a.get("Hostname")}
    accounts_ = []
    for a in found.values():
        if a["kind"] != "IMAP" or not a.get("Hostname") or not a["user"]:
            continue
        address = a.get("IdentityEmailAddress") or a["user"]
        address = address[0] if isinstance(address, list) and address else address
        if not isinstance(address, str) or "@" not in address:
            address = a["user"]
        sending = smtp.get(a["user"].lower())
        accounts_.append({
            "name": a["name"] if a["name"] and a["name"] != address else address,  # several on a domain: apart
            "address": address,
            "imap": f"{a['Hostname']}:{a.get('PortNumber') or 993}",
            "smtp": f"{sending['Hostname']}:{sending.get('PortNumber') or 465}" if sending else guess(address)[1],
            **({"user": a["user"]} if a["user"].lower() != address.lower() else {}),
        })
    return sorted(accounts_, key=lambda a: a["address"].lower())




def _shown(a: dict) -> dict:
    return {**a, "password": bool(password(a["address"]))}


@web.route("GET", "/admin/mail")
async def _list(request):
    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    if "guess" in request.query:  # the servers for an address, as you type it
        imap, smtp = guess(request.query["guess"])
        return http.json_response({"imap": imap, "smtp": smtp})
    if "mac" in request.query:  # the Mac's own accounts, to import (not those already here)
        import asyncio

        found = await asyncio.get_running_loop().run_in_executor(None, on_the_mac)
        if found is None:
            return http.json_response({"error": "full disk access"}, status=403)
        here = {a["address"].lower() for a in accounts()}
        return http.json_response({"accounts": [a for a in found if a["address"].lower() not in here]})
    return http.json_response({"accounts": [_shown(a) for a in accounts()]})


@web.route("POST", "/admin/mail")
async def _change(request):
    """{"add": {address, password, name?, imap?, smtp?, user?}} tries it and saves it;
    {"test": address}; {"remove": address}."""
    import asyncio

    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    data = await request.json()
    loop = asyncio.get_running_loop()
    try:
        if "add" in data:
            given = data["add"]
            if "@" not in str(given.get("address", "")) or not given.get("password"):
                return http.json_response({"error": "address and password"}, status=400)
            a = new_account(given["address"], given.get("name", ""), given.get("imap", ""), given.get("smtp", ""),
                            given.get("user", ""))
            problems = await loop.run_in_executor(None, check, a, given["password"])
            if problems:
                return http.json_response({"problems": problems}, status=400)
            keep(a, given["password"])
            log.info("account added: %s", label(a))
        elif "test" in data:
            a = account(data["test"])
            problems = await loop.run_in_executor(None, check, a, password(a["address"]) or "")
            return http.json_response({"problems": problems, "accounts": [_shown(x) for x in accounts()]})
        elif "remove" in data:
            remove(account(data["remove"]))
    except ToolError as e:
        return http.json_response({"error": str(e)}, status=400)
    return http.json_response({"accounts": [_shown(a) for a in accounts()]})


# --- For the LLM ---

ACCOUNT = " account_name: its name or address (list_mail_accounts); empty, the first one."


@tool("The mail accounts besides Gmail (Gmail is through bin/gog): name and address.")
def list_mail_accounts() -> str:
    found = accounts()
    return "; ".join(f"{label(a)} ({a['address']})" for a in found) if found else "no mail accounts"


@tool("The newest emails of a mail account that isn't Gmail (who, subject, date, id to read one); nothing is "
      "marked read." + ACCOUNT)
def list_mail(account_name: str = "", unread_only: bool = True, most: int = 10) -> str:
    a = account(account_name)
    found = _messages(a, "UNSEEN" if unread_only else "ALL", max(1, min(int(most), 30)))
    if not found:
        return "no unread emails" if unread_only else "no emails"
    return "\n".join(f"[{m.id}] {m.date} · {m.sender}: {m.subject}" for m in found)


@tool("One email of a mail account that isn't Gmail, by its id from list_mail (not marked read).")
def read_mail(mail_id: str) -> str:
    return read(mail_id)


@tool("Send an email from a mail account that isn't Gmail (SMTP); a copy goes to its Sent folder." + ACCOUNT,
      needs_yes=True)
def send_mail(to: str, subject: str, body: str, account_name: str = "") -> str:
    if "@" not in to:
        raise ToolError("«to» needs an email address")
    a = account(account_name)
    send(a, to, subject, body)
    return f"sent from {a['address']} to {to}"
