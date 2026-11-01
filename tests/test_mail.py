"""The plugin «mail»: accounts besides Gmail (IMAP to receive, SMTP to send), with fake servers."""

import email.utils
from email.message import EmailMessage

import pytest

import kernel
import settings

kernel.load_all()
mail = kernel.load("mail")
emails = kernel.load("email-notices")
morning = kernel.load("morning")

WORK = {"name": "Trabajo", "address": "yo@estudio.com", "imap": "imap.estudio.com:993", "smtp": "smtp.estudio.com:465"}


def message(uid, sender, subject, body="Hola", html=None):
    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = sender, subject, email.utils.formatdate()
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return uid, m.as_bytes()


class Box:
    """A fake IMAP server: its inbox, which ones are unread, what it was asked."""
    inbox = {}
    unseen = set()
    sent = []

    def __init__(self, *args, **kwargs):
        self.selected = None

    def login(self, user, secret):
        assert secret == "secreto"

    def select(self, folder, readonly=False):
        assert readonly  # never marks anything read
        self.selected = folder

    def uid(self, command, *args):
        if command == "SEARCH":
            uids = [u for u in sorted(Box.inbox) if args[-1] == "ALL" or u in Box.unseen]
            return "OK", [b" ".join(str(u).encode() for u in uids)]
        uid, what = int(args[0]), args[1]
        assert "PEEK" in what
        return "OK", [(b"1", Box.inbox[uid]), b")"]

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Sent) "/" "Sent Messages"']

    def append(self, folder, flags, date, raw):
        Box.sent.append((folder, raw))

    def logout(self):
        pass


class Smtp:
    out = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def login(self, user, secret):
        assert (user, secret) == ("yo@estudio.com", "secreto")

    def send_message(self, m):
        Smtp.out.append(m)


@pytest.fixture(autouse=True)
def servers(monkeypatch):
    monkeypatch.setattr(settings, "active", {"mail_accounts": [WORK]})
    monkeypatch.setattr(mail, "password", lambda address: "secreto")
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", Box)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", Smtp)
    Box.inbox = dict([message(1, "Banco <info@banco.es>", "Su extracto"),
                      message(2, "=?utf-8?q?Ana_Garc=C3=ADa?= <ana@x.com>", "=?utf-8?q?Cena_el_s=C3=A1bado?="),
                      message(3, "luis@x.com", "Fotos", html="<p>Mira <b>esto</b></p><script>x()</script>")])
    Box.unseen, Box.sent, Smtp.out = {2, 3}, [], []


def test_the_servers_of_known_providers():
    assert mail.guess("yo@icloud.com") == ("imap.mail.me.com:993", "smtp.mail.me.com:587")
    assert mail.guess("yo@estudio.com") == ("imap.estudio.com:993", "smtp.estudio.com:465")


def test_unread_without_marking_them_read():
    found = mail.unread(WORK)
    assert [(m.sender, m.subject) for m in found] == [("luis@x.com", "Fotos"), ("Ana García", "Cena el sábado")]
    assert mail.unread_count(WORK) == 2


def test_the_llm_lists_and_reads_them():
    listed = mail.list_mail()
    assert "[Trabajo:3]" in listed and "Ana García: Cena el sábado" in listed
    assert "Su extracto" in mail.list_mail(unread_only=False)
    read = mail.read_mail("Trabajo:2")
    assert "Subject: Cena el sábado" in read and read.endswith("Hola")


def test_an_html_email_is_read_as_text():
    m = email.message_from_bytes(Box.inbox[3], policy=email.policy.default)
    assert mail._text(m) == "Hola"  # the plain part first
    only_html = EmailMessage()
    only_html.set_content("<p>Mira <b>esto</b></p><script>x()</script>", subtype="html")
    assert mail._text(only_html) == "Mira esto"


def test_sending_needs_a_yes_and_keeps_a_copy():
    import tools

    assert tools.TOOLS["send_mail"].needs_yes and not tools.TOOLS["list_mail"].needs_yes
    assert mail.send_mail("ana@x.com", "Hola", "¿Cenamos?") == "sent from yo@estudio.com to ana@x.com"
    sent = Smtp.out[0]
    assert (sent["To"], sent["Subject"], sent["From"]) == ("ana@x.com", "Hola", "yo@estudio.com")
    assert Box.sent[0][0] == '"Sent Messages"'


def test_an_unknown_account():
    with pytest.raises(mail.ToolError):
        mail.list_mail("Casa")


