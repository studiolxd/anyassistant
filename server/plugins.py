"""Registro de plugins compartido por stt/, despertar/ y los que vengan.

Cada paquete de plugins crea su registro y expone registrar/crear/disponibles.
Los plugins son módulos del paquete; al pedir la lista se importan todos, así
que las dependencias pesadas van dentro de las clases, no arriba del módulo.
"""

import importlib
import pkgutil


class Registro:
    def __init__(self, paquete: str, ruta, que: str):
        self.paquete = paquete
        self.ruta = ruta
        self.que = que
        self._plugins: dict[str, type] = {}

    def registrar(self, nombre: str):
        def decorador(clase):
            clase.nombre = nombre
            self._plugins[nombre] = clase
            return clase

        return decorador

    def disponibles(self) -> list[str]:
        self._descubrir()
        return sorted(self._plugins)

    def crear(self, nombre: str, **opciones):
        self._descubrir()
        if nombre not in self._plugins:
            raise ValueError(
                f"{self.que} desconocido: {nombre}. Hay: {', '.join(sorted(self._plugins))}"
            )
        return self._plugins[nombre](**opciones)

    def _descubrir(self):
        for modulo in pkgutil.iter_modules(self.ruta):
            importlib.import_module(f"{self.paquete}.{modulo.name}")
