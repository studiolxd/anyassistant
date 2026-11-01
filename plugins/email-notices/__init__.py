"""Email notices: «Tienes un email nuevo de Ana.» when an email arrives, through the plugin
«notices» (not at night, not over anyone, a soft tone first, where it says).

Every «email_check_minutes» it looks at the unread emails that match «email_notice_query»
(by default the Primary tab's: not promotions or notifications) and tells the ones it hadn't
seen. What it already had when the server started isn't told (the morning summary counts
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

_seen: set[str] | None = None  # the ids already there (None: not looked yet)


def new(emails: list) -> list:
    """The ones not seen before (the first time, none: what was there when it started)."""
    global _seen
    if _seen is None:
        _seen = {e.id for e in emails}
        return []
    found = [e for e in emails if e.id not in _seen]
    _seen |= {e.id for e in found}
    return found


def sentence(emails: list) -> str:
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
                google = kernel.module("google")
                if kernel.enabled("email-notices") and google and time.time() - looked >= every:
                    looked = time.time()
                    query = settings.get("email_notice_query") or QUERY
                    found = await asyncio.get_running_loop().run_in_executor(None, google.unread_emails, query)
                    arrived = new(found) if found is not None else []
                    notices = kernel.module("notices")
                    if arrived and notices:
                        log.info("%d new email(s)", len(arrived))
                        await notices.tell(sentence(list(reversed(arrived))))  # in the order they came
            except Exception as e:
                log.warning("email: %r", e)
            await asyncio.sleep(20)

    app["email-notices"] = asyncio.ensure_future(loop())
