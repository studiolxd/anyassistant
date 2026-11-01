"""The morning summary: «buenos días» (or when you stop the first alarm of the day, before 12),
without the LLM: the date, the weather (the plugin skill-weather, if it's there and knows your
city), today's all-day events, what's still on your calendar and how many unread emails
(the plugin «google»). Reading them takes a moment: it answers in the background.

    «Buenos días. Hoy es domingo, 1 de noviembre. Hoy: Día de Todos los Santos. Ahora en Málaga
    hace 18 grados, despejado… En la agenda tienes 2 cosas: a las 10 de la mañana, dentista, y a
    las 5 de la tarde, llamar a Ana. Tienes 3 emails sin leer.»

If you want to hear the emails, ask for them: the LLM reads them.
"""

import asyncio
import logging
import time

import events
import i18n
import kernel
import options
import settings
from options import Option
from plugins.skills_language import spoken_list
from skills import Skill, skill
from text import words

log = logging.getLogger("morning")
MORNING = (4, 12)  # the hours in which an alarm is the morning's

options.add(Option("morning_after_alarm", True, "the morning summary when you stop the first alarm of the day "
                   "(before 12)", "skills", "bool", live=True))
options.add(Option("unread_query", "is:unread in:inbox", "which emails the summary counts (a Gmail search)",
                   "skills", live=True))

_given = ""  # the day (YYYY-MM-DD) the summary was given after an alarm


def is_greeting(text: str) -> bool:
    """«Buenos días», «buenos días, Eva», «good morning»: a greeting on its own, not a sentence with it."""
    said = words(text)
    for greeting in i18n.L.list("morning.greetings"):
        wanted = greeting.split()
        if said[:len(wanted)] == wanted and len(said) <= len(wanted) + 2:
            return True
    return False


def _date(all_day: list, now: float) -> str:
    """«Hoy es domingo 1 de noviembre», with the all-day events («: Día de Todos los Santos»)."""
    date = i18n.L.date_spoken(time.localtime(now))
    if not all_day:
        return i18n.L("speech.morning_date", date=date)
    return i18n.L("speech.morning_date_with", date=date,
                  items=spoken_list([e.title or i18n.L("speech.morning_untitled") for e in all_day]))


def _agenda(timed: list) -> list[str]:
    parts = []
    items = [i18n.L("speech.morning_item", time=i18n.L.time_spoken(time.localtime(e.start)),
                    title=e.title or i18n.L("speech.morning_untitled")) for e in timed]
    if not items:
        parts.append(i18n.L("speech.morning_nothing"))
    elif len(items) == 1:
        parts.append(i18n.L("speech.morning_one", items=items[0]))
    else:
        parts.append(i18n.L("speech.morning_some", count=len(items), items=spoken_list(items)))
    return parts


def _emails(google) -> list[str]:
    found = google.unread(settings.get("unread_query") or "is:unread in:inbox")
    if found is None:
        return []
    count, more = found
    if more:
        return [i18n.L("speech.morning_more_emails", count=count)]
    if count == 0:
        return [i18n.L("speech.morning_no_email")]
    return [i18n.L("speech.morning_one_email") if count == 1 else i18n.L("speech.morning_emails", count=count)]


def summary(now: float | None = None) -> str:
    """The whole summary (it asks Google and Open-Meteo: a few seconds; call it in the background)."""
    now = now or time.time()
    google = kernel.module("google")
    found = google.today_left(now) if google else None
    all_day, timed = found if found is not None else ([], None)
    parts = [i18n.L("speech.morning_hello"), _date(all_day, now)]
    weather = kernel.module("skill-weather")
    if weather and settings.get("location"):
        parts.append(weather.answer(0))
    if timed is not None:
        parts += _agenda(timed)
    if google:
        parts += _emails(google)
    return " ".join(parts)


def give(assistant):
    """Says the summary on that device, when it's ready."""
    async def say():
        assistant.say(await asyncio.get_running_loop().run_in_executor(None, summary))

    assistant.later(say())


@skill
class Morning(Skill):
    order = 44

    def hear(self, text, assistant) -> bool:
        if not is_greeting(text):
            return False
        assistant.show_heard(text)
        give(assistant)
        return True


@events.on("alarm_stopped")
def _after_the_alarm(assistant, item):
    """The first alarm of the day you stop, in the morning: the summary right after."""
    global _given
    t = time.localtime()
    today = time.strftime("%Y-%m-%d", t)
    if (item.get("kind") != "alarm" or not settings.get("morning_after_alarm", True) or _given == today
            or not MORNING[0] <= t.tm_hour < MORNING[1]):
        return
    _given = today
    log.info("the morning alarm stopped: the summary")
    give(assistant)
