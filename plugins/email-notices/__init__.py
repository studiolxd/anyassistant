"""Email notices: «Tienes un email nuevo de Ana.» when an email arrives, through the plugin
«notices» (not at night, not over anyone, a soft tone first, where it says).

Every «email_check_minutes» it looks at the unread emails of Gmail (the plugin «google»: those
that match «email_notice_query», by default the Primary tab's: not promotions or notifications)
and of the other accounts (the plugin «mail»: their inbox), and tells the ones it hadn't seen;
with more than one account, it says which («En Trabajo: tienes un email nuevo de Ana.»). What it already had when the server started isn't told (the morning summary counts
them). «email_notice_says»: who it's from (sender, the default), its subject too (subject: it
may be private, in a shared house), or only how many (count). To hear them, ask: the LLM reads them.
"""

import asyncio
import logging
import time

import i18n
import kernel
import options
import settings
import web
from options import Option
from plugins.skills_language import spoken_list

log = logging.getLogger("email")
QUERY = "is:unread in:inbox category:primary"
MOST_NAMED = 3  # with more new ones at once, it only says how many

options.add(Option("email_notice_query", QUERY, "which emails it gives notice of (a Gmail search; by default the "
                   "Primary tab's unread ones)", "assistant", live=True))
options.add(Option("email_notice_says", "sender", "what it says of each new email", "assistant", "choice",
                   ["sender", "subject", "count"], live=True))
options.add(Option("email_check_minutes", 5, "every how many minutes it looks for new emails", "assistant", "int",
                   live=True))

_seen: dict[str, set[str]] = {}  # per account, the ids already there (not there: not looked yet)


def new(emails: list, account: str = "Gmail") -> list:
    """The ones not seen before (the first time, none: what was there when it started)."""
    if account not in _seen:
        _seen[account] = {e.id for e in emails}
        return []
    found = [e for e in emails if e.id not in _seen[account]]
    _seen[account] |= {e.id for e in found}
    return found


def sources() -> list[tuple]:
    """(account, function that reads its unread emails): Gmail, and each of the plugin «mail»'s."""
    found = []
    google = kernel.module("google")
    if google:
        query = settings.get("email_notice_query") or QUERY
        found.append(("Gmail", lambda: google.unread_emails(query)))
    mail = kernel.module("mail")
    for a in mail.accounts() if mail else []:
        found.append((mail.label(a), lambda a=a: mail.unread(a)))
    return found


def sentence(emails: list, account: str = "") -> str:
    """What it says; with `account`, which one («En Trabajo: tienes…»)."""
    said = _sentence(emails)
    if not account:
        return said
    return i18n.L("speech.email_account", account=account, sentence=said[:1].lower() + said[1:])


def _sentence(emails: list) -> str:
    says = settings.get("email_notice_says", "sender")
    if says == "count" or len(emails) > MOST_NAMED:
        return i18n.L("speech.email_one") if len(emails) == 1 else i18n.L("speech.email_some", count=len(emails))
    if len(emails) == 1:
        email = emails[0]
        if says == "subject":
            return i18n.L("speech.email_subject", sender=email.sender,
                          subject=email.subject or i18n.L("speech.email_untitled"))
        return i18n.L("speech.email_from", sender=email.sender)
    senders = list(dict.fromkeys(e.sender for e in emails))  # each once, in order
    return i18n.L("speech.email_from_some", count=len(emails), senders=spoken_list(senders))


@web.startup
async def watch(app):
    async def loop():
        looked = 0.0
        while True:
            try:
                every = max(1, settings.get("email_check_minutes") or 5) * 60
                if kernel.enabled("email-notices") and time.time() - looked >= every:
                    looked = time.time()
                    accounts = sources()
                    for account, read in accounts:
                        found = await asyncio.get_running_loop().run_in_executor(None, read)
                        arrived = new(found, account) if found is not None else []
                        notices = kernel.module("notices")
                        if arrived and notices:
                            log.info("%d new email(s) in %s", len(arrived), account)
                            which = account if len(accounts) > 1 else ""
                            await notices.tell(sentence(list(reversed(arrived)), which))  # in the order they came
            except Exception as e:
                log.warning("email: %r", e)
            await asyncio.sleep(20)

    app["email-notices"] = asyncio.ensure_future(loop())
