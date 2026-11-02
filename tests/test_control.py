"""Controlling the computer by voice: how a spoken name reaches a written one (the plugin
control-language), which sentences are commands, and what the Mac's plugin does with them
(the Mac itself replaced by fakes)."""

import asyncio
import json
from pathlib import Path

import pytest

import i18n
import kernel
import paths
import skills
import tools
from plugins.control_language import commands, matching
from plugins.control_language.matching import Found, Window
import plugins.control_mac as control
from plugins.control_mac.macos import App

confirmation = kernel.load("confirmation")


# --- Sounds ---

@pytest.mark.parametrize("group", [
    ["chrome", "crome", "cromo", "croma", "crom", "kromo"],
    ["safari", "safary", "zafari", "safarí"],
    ["espotifai", "spotifai", "espotifay"],
    ["photoshop", "fotochop"],
    ["guasap", "uasap", "wasap"],
    ["bale", "vale"],
    ["word", "guord"],
    ["quiero", "kiero"],
])
def test_one_sound_survives_many_spellings(group):
    assert {matching.phonetic(spelling) for spelling in group} == {matching.phonetic(group[0])}


@pytest.mark.parametrize("a, b", [
    ("gmail", "mail"), ("mallorca", "orca"), ("minuto", "minion"), ("safari", "terminal"), ("chrome", "cromwell"),
    ("copiar", "cortar"), ("ventana", "pestana"), ("marca", "marcadores"),
])
def test_different_words_keep_different_sounds(a, b):
    assert matching.phonetic(a) != matching.phonetic(b)


def test_the_sounds_spanish_really_merges():
    assert matching.phonetic("vaca") == "bak"
    assert matching.phonetic("queso") == "kes"
    assert matching.phonetic("zapato") == "sapat"
    assert matching.phonetic("hola") == "ola"
    assert matching.phonetic("perro") == "per"
    assert matching.phonetic("chrome") == "krom"
    assert matching.phonetic("no") == "no"  # a short word keeps its vowel
    assert matching.phonetic("google") == matching.phonetic("gugle") and matching.phonetic("tweet") == matching.phonetic("tuit")
    assert matching.normalise("¡Abre Chrome 2!") == "abre chrome 2"


def test_a_spoken_word_reaches_a_written_one():
    assert matching.reaches("safari", "safari")
    assert matching.reaches("safaris", "safari")  # one slip in a long word
    assert matching.reaches("calcul", "calculator")  # a prefix long enough (more than half of it)
    assert not matching.reaches("calc", "calculator")
    assert matching.reaches("cromo", "chrome")  # the same sounds
    assert not matching.reaches("gmail", "mail")
    assert not matching.reaches("pon", "ponme")
    assert not matching.reaches("marca", "marcadores")


# --- Apps ---

APPS = [App("Google Chrome", "Google Chrome", "/Applications/Google Chrome.app"),
        App("Safari", "Safari", "/Applications/Safari.app"),
        App("Mail", "Mail", "/System/Applications/Mail.app"),
        App("System Settings", "Ajustes del Sistema", "/System/Applications/System Settings.app"),
        App("Visual Studio Code", "Visual Studio Code", "/Applications/Visual Studio Code.app"),
        App("Notes", "Notas", "/System/Applications/Notes.app"),
        App("Chrome Remote Desktop Host", "Chrome Remote Desktop Host", "/Applications/Chrome Remote Desktop Host.app")]


def names(app: App) -> list[str]:
    return [app.name, app.display]


@pytest.mark.parametrize("spoken, expected", [
    ("chrome", "Google Chrome"), ("crom", "Google Chrome"), ("google chrome", "Google Chrome"), ("gugle cromo", "Google Chrome"),
    ("safari", "Safari"), ("zafari", "Safari"), ("ajustes", "System Settings"), ("ajustes del sistema", "System Settings"),
    ("visual studio", "Visual Studio Code"), ("visual estudio code", "Visual Studio Code"), ("notas", "Notes"),
    ("gmail", None), ("puerta", None), ("code", None), ("la", None), ("remote desktop", "Chrome Remote Desktop Host"),
])
def test_an_app_answers_to_how_its_name_sounds(spoken, expected):
    found = matching.rank(spoken.split(), [(a, names(a)) for a in APPS])
    assert (found[0].item.name if found else None) == expected


def test_the_whole_name_beats_a_part_of_it():
    found = matching.rank(["chrome"], [(a, names(a)) for a in APPS])
    assert [m.item.name for m in found] == ["Google Chrome"]  # not a quarter of «Chrome Remote Desktop Host»
    found = matching.rank(["chrome", "remote", "desktop", "host"], [(a, names(a)) for a in APPS])
    assert found[0].item.name == "Chrome Remote Desktop Host"