def test_notices_of_every_account(monkeypatch, es):
    google = type("Google", (), {"unread_emails": lambda self, query: []})()
    monkeypatch.setattr(kernel, "module", lambda name: {"google": google, "mail": mail}.get(name))
    monkeypatch.setattr(emails, "_seen", {})
    found = emails.sources()
    assert [name for name, _ in found] == ["Gmail", "Trabajo"]
    work = dict(found)["Trabajo"]
    assert emails.new(work(), "Trabajo") == []  # there already
    Box.inbox.update([message(4, "Marta <m@x.com>", "Presupuesto")])
    Box.unseen.add(4)
    arrived = emails.new(work(), "Trabajo")
    assert emails.sentence(arrived, "Trabajo") == "En Trabajo: tienes un email nuevo de Marta."


def test_the_morning_count_adds_them(es):
    class Google:
        def unread(self, query):
            return 1, False

    assert morning._emails(Google(), mail) == ["Tienes 3 emails sin leer."]
    assert morning._emails(None, mail) == ["Tienes 2 emails sin leer."]


# --- The Mac's accounts, and the app's routes ---

def archived(value):
    import plistlib

    return plistlib.dumps({"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {},
                           "$objects": ["$null", value]}, fmt=plistlib.FMT_BINARY)


def test_importing_the_macs_accounts(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "Accounts4.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE ZACCOUNTTYPE (Z_PK INTEGER, ZIDENTIFIER TEXT);
        CREATE TABLE ZACCOUNT (Z_PK INTEGER, ZACCOUNTTYPE INTEGER, ZUSERNAME TEXT, ZACCOUNTDESCRIPTION TEXT);
        CREATE TABLE ZACCOUNTPROPERTY (ZOWNER INTEGER, ZKEY TEXT, ZVALUE BLOB);
        INSERT INTO ZACCOUNTTYPE VALUES (1, 'com.apple.account.IMAP'), (2, 'com.apple.account.SMTP'),
                                        (3, 'com.apple.account.Exchange');
        INSERT INTO ZACCOUNT VALUES (10, 1, 'hola@estudio.com', 'Estudio'), (11, 2, 'hola@estudio.com', ''),
                                    (12, 3, 'yo@hotmail.com', 'Hotmail');""")
    for owner, key, value in ((10, "Hostname", "mail.estudio.com"), (10, "PortNumber", 143),
                              (11, "Hostname", "smtp.estudio.com"), (11, "PortNumber", 587)):
        db.execute("INSERT INTO ZACCOUNTPROPERTY VALUES (?, ?, ?)", (owner, key, archived(value)))
    db.commit()
    monkeypatch.setattr(mail, "MAC_ACCOUNTS", str(path))
    assert mail.on_the_mac() == [{"name": "Estudio", "address": "hola@estudio.com",
                                  "imap": "mail.estudio.com:143", "smtp": "smtp.estudio.com:587"}]
    monkeypatch.setattr(mail, "MAC_ACCOUNTS", str(tmp_path / "none.sqlite"))
    assert mail.on_the_mac() is None  # can't be read: the app asks for Full Disk Access


def test_the_apps_routes(monkeypatch):
    import asyncio
    import json

    from aiohttp.test_utils import make_mocked_request

    saved = {}
    monkeypatch.setattr(mail, "save_password", lambda address, secret: saved.update({address: secret}))
    monkeypatch.setattr(mail, "forget_password", lambda address: saved.pop(address, None))
    monkeypatch.setattr(settings, "save", lambda **changes: settings.active.update(changes))
    monkeypatch.setattr(settings, "refresh", lambda: set())
    monkeypatch.setattr(mail, "check", lambda a, secret: [] if secret == "secreto" else ["IMAP: wrong password"])

    def post(body, remote="127.0.0.1"):
        request = make_mocked_request("POST", "/admin/mail", transport=type("T", (), {
            "get_extra_info": lambda self, k, d=None: (remote, 1) if k == "peername" else d})())
        request.json = lambda: asyncio.sleep(0, body)
        answer = asyncio.run(mail._change(request))
        return answer.status, json.loads(answer.body)

    status, answer = post({"add": {"address": "ana@casa.es", "password": "mal"}})
    assert status == 400 and answer["problems"] == ["IMAP: wrong password"] and not saved
    status, answer = post({"add": {"address": "ana@casa.es", "password": "secreto", "name": "Casa"}})
    assert status == 200 and saved == {"ana@casa.es": "secreto"}
    assert [a["name"] for a in answer["accounts"]] == ["Trabajo", "Casa"]
    assert "password" not in json.dumps(settings.active["mail_accounts"])  # never in settings.json
    assert post({"remove": "Casa"})[1]["accounts"][-1]["name"] == "Trabajo"
    assert post({"add": {}}, remote="192.168.1.5")[0] == 403  # only from the Mac
