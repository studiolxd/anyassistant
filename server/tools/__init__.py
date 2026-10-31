"""Jarvis's own tools, for the LLM to manage itself (served over MCP by mcp_server.py).

Each tool is declared next to what it does, with @tool: its description, and
whether it needs the user's «yes». Its parameters (and their types) come from the
function's own:

    @tool("Forget a fact (its number from get_memory).", needs_yes=True)
    def forget(number: int) -> str: ...

Only what it may touch: its look, voice, name, language, memory, the camera on the
screen, its timers, which LLM it uses (among the installed ones), reloading its
tools and restarting. Never the permissions, the confirmation times, the port or
your instructions, so it cannot lift its own safeguards. Tools that change
something ask for your «yes» themselves (confirmation.py), so it holds for any LLM.
"""

import inspect
import json
import typing
from dataclasses import dataclass

import confirmation
import paths

session = lambda: None  # noqa: E731 — the connected device's Session; set by main.py
requested: set[str] = set()  # «reload», «restart»: for when the answer ends
ASK = ("This action changes data and needs the user's confirmation. Don't assume it: ask them in one "
       "short sentence whether to do it (say what you are going to do). If they answer yes, repeat "
       "exactly the same call; if not, don't do it.")


class ToolError(Exception):
    """A refusal or a wrong argument: its text goes back to the LLM."""


@dataclass
class Tool:
    function: typing.Callable
    description: str
    schema: dict
    needs_yes: bool


TOOLS: dict[str, Tool] = {}
NEEDS_YES: set[str] = set()
TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool(description: str, needs_yes: bool = False, name: str = "", choices: dict | None = None):
    """Declares a tool; its JSON schema comes from the function's parameters."""
    def register(function):
        properties, required = {}, []
        for parameter in inspect.signature(function).parameters.values():
            kind = parameter.annotation
            if typing.get_origin(kind) in (typing.Union, getattr(__import__("types"), "UnionType", None)):
                kind = next(a for a in typing.get_args(kind) if a is not type(None))
            properties[parameter.name] = {"type": TYPES.get(kind, "string")}
            if choices and parameter.name in choices:
                properties[parameter.name]["enum"] = choices[parameter.name]
            if parameter.default is inspect.Parameter.empty:
                required.append(parameter.name)
        called = name or function.__name__
        TOOLS[called] = Tool(function, description, {"type": "object", "properties": properties, "required": required},
                             needs_yes)
        if needs_yes:
            NEEDS_YES.add(called)
        return function
    return register


def confirmation_on() -> bool:
    try:
        permissions = json.loads(paths.PERMISSIONS.read_text())
    except (OSError, ValueError):
        permissions = {}
    return permissions.get("confirm", True) is not False


def confirmed(name: str, arguments: dict) -> bool:
    """Whether the user said «yes» to exactly this call (once); if not, it is left pending for them."""
    sign = confirmation.signature("jarvis", name, arguments)
    if confirmation.confirmed(sign):
        return True
    confirmation.ask(sign, f"jarvis: {name} {json.dumps(arguments, ensure_ascii=False)}")
    return False


def call(name: str, arguments: dict) -> str:
    if name not in TOOLS:
        raise ToolError(f"unknown tool {name}")
    if name in NEEDS_YES and confirmation_on() and not confirmed(name, arguments):
        raise ToolError(ASK)
    try:
        return TOOLS[name].function(**arguments)
    except TypeError as e:
        raise ToolError(f"wrong arguments: {e}") from None


# The modules that declare tools (each next to what it does).
import tools.system  # noqa: E402,F401
import memory  # noqa: E402,F401
import skins  # noqa: E402,F401
import skills  # noqa: E402

skills.load()
