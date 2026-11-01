"""bin/anyassistant mail: the mail accounts besides Gmail.

    bin/anyassistant mail add you@domain.com [--name Trabajo] [--imap host[:port]] [--smtp host[:port]] [--user login]
    bin/anyassistant mail list
    bin/anyassistant mail test [name]
    bin/anyassistant mail remove <name or address>

«add» asks for the password (it isn't shown), tries IMAP and SMTP with it, saves the account
in settings.json and the password in the macOS Keychain. For iCloud, Gmail, Outlook, Yahoo…
use an app password (the provider's account page), not your usual one.
"""

import argparse
import getpass
import os
import smtplib
import ssl
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "server"))

import kernel  # noqa: E402
import settings  # noqa: E402

kernel.load_all()
settings.active = {**settings.load()}
mail = kernel.load("mail")


def _save(found: list[dict]):
    settings.save(mail_accounts=found)


def _try(a: dict, secret: str) -> list[str]:
    """What fails with these servers and password (empty: everything works)."""
    problems = []
    try:
        box = mail._imap(a, secret)
        box.logout()
        print(f"  IMAP {a['imap']}: ok")
    except Exception as e:
        problems.append(f"IMAP {a['imap']}: {e}")
    host, port = mail._server(a["smtp"], 465)
    try:
        server = (smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=mail.TIMEOUT)
                  if port == 465 else smtplib.SMTP(host, port, timeout=mail.TIMEOUT))
        with server:
            if port != 465:
                server.starttls(context=ssl.create_default_context())
            server.login(a.get("user") or a["address"], secret)
        print(f"  SMTP {a['smtp']}: ok")
    except Exception as e:
        problems.append(f"SMTP {a['smtp']}: {e}")
    return problems


def add(args):
    imap, smtp = mail.guess(args.address)
    a = {"name": args.name or args.address.split("@")[1].split(".")[0].capitalize(), "address": args.address,
         "imap": args.imap or imap, "smtp": args.smtp or smtp}
    if args.user:
        a["user"] = args.user
    print(f"{a['address']}: IMAP {a['imap']}, SMTP {a['smtp']}")
    secret = getpass.getpass("Password (an app password if your provider has them): ")
    problems = _try(a, secret)
    if problems:
        print("It doesn't work:\n  " + "\n  ".join(problems))
        print("Check the password, or give the servers with --imap / --smtp.")
        sys.exit(1)
    mail.save_password(a["address"], secret)
    found = [x for x in mail.accounts() if x["address"].lower() != a["address"].lower()] + [a]
    _save(found)
    print(f"Saved «{a['name']}» (the password, in the Keychain). It applies at once.")


def listing(args):
    found = mail.accounts()
    if not found:
        print("No mail accounts. bin/anyassistant mail add you@domain.com")
    for a in found:
        key = "password in the Keychain" if mail.password(a["address"]) else "NO PASSWORD"
        print(f"{mail.label(a)}: {a['address']} · IMAP {a.get('imap')} · SMTP {a.get('smtp')} · {key}")


def test(args):
    for a in mail.accounts() if not args.name else [mail.account(args.name)]:
        print(mail.label(a))
        problems = _try(a, mail.password(a["address"]) or "")
        for problem in problems:
            print("  " + problem)


def remove(args):
    a = mail.account(args.name)
    _save([x for x in mail.accounts() if x is not a])
    mail.forget_password(a["address"])
    print(f"Removed «{mail.label(a)}» and its password.")


def main():
    parser = argparse.ArgumentParser(prog="bin/anyassistant mail", description="Mail accounts besides Gmail.")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("add", help="add (or change) an account")
    new.add_argument("address")
    new.add_argument("--name")
    new.add_argument("--imap", help="host[:port] (993: TLS)")
    new.add_argument("--smtp", help="host[:port] (465: TLS; 587: STARTTLS)")
    new.add_argument("--user", help="the login, if it isn't the address")
    new.set_defaults(run=add)
    commands.add_parser("list").set_defaults(run=listing)
    one = commands.add_parser("test")
    one.add_argument("name", nargs="?")
    one.set_defaults(run=test)
    gone = commands.add_parser("remove")
    gone.add_argument("name")
    gone.set_defaults(run=remove)
    args = parser.parse_args()
    try:
        args.run(args)
    except mail.ToolError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