# --- Shortcuts, files, windows ---

def test_a_shortcut_by_its_whole_name_word_for_word():
    installed = ["Modo Trabajo", "Buenas Noches", "Comprobar las reuniones restantes"]
    assert matching.rank_shortcuts(["modo", "trabajo"], installed)[0] == "Modo Trabajo"
    assert matching.rank_shortcuts(["modo", "trabaho"], installed)[0] == "Modo Trabajo"  # one slip
    assert matching.rank_shortcuts(["buenas", "noches"], installed)[0] == "Buenas Noches"
    assert matching.rank_shortcuts(["modo", "cocina"], installed) == []
    assert matching.rank_shortcuts(["modo"], installed) == []  # «Modo» isn't inside «Modo Trabajo»
    assert matching.rank_shortcuts(["comprobar", "reuniones"], installed) == ["Comprobar las reuniones restantes"]
    assert matching.rank_shortcuts(["modo", "trabajo"], []) == []


def test_files_are_ranked_by_name_kind_and_depth():
    found = [Found("/Users/ana/Documentos/proyectos/Dev", True), Found("/Users/ana/Dev", True),
             Found("/Users/ana/dev.txt", False), Found("/Users/ana/Library/Caches/dev", True),
             Found("/Users/ana/proyecto/node_modules/dev", True), Found("/Users/ana/Cosa.app/Contents/dev", True),
             Found("/Users/ana/Library/CloudStorage/Dropbox/Dev", True), Found("/Users/ana/otra cosa", True)]
    ranked = matching.rank_files("dev", True, found)
    assert [f.path for f in ranked] == ["/Users/ana/Dev", "/Users/ana/Documentos/proyectos/Dev",
                                        "/Users/ana/Library/CloudStorage/Dropbox/Dev", "/Users/ana/dev.txt"]
    assert matching.rank_files("dev", False, found)[0].path == "/Users/ana/dev.txt"
    assert matching.rank_files("informe septiembre", False, [
        Found("/Users/ana/Resumen del informe de septiembre.pdf", False), Found("/Users/ana/Informe septiembre 2026.pdf", False),
        Found("/Users/ana/Informe octubre.pdf", False)])[0].path == "/Users/ana/Informe septiembre 2026.pdf"
    assert matching.rank_files("informe", False, [Found("/Users/ana/Informe.pdf", False)])  # the extension isn't said


def test_a_window_answers_to_its_title_or_its_app():
    windows = [Window("Safari", "MARCA — Diario líder deportivo"), Window("Mail", "Recibidos (3)"),
               Window("Google Chrome", "Presupuesto")]
    assert matching.rank_windows(["marca"], windows)[0].app == "Safari"
    assert matching.rank_windows(["recibidos"], windows)[0].app == "Mail"
    assert matching.rank_windows(["mail"], windows)[0].app == "Mail"
    assert matching.rank_windows(["cromo"], windows)[0].app == "Google Chrome"
    assert matching.rank_windows(["presupuesto"], windows)[0].title == "Presupuesto"
    assert matching.rank_windows(["informe", "trimestral", "de", "ventas"], windows) == []  # half a name isn't enough
    assert matching.rank_windows(["notas"], windows) == []


def test_spotlight_query_asks_for_every_word_and_keeps_quotes_balanced():
    from plugins.control_mac import macos

    query = macos.spotlight_query(["informe", "septiembre"], False)
    assert "'*informe*'cd" in query and "'*septiembre*'cd" in query and " && " in query and "folder" not in query
    assert "public.folder" in macos.spotlight_query(["dev"], True)
    assert macos.spotlight_query(["informe' || kMDItemFSName == '*"], False).count("'") % 2 == 0


# --- Which sentences are commands ---

