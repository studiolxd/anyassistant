"""The language of controlling the computer by voice, shared by the plugins that do it on each
system (control-mac; Windows and Linux will come as their own plugins):

- matching.py: how a spoken name reaches a written one. The recognizer writes English names as
  they sound in Spanish («crom», «cromo» for Chrome; «fotochop»), so spellings are reduced to
  sounds before comparing; and the rankings of apps, shortcuts, files and windows, pure.
- commands.py: what a sentence asks for («abre Safari», «ejecuta el atajo Buenas noches», «abre la
  carpeta Descargas», «ve a la ventana de Mail», «teclea hola», «¿qué puedo decir?»), with the
  words of each language in its locales («control»); and what it says («speech»).

Nothing here touches the computer: the plugin of each system brings the actions.
"""

from . import commands, matching  # noqa: F401
