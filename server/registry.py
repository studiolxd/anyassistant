"""Registry of one kind of engine plugin (stt, wake, llm, tts, vad): who registered
which name, and whether its plugin is on (kernel.py).

    _registry = Registry("stt", "STT")
    register = _registry.register     # @register("parakeet") on the plugin's class
"""

import kernel


class Registry:
    def __init__(self, kind: str, label: str):
        self.kind = kind
        self.label = label
        self._plugins: dict[str, type] = {}

    def register(self, name: str):
        def decorator(cls):
            cls.name = name
            cls.plugin = kernel.current()
            self._plugins[name] = cls
            return cls

        return decorator

    def _discover(self):
        kernel.load_all(self.kind)

    def available(self) -> list[str]:
        self._discover()
        return sorted(n for n, c in self._plugins.items() if kernel.enabled(c.plugin))

    def get(self, name: str):
        """The plugin's class (to ask it things without creating one), or None."""
        self._discover()
        found = self._plugins.get(name)
        return found if found and kernel.enabled(found.plugin) else None

    def create(self, name: str, **options):
        found = self.get(name)
        if not found:
            raise ValueError(f"Unknown {self.label}: {name}. Available: {', '.join(self.available())}")
        return found(**options)