CASES = {
    "es": [
        ("Abre Chrome.", ("app", "chrome")), ("Jarvis, abre crom", ("app", "crom")), ("Abre la aplicación Notas", ("app", "notas")),
        ("Ábreme Safari, por favor", ("app", "safari")), ("Lanza el Terminal", ("app", "terminal")),
        ("Abre la puerta", ("app", "puerta")),  # taken only if an app answers to it
        ("¿Me abres el correo?", None), ("Abre una ventana nueva", None), ("Abre", None),
        ("Ejecuta el atajo Buenas noches", ("shortcut", "buenas noches")), ("Atajo descansar", ("shortcut", "descansar")),
        ("Lanza el atajo modo trabajo", ("shortcut", "modo trabajo")), ("¿Qué atajos tengo?", None), ("Ejecuta el atajo", None),
        ("Abre el archivo informe septiembre", ("file", "informe septiembre")), ("Abre el documento presupuesto", ("file", "presupuesto")),
        ("Abre la carpeta Descargas", ("folder", "descargas")), ("Muéstrame la carpeta", None), ("Crea una carpeta", None),
        ("Sube a la carpeta superior", None), ("La carpeta Dev", None),
        ("Ve a la ventana de Mail", ("window", "mail")), ("Cambia a la ventana del presupuesto", ("window", "presupuesto")),
        ("Pasa a la ventana de la hoja de cálculo", ("window", "hoja calculo")),
        ("Cierra la ventana", None), ("Minimiza la ventana", None), ("Pon la ventana a la izquierda", None),
        ("Cambia a Safari", ("switch", "safari")), ("Vuelve a casa", None), ("Ve a dormir", None),
        ("Teclea Hola, ¿qué tal?.", ("type", "Hola, ¿qué tal?")), ("Escribe esto: nos vemos a las 8.", ("type", "nos vemos a las 8")),
        ("Jarvis, teclea 1234", ("type", "1234")), ("Escribe un correo a mamá", None), ("Teclea", None),
        ("Teclea Estimado señor, le escribo para pedirle una cita la semana que viene, si es posible por la mañana.",
         ("type", "Estimado señor, le escribo para pedirle una cita la semana que viene, si es posible por la mañana")),
        ("¿Qué puedo decir?", ("help", "")), ("Jarvis, ¿qué comandos entiendes?", ("help", "")),
        ("¿Qué hora es?", None), ("Pon un temporizador de 10 minutos", None), ("Muéstrame el tiempo", None),
        ("Pues no sé, yo creo que deberíamos abrir Chrome mañana", None),
    ],
    "en": [
        ("Open Safari", ("app", "safari")), ("Open the Notes app", ("app", "notes")), ("Launch Chrome, please", ("app", "chrome")),
        ("Open the door", ("app", "door")), ("Could you open the mail?", None), ("Open a new window", None),
        ("Run the shortcut Good night", ("shortcut", "good night")), ("Shortcut rest", ("shortcut", "rest")), ("What shortcuts do I have?", None),
        ("Open the file September report", ("file", "september report")), ("Open the folder Downloads", ("folder", "downloads")),
        ("Open folder downloads", ("folder", "downloads")), ("Create a folder", None),
        ("Go to the Mail window", ("window", "mail")), ("Switch to the budget window", ("window", "budget")),
        ("Go to window Marca", ("window", "marca")), ("Close the window", None),
        ("Switch to Chrome", ("switch", "chrome")), ("Bring up Safari", ("switch", "safari")), ("Go to sleep", None),
        ("Type hello world.", ("type", "hello world")), ("Type this: see you at 8", ("type", "see you at 8")),
        ("Write an email to mum", None), ("What type of bird is that?", None),
        ("What can I say?", ("help", "")), ("What commands do you understand?", ("help", "")), ("What time is it?", None),
    ],
}


@pytest.mark.parametrize("code", ["es", "en"])
def test_which_sentences_are_commands(code):
    i18n.use(code)
    try:
        for text, expected in CASES[code]:
            found = commands.parse(text)
            assert (found and (found.kind, found.name)) == expected, text
    finally:
        i18n.use("en")


# --- The Mac's plugin, with the Mac replaced ---

class Assistant:
    def __init__(self):
        self.said, self.shown, self.tasks = [], [], []

    def say(self, text):
        self.said.append(text)

    def show_heard(self, text):
        self.shown.append(text)

    def reply(self, text, sentence):
        self.shown.append(text)
        self.said.append(sentence)

    def later(self, coroutine):
        self.tasks.append(coroutine)

    def run(self):
        async def all_of_them():
            while self.tasks:
                await self.tasks.pop(0)
        asyncio.run(all_of_them())


class Mac:
    """What the plugin did to it."""

    def __init__(self):
        self.opened, self.ran, self.typed, self.raised, self.asked = [], [], [], [], 0


