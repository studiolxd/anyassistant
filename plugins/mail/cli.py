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
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "server"))

import kernel  # noqa: E402
import settings  # noqa: E402

kernel.load_all()
settings.active = {**settings.load()}
mail = kernel.load("mail")


def add(args):
    a = mail.new_account(args.address, args.name or "", args.imap or "", args.smtp or "", args.user or "")
    print(f"{a['address']}: IMAP {a['imap']}, SMTP {a['smtp']}")
    secret = getpass.getpass("Password (an app password if your provider has them): ")
    problems = mail.check(a, secret)
    if problems:
        print("It doesn't work:\n  " + "\n  ".join(problems))
        print("Check the password, or give the servers with --imap / --smtp.")
        sys.exit(1)
    mail.keep(a, secret)
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
        problems = mail.check(a, mail.password(a["address"]) or "")
        for problem in problems or ["IMAP and SMTP: ok"]:
            print("  " + problem)


def remove(args):
    a = mail.account(args.name)
    mail.remove(a)
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
