"""Plugin registry shared by stt/, wake/, llm/, tts/ and any future plugin package.

Each plugin package creates its registry and exposes register/create/available.
Plugins are the package's modules; listing them imports them all, so heavy
dependencies must be imported inside the classes, not at module level.
"""

import importlib
import pkgutil


class Registry:
    def __init__(self, package: str, path, kind: str):
        self.package = package
        self.path = path
        self.kind = kind
        self._plugins: dict[str, type] = {}

    def register(self, name: str):
        def decorator(cls):
            cls.name = name
            self._plugins[name] = cls
            return cls

        return decorator

    def available(self) -> list[str]:
        self._discover()
        return sorted(self._plugins)

    def get(self, name: str):
        """The plugin's class (to ask it things without creating one), or None."""
        self._discover()
        return self._plugins.get(name)

    def create(self, name: str, **options):
        self._discover()
        if name not in self._plugins:
            raise ValueError(
                f"Unknown {self.kind}: {name}. Available: {', '.join(sorted(self._plugins))}"
            )
        return self._plugins[name](**options)

    def _discover(self):
        for module in pkgutil.iter_modules(self.path):
            importlib.import_module(f"{self.package}.{module.name}")