@pytest.fixture
def mac(monkeypatch, tmp_path):
    done = Mac()
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(control.macos, "installed_apps", lambda: list(APPS))
    monkeypatch.setattr(control.macos, "shortcuts", lambda: ["Buenas noches", "Modo trabajo", "Good night"])
    monkeypatch.setattr(control.macos, "find_paths", lambda words, folder: [
        (str(home / "Documentos" / "Informe septiembre.pdf"), False), (str(home / "Documentos" / "Informe octubre.pdf"), False),
        (str(home / "Dev"), True), (str(home / "Proyectos" / "Dev"), True)] if words[0] in ("informe", "dev") else [])
    monkeypatch.setattr(control.macos, "windows", lambda: [
        control.macos.Window("Safari", "MARCA — Diario líder deportivo", 10), control.macos.Window("Google Chrome", "Presupuesto", 11)])
    monkeypatch.setattr(control.macos, "trusted", lambda: True)
    monkeypatch.setattr(control.macos, "ask_permission", lambda: setattr(done, "asked", done.asked + 1))
    monkeypatch.setattr(control.macos, "open_path", lambda path: done.opened.append(path) or True)
    monkeypatch.setattr(control.macos, "run_shortcut", lambda name: done.ran.append(name) or True)
    monkeypatch.setattr(control.macos, "type_text", lambda text: done.typed.append(text) or True)
    monkeypatch.setattr(control.macos, "raise_window", lambda window: done.raised.append(window) or True)
    monkeypatch.setattr(control.apps, "items", None)
    monkeypatch.setattr(control.shortcuts, "items", None)
    return done


@pytest.fixture
def hear(es):
    found = next(s for s in skills.ordered() if type(s).__name__ == "ControlMac") if kernel.enabled("control-mac") else control.ControlMac()

    def _hear(text):
        assistant = Assistant()
        taken = found.hear(text, assistant)
        assistant.run()
        return taken, assistant
    return _hear


def test_the_skill_listens_after_the_commands_and_before_the_clock():
    orders = {type(s).__name__: s.order for s in skills.ordered()} if kernel.enabled("control-mac") else {}
    if "ControlMac" in orders:
        assert orders["ChooseLLM"] < orders["ControlMac"] < orders["Clock"]
    assert control.ControlMac.order == 15 and not control.ControlMac.local


def test_opens_an_app_said_as_it_sounds(mac, hear):
    taken, assistant = hear("Jarvis, abre crom")
    assert taken and mac.opened == ["/Applications/Google Chrome.app"]
    assert assistant.shown == ["Jarvis, abre crom"] and assistant.said == ["Abro Google Chrome."]
    taken, assistant = hear("Abre ajustes")  # the Mac's own name for it, in its language
    assert taken and mac.opened[-1].endswith("System Settings.app") and assistant.said == ["Abro Ajustes del Sistema."]


def test_what_isnt_an_app_goes_to_the_llm(mac, hear):
    taken, assistant = hear("Abre la puerta")
    assert not taken and not mac.opened and not assistant.said and not assistant.shown
    taken, assistant = hear("Cambia a modo nocturno")  # neither an app nor a window
    assert not taken and not assistant.said


def test_your_own_names_for_apps(mac, hear, monkeypatch):
    import settings

    monkeypatch.setattr(settings, "active", {"app_names": {"el bicho": "Visual Studio Code"}})
    taken, assistant = hear("Abre el bicho")
    assert taken and mac.opened == ["/Applications/Visual Studio Code.app"]


def test_runs_a_shortcut(mac, hear):
    taken, assistant = hear("Ejecuta el atajo buenas noches")
    assert taken and mac.ran == ["Buenas noches"] and assistant.said == ["Ejecuto el atajo Buenas noches."]
    taken, assistant = hear("Ejecuta el atajo cocinar")
    assert taken and mac.ran == ["Buenas noches"] and assistant.said == ["No tienes ningún atajo llamado cocinar."]


def test_opens_a_standard_folder_and_a_file(mac, hear, tmp_path):
    taken, assistant = hear("Abre la carpeta descargas")
    assert taken and mac.opened == [str(tmp_path / "home" / "Downloads")] and assistant.said == ["Abro Descargas."]
    taken, assistant = hear("Abre el archivo informe septiembre")
    assert taken and mac.opened[-1].endswith("Informe septiembre.pdf") and assistant.said == ["Abro Informe septiembre.pdf."]
    taken, assistant = hear("Abre la carpeta dev")  # two of them: which one is said
    assert taken and mac.opened[-1] == str(tmp_path / "home" / "Dev") and assistant.said == ["Abro Dev, en tu carpeta personal."]
    taken, assistant = hear("Abre el archivo presupuesto")
    assert taken and assistant.said == ["No encuentro nada llamado presupuesto."] and len(mac.opened) == 3


