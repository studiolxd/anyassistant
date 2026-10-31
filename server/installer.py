"""The installer's steps: what `bin/jarvis setup` goes through, in the terminal or for
the app's window (the same steps; only how they are shown changes).

The core and the plugins declare them, next to what they are about:

    @installer.question("llm", "Which LLM answers", order=30, choices=lambda: […], default=lambda: "claude")
    def llm(value): settings.save(llm=value)          # what to do with the answer

    @installer.task("parakeet-model", "Speech recognition model", order=50)
    def download(progress): progress(0.5, "…")       # work, reporting how it goes

    @installer.device("my-voice", "Your voice", order=70)
    def enroll(progress): …                          # done on the device (the tablet, the app):
                                                     # the installer only shows how it goes

A step belongs to the plugin loading it: only those of the plugins that are wanted
(on, or about to be) run. Any step can be done again later: `bin/jarvis setup <id>`.

How it is shown:
- terminal (default): asks each question (Enter keeps the default) and shows progress;
- --defaults: no questions, every default («install with what comes»);
- --json: one JSON object per line ({"event": "step"|"progress"|"done"|"skipped"|"error"|
  "finished", …}) for a window to draw; answers come with --set key=value.
  `--list --json` describes the steps and their questions, for the window's forms.
"""

import json
import sys
import time
from dataclasses import dataclass
from typing import Callable

import kernel


@dataclass
class Step:
    id: str
    title: str
    order: int
    kind: str  # question, task, device
    function: Callable
    plugin: str | None
    help: str = ""
    choices: Callable | None = None  # question: the allowed answers (None: free text)
    default: Callable | None = None  # question: the answer if none is given
    when: Callable | None = None  # whether it applies now (None: always)
    always: bool = False  # shown even if its plugin is off (a question that turns it on)

    def describe(self) -> dict:
        found = {"id": self.id, "title": self.title, "kind": self.kind, "help": self.help,
                 "plugin": self.plugin, "order": self.order}
        if self.kind == "question":
            found["choices"] = _choices(self)
            found["default"] = self.default() if self.default else None
        return found


STEPS: dict[str, Step] = {}


def _register(kind, step_id, title, order, **more):
    def register(function):
        STEPS[step_id] = Step(step_id, title, order, kind, function, kernel.current(), **more)
        return function
    return register


def question(step_id: str, title: str, order: int, choices=None, default=None, help: str = "", when=None,
             always: bool = False):
    """always: shown even while its plugin is off (a question whose answer turns it on)."""
    return _register("question", step_id, title, order, choices=choices, default=default, help=help, when=when,
                     always=always)


def task(step_id: str, title: str, order: int, help: str = "", when=None):
    return _register("task", step_id, title, order, help=help, when=when)


def device(step_id: str, title: str, order: int, help: str = "", when=None):
    """Something done on the device (the tablet, the app): function(progress) waits for it."""
    return _register("device", step_id, title, order, help=help, when=when)


class Skip(Exception):
    """A step that doesn't apply after all (its text says why)."""


def _choices(step: Step):
    if step.choices is None:
        return None
    found = step.choices()
    return [{"value": c, "label": str(c)} if not isinstance(c, dict) else c for c in found]


def steps(only: list[str] | None = None) -> list[Step]:
    """The steps that apply, in order: the core's and those of the plugins that are wanted."""
    import install_steps  # noqa: F401 — the core's own steps

    kernel.load_all()
    chosen = [s for s in STEPS.values() if s.plugin is None or s.always or kernel.wanted(s.plugin)]
    if only:
        chosen = [s for s in chosen if s.id in only]
    return sorted(chosen, key=lambda s: (s.order, s.id))


# --- Showing them ---

class Terminal:
    def __init__(self, ask: bool):
        self.ask = ask

    def step(self, step, index, total):
        print(f"\n[{index}/{total}] {step.title}")
        if step.help:
            print(f"      {step.help}")

    def answer(self, step, given):
        default = given if given is not None else (step.default() if step.default else None)
        if not self.ask:
            return default
        options = _choices(step)
        if options:
            for i, option in enumerate(options, 1):
                mark = "*" if option["value"] == default else " "
                print(f"   {mark}{i}. {option['label']}")
            while True:
                said = input(f"      Choose (Enter: {default}): ").strip()
                if not said:
                    return default
                if said.isdigit() and 1 <= int(said) <= len(options):
                    return options[int(said) - 1]["value"]
                if said in [o["value"] for o in options]:
                    return said
                print("      That isn't one of them.")
        said = input(f"      (Enter: {default}): ").strip()
        return said or default

    def progress(self, step, fraction, text):
        bar = f"{round(fraction * 100):3d} %" if fraction is not None else "  …  "
        print(f"\r      {bar}  {text[:70]:70}", end="", flush=True)

    def done(self, step, text):
        print(f"\r      ✓ {(text or 'done')[:74]:74}")

    def skipped(self, step, text):
        print(f"      – {text}")

    def error(self, step, text):
        print(f"\r      ✗ {text}")

    def finished(self, failed):
        print("\nDone." if not failed else f"\nDone, with problems in: {', '.join(failed)}.")


class Lines:
    """--json: one event per line, for the app's window."""

    def _emit(self, **event):
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def step(self, step, index, total):
        self._emit(event="step", index=index, total=total, **step.describe())

    def answer(self, step, given):
        return given if given is not None else (step.default() if step.default else None)

    def progress(self, step, fraction, text):
        self._emit(event="progress", id=step.id, fraction=fraction, text=text)

    def done(self, step, text):
        self._emit(event="done", id=step.id, text=text)

    def skipped(self, step, text):
        self._emit(event="skipped", id=step.id, text=text)

    def error(self, step, text):
        self._emit(event="error", id=step.id, text=text)

    def finished(self, failed):
        self._emit(event="finished", failed=failed)


def run(view, answers: dict, only: list[str] | None = None) -> list[str]:
    """Goes through the steps; the ids of those that failed."""
    chosen = steps(only)
    failed = []
    for index, step in enumerate(chosen, 1):
        if step.plugin and not step.always and not kernel.wanted(step.plugin):
            continue  # turned off by an earlier answer
        if step.when and not step.when():
            continue
        view.step(step, index, len(chosen))
        last = [0.0]

        def progress(fraction=None, text=""):
            if time.time() - last[0] > 0.2 or fraction in (None, 1):
                last[0] = time.time()
                view.progress(step, fraction, text)

        try:
            if step.kind == "question":
                value = view.answer(step, answers.get(step.id))
                options = _choices(step)
                if options and value not in [o["value"] for o in options]:
                    raise ValueError(f"«{value}» isn't one of {', '.join(str(o['value']) for o in options)}")
                result = step.function(value)
            else:
                result = step.function(progress)
            view.done(step, result if isinstance(result, str) else "")
        except Skip as e:
            view.skipped(step, str(e))
        except Exception as e:  # one step failing doesn't stop the rest
            failed.append(step.id)
            view.error(step, f"{e}")
    view.finished(failed)
    return failed


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    answers, only, i = {}, [], 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--set" and i + 1 < len(argv):
            key, _, value = argv[i + 1].partition("=")
            answers[key] = {"true": True, "false": False}.get(value, value)
            i += 2
            continue
        if not arg.startswith("--"):
            only.append(arg)
        i += 1
    if "--list" in argv:
        found = [s.describe() for s in steps(only or None)]
        print(json.dumps(found, ensure_ascii=False, indent=None if as_json else 2))
        return 0
    view = Lines() if as_json else Terminal(ask="--defaults" not in argv and sys.stdin.isatty())
    return 1 if run(view, answers, only or None) else 0
