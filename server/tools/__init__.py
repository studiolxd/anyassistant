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
something wait for your «yes» (the plugin «confirmation», through gate()), so it holds
for any LLM.
"""

import inspect
import typing
from dataclasses import dataclass

import hub
import kernel

session = hub.current  # the connected device's Session
requested: set[str] = set()  # «reload», «restart»: for when the answer ends
GATES = []  # (function, plugin): may refuse a call to a tool that changes something (confirmation…)


class ToolError(Exception):
    """A refusal or a wrong argument: its text goes back to the LLM."""


@dataclass
class Tool:
    function: typing.Callable
    description: str
    schema: dict
    needs_yes: bool
    plugin: str | None = None  # the plugin it belongs to: off, the tool isn't there


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
                             needs_yes, kernel.current())
        if needs_yes:
            NEEDS_YES.add(called)
        return function
    return register


def gate(function):
    """function(name, arguments) raises ToolError to refuse a needs_yes call (the plugin «confirmation»)."""
    plugin = kernel.current()
    GATES[:] = [g for g in GATES if (g[0].__qualname__, g[1]) != (function.__qualname__, plugin)] + [(function, plugin)]
    return function


def available() -> dict[str, Tool]:
    """The tools whose plugin is on (the plugins are loaded the first time, not on import:
    loading them while another module is half imported would break theirs)."""
    kernel.load_all()
    return {name: t for name, t in TOOLS.items() if kernel.enabled(t.plugin)}


def call(name: str, arguments: dict) -> str:
    if name not in available():
        raise ToolError(f"unknown tool {name}")
    if name in NEEDS_YES:
        for function, plugin in GATES:
            if kernel.enabled(plugin):
                function(name, arguments)
    try:
        return TOOLS[name].function(**arguments)
    except TypeError as e:
        raise ToolError(f"wrong arguments: {e}") from None


# The core's modules that declare tools (the plugins' load with them, in available()).
import skins  # noqa: E402,F401