def test_goes_to_a_window_or_an_app(mac, hear):
    taken, assistant = hear("Ve a la ventana de marca")
    assert taken and [w.app for w in mac.raised] == ["Safari"] and assistant.said == ["Voy a MARCA — Diario líder deportivo."]
    taken, assistant = hear("Cambia a presupuesto")  # not an app: a window
    assert taken and mac.raised[-1].app == "Google Chrome" and assistant.said == ["Voy a Presupuesto."]
    taken, assistant = hear("Cambia a safari")  # an app: it comes forward
    assert taken and mac.opened == ["/Applications/Safari.app"] and assistant.said == ["Voy a Safari."]
    taken, assistant = hear("Ve a la ventana de mail")  # no window of it: the app
    assert taken and mac.opened[-1].endswith("Mail.app") and assistant.said == ["Voy a Mail."]
    taken, assistant = hear("Ve a la ventana de la hoja de cálculo")
    assert taken and assistant.said == ["No encuentro ninguna ventana de hoja calculo."]


def test_without_the_accessibility_permission_it_says_how_to_grant_it(mac, hear, monkeypatch):
    monkeypatch.setattr(control.macos, "trusted", lambda: False)
    taken, assistant = hear("Ve a la ventana de marca")
    assert taken and not mac.raised and mac.asked == 1 and assistant.said[0].startswith("Para eso necesito el permiso de accesibilidad")
    taken, assistant = hear("Cambia a safari")  # an app needs no permission
    assert taken and mac.opened == ["/Applications/Safari.app"]
    taken, assistant = hear("Teclea hola")
    assert taken and not mac.typed and mac.asked == 2 and assistant.said[0].startswith("Para eso necesito")


def drive(assistant, answer: str | None):
    """Runs what the skill left for later, answering the question it asks."""
    async def run():
        task = asyncio.ensure_future(assistant.tasks.pop(0))
        await asyncio.sleep(0.05)
        assert confirmation.waiting(), "it asked first"
        if answer is not None:
            confirmation.answer(answer)
        await task
    asyncio.run(run())


def test_typing_waits_for_your_yes(mac, es):
    paths.PERMISSIONS.write_text(json.dumps({"confirm": True}))
    assistant = Assistant()
    assert control.ControlMac().hear("Teclea Hola, ¿qué tal?", assistant)
    assert assistant.shown == ["Teclea Hola, ¿qué tal?"] and not mac.typed
    drive(assistant, "sí")
    assert mac.typed == ["Hola, ¿qué tal?"] and assistant.said == ["¿Escribo «Hola, ¿qué tal?»?", "Escrito."]

    assistant = Assistant()
    control.ControlMac().hear("Teclea adiós", assistant)
    drive(assistant, "no")
    assert mac.typed == ["Hola, ¿qué tal?"] and assistant.said == ["¿Escribo «adiós»?", "Vale, no lo escribo."]


def test_typing_without_asking_when_confirmation_is_off(mac, hear):
    taken, assistant = hear("Teclea hola")  # permissions.json «confirm»: false (the tests' default)
    assert taken and mac.typed == ["hola"] and assistant.said == ["Escrito."]


def test_what_can_i_say(mac, hear):
    taken, assistant = hear("¿Qué puedo decir?")
    assert taken and assistant.said == [i18n.L("speech.control_help")] and "abre Safari" in assistant.said[0]


def test_tools_for_the_llm(mac, es):
    assert {"open_app", "run_shortcut", "open_file", "go_to_window", "type_text", "list_apps", "list_shortcuts"} <= set(tools.TOOLS)
    assert {"type_text", "run_shortcut"} <= tools.NEEDS_YES and not {"open_app", "open_file", "go_to_window"} & tools.NEEDS_YES
    assert control.open_app("cromo") == "Opened Google Chrome." and mac.opened == ["/Applications/Google Chrome.app"]
    with pytest.raises(tools.ToolError):
        control.open_app("puerta")
    assert "Google Chrome" in control.list_apps() and control.list_shortcuts().startswith("Buenas noches")
    assert control.run_shortcut("good night") == "Running Good night." and mac.ran == ["Good night"]
    assert control.open_file("informe septiembre", False).startswith("Opened ") and "Informe septiembre.pdf" in mac.opened[-1]
    assert control.go_to_window("marca").startswith("Brought «MARCA") and mac.raised[-1].app == "Safari"
    assert control.go_to_window("safari").startswith("Brought «MARCA")  # its window, by the app's name
    assert control.type_text("hola") == "Typed 4 characters." and mac.typed == ["hola"]


def test_a_windows_path_says_its_name():
    """Windows' paths («C:\\Users\\…»): the file's name is said, not the whole path; and how deep it is counts."""
    assert Found(r"C:\Users\ana\Documents\Informe septiembre.pdf", False).name == "Informe septiembre.pdf"
    assert Found("C:\\Users\\ana\\Dev\\", True).name == "Dev"
    assert matching.depth(r"C:\Users\ana\Dev") == matching.depth("/Users/ana/Dev") == 3
