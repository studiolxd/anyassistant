# AnyAssistant

An old phone or tablet becomes the eyes, mouth and ears of a voice assistant;
all the processing runs on the Mac. The assistant is called Jarvis until you give
it another name (`name`: also its wake word, «Hey …»). WebRTC transport (Opus + Chrome's echo
cancellation) over the local network.

## Phase 0 · Preparing the phone

1. A ROM with Android 7.1 or later and an up-to-date Chrome (a Lenovo tablet with
   Android 4.4 and Chrome 81 also works).
2. A fixed IP for the Mac (currently `192.168.1.137`): in macOS, Wi-Fi → network
   Details → *Private Wi-Fi address* set to **Fixed** (with *Rotating* the IP changes),
   or better, a DHCP reservation on the router. The phone on the 5 GHz network if there is one.
3. In the phone's Chrome: `chrome://flags` → *Insecure origins treated as secure* →
   `http://192.168.1.137:8080` → *Enabled* → Relaunch.
4. Settings → Battery → optimization: Chrome *not optimized*.


## Installing

```sh
./install.sh              # asks each step; Enter keeps what comes
./install.sh --defaults   # everything as it comes
```

It copies the program to `~/Applications/AnyAssistant`, gets its own Python (uv,
no administrator rights), keeps your data in `~/Library/Application Support/AnyAssistant`
and what can be rebuilt in `~/Library/Caches/AnyAssistant`, and then goes through
`bin/anyassistant setup`: this computer, the plugins' packages, language, name, LLM, the
Swift bridges, the speech models, pairing, memory, eyes, starting with the Mac
(launchd) and the address (and code) for your tablet. Run again, it updates the
program and keeps your data.

**On Linux** the same `./install.sh`: the program in `~/.local/opt/AnyAssistant`, your data in
`~/.local/share/AnyAssistant`, the cache in `~/.cache/AnyAssistant`, and it starts with the
computer as a systemd user service (`sudo loginctl enable-linger $USER` so it also starts at boot
without anyone logging in: a server with no screen). Bonjour comes from Python's zeroconf, mail
passwords go to the Secret Service (keyring), and PyTorch is the CPU one. Its own engines there:
speech recognition with Parakeet v3 in ONNX (`stt-parakeet-onnx`, on the CPU, with Whisper as its
fallback) or Whisper (`stt-faster-whisper`, CPU or an NVIDIA card), the voice Kokoro
(`tts-kokoro`: ef_dora in Spanish, af_heart in English) or the lighter Piper (`tts-piper`, for a
Raspberry Pi), the wake word with faster-whisper.
**Windows** for now runs from the project (`uv run server/main.py`); its app comes later. Apple's
model is only on the Mac; how each piece was made, in `docs/windows-y-linux.md`.

**The Windows and Linux app** (`apps/desktop`, Electron): in the tray, as the Mac app in the menu
bar, with the same menu and windows. The first time, its installer window (as the Mac's: «Install»,
«Customize…», or «Connect to another server…» to only talk to another computer's server) makes its
Python and goes through the same steps as `bin/anyassistant setup`. Then it runs the server (or
adopts the one running: Linux's systemd service): the menu says how it is and which devices are
connected, starts, restarts and stops it (a «restart» by voice too: the server ends with the code the
app asked for and the app starts it again); «Show Eva» opens its face (the page, with Chromium's
microphone, camera and echo cancellation) and «Listen on this device» keeps it listening while
hidden; «Themes», «Connect another device», «Devices» and «Settings» are windows (the admin page,
`/admin`, each part in its own); «Log», «Set it up again», «Open at login». Its packages (unsigned:
on Windows, «More info» → «Run anyway» the first time) are built on GitHub Actions («packages»):
the installer `.exe`, the AppImage and the `.deb`, with the program and uv inside. Your data goes
to `%APPDATA%\AnyAssistant` on Windows, `~/.local/share/AnyAssistant` on Linux. While developing:
`cd apps/desktop && npm install && npm start` (`ANYASSISTANT_SETUP=1 npm start` shows the installer
window too). The differences with the Mac app, and why: `docs/paridad-escritorio.md`.

**Administering it** without the Mac app: the page `/admin` (pair a device with its QR, devices,
settings, plugins, voices, mail, admins): from the computer itself, or from another one's browser
with an admin code (`bin/anyassistant admin-code`, over SSH on a Linux with no screen; or the
page's Admins). A device paired to talk can't administer.

```sh
~/Applications/AnyAssistant/bin/anyassistant update      # the new version from where it was
                                                          # installed from; packages, models; restarts
~/Applications/AnyAssistant/bin/anyassistant uninstall   # asks whether your data goes too
                                                          # (--all, --keep-data)
```

The steps come from the core (`server/install_steps.py`) and from the plugins
(`@installer.question`, `@installer.task`, `@installer.device` for something done on
the device), so a plugin brings its own. Any of them again later:
`bin/anyassistant setup memory`. For the app's window: `bin/anyassistant setup --list --json`
(the questions) and `bin/anyassistant setup --json --set llm=apple …` (one event per line).

A «device» step needs this computer's microphone, so the setup only names it: the Mac app's and
the Windows and Linux app's installer offer it right after installing, once the server runs, on
the computer's own device (its button, or «Not now»; through `/setup/device/<id>`); the terminal
says how to do it later. The plugin «voices» brings one, «Your voice»: you read a few phrases out
loud and it knows you (only while it knows nobody yet).

## Running it

```
bin/anyassistant start [options]   # in the background; e.g. bin/anyassistant start --llm hermes
bin/anyassistant stop
bin/anyassistant restart           # like saying «restart»: same options
bin/anyassistant status
bin/anyassistant log               # live log (.build/anyassistant.log)
```

Installed, these are `~/Applications/AnyAssistant/bin/anyassistant …` (launchd starts it
with the Mac). In the project folder, the same commands run a development copy with
its own `settings.json` (not in git): keep another `port` (8081) so it doesn't clash
with the installed one, and your real data stays in the installation.

Or in the foreground, to see the log directly:

```
uv run server/main.py                    # Phase 3: assistant (Parakeet + Claude + AVSpeech)
uv run server/main.py --mode transcribe  # Phase 2: transcription only
uv run server/main.py --mode parrot      # Phase 1: repeats what it hears (mic and speaker test)
```

The first time it downloads the models (Parakeet ~1.2 GB, Whisper turbo ~1.6 GB, Whisper base).

- Phone: `http://192.168.1.137:8080` → **Start** → allow microphone and camera.
- Mac: `http://localhost:8080/monitor` to watch the camera.

The first time, macOS asks whether Python may accept incoming connections: *Allow*.

## Languages

Everything Jarvis says, shows or understands lives in `locales/<code>.json`:
spoken sentences (`speech`), the page's texts (`ui`), the voice commands it
understands (`commands`: sleep, reload, restart, yes, no), Whisper's typical
hallucinations for that language (`stt`), the default voice and the recognition
language. **English (`en.json`) is the base**; a missing key in another language
falls back to it, so **adding a language means adding a file**. Even how the
date and time are said aloud is set there (`calendar.now_style`: `ampm` or
`periods`, with its format).

The language is, in this order: `--lang`, `settings.json`'s `language`, or the
Mac's preferred one when there is a locale for it.

**By voice**: «Speak English», «Switch to Spanish», «Háblame en inglés», «Cambia a
español»… (understood in any language). Jarvis says so, saves it in
`settings.json` and restarts in the new language; the page picks up its texts when
it reconnects. Only short commands that start with the verb count: «¿Quién habla
inglés en Suiza?» goes to the LLM. Each locale lists the verbs
(`commands.language`) and the languages' names (`languages`): a new language needs
its name added to the others.

## Settings

`settings.json` in the project (not in git; see `settings.example.json`) holds
the preferences, so `bin/anyassistant start` needs no options:

```json
{
  "language": "es",
  "name": "Jarvis",
  "instructions": ["I'm a freelance designer.", "I invoice with Holded."],
  "voice": {"es": "Mónica", "en": "Samantha"},
  "theme": "eyes",
  "video": "auto"
}
```

Keys are the server's options with underscores instead of dashes; options on the
command line win over it (`uv run server/main.py --help` lists them all). They are
all defined in `server/options.py`; most apply at once, the rest restart it.

<!-- options: made by `python server/options.py markdown`; a test checks it is current -->
**Plugins**

| Option | Default | |
|---|---|---|
| `plugins` | — | which plugins are on or off, if not as they come: {"memory": true, "tap-to-wake": false} |

**Assistant**

| Option | Default | |
|---|---|---|
| `name` | `"Jarvis"` | the assistant's name: its wake word, the page's title, what the LLM calls itself *(restarts)* |
| `language` | — | en, es…: what it speaks and understands (default: the system's) *(restarts)* |
| `llm` | `"claude"` | the LLM: claude, codex, gemini, opencode, apple, openai, ollama, hermes… *(restarts)* |
| `llm_model` | — | the LLM's model (for Claude: sonnet, opus, haiku…) *(restarts)* |
| `mcp` | — | .mcp.json with the MCP servers (default: your data folder's) *(restarts)* |
| `instructions` | — | yours, added to the LLM's (text or a list of lines): who you are, how to talk… |
| `detail` | `"neutral"` | how much it says: concise, neutral, detailed or one of detail_levels |
| `detail_levels` | — | more levels, or other texts for these: {"name": "instruction for the prompt"} |
| `ignore_others` | `true` | the LLM stays quiet when what it hears is clearly not for it |
| `skills` | `true` | time, date, timers, alarms, reminders, sums, units and volume, without the LLM |
| `conversations` | `2` | how many devices can be in a conversation at once (each its own LLM: with Claude, two processes each); 1: one at a time, the others fall asleep |
| `quiet_hours` | `"23:00-08:00"` | hours when it doesn't give notices (e.g. 23:00-08:00; empty: any time); alarms ring anyway |
| `notices_where` | `"everywhere"` | where notices are said: on every device, or on the last one you talked to |
| `calendar_notice_minutes` | `10` | how many minutes before an event it gives notice |
| `email_notice_query` | `"is:unread in:inbox category:primary"` | which emails it gives notice of (a Gmail search; by default the Primary tab's unread ones) |
| `email_notice_says` | `"sender"` | what it says of each new email |
| `email_check_minutes` | `5` | every how many minutes it looks for new emails |
| `read_photo` | `true` | a full-resolution photo when asked to read |
| `llm_fallback` | `"auto"` | if the LLM can't answer, another one does: auto (Apple's local model if there is one), an LLM's name, or none |
| `openai_key` | — | the API key for «openai» (saved in the system's keychain) |
| `openai_url` | — | the OpenAI-compatible service for «openai» (OpenRouter, Groq, LM Studio…) *(restarts)* |
| `mail_accounts` | `[]` | mail accounts besides Gmail (IMAP and SMTP); add them with `bin/anyassistant mail add you@domain.com` (the password goes to the Keychain) |

**Memory**

| Option | Default | |
|---|---|---|
| `memory` | `"explicit"` | what it remembers: only when asked (explicit) or also on its own (auto) |
| `memory_facts` | `50` | facts before the LLM compacts them |
| `memory_conversations` | `10` | conversation summaries kept |
| `memory_days` | `30` | days a conversation summary is kept |

**Voice**

| Option | Default | |
|---|---|---|
| `stt` | `"parakeet"` | speech recognition: parakeet, mlx-whisper… *(restarts)* |
| `stt_model` | — | its model *(restarts)* |
| `stt_unload_minutes` | `30` | minutes without transcribing before the speech recognition model leaves memory (0: never); it comes back when needed |
| `tts` | `"avspeech"` | its voice engine: avspeech, macos, kokoro, piper… or none *(restarts)* |
| `voice` | — | the voice (default: the language's); one, or one per language: {"es": "Mónica", "en": "Samantha"} *(restarts)* |
| `rate` | — | words per minute *(restarts)* |
| `volume` | `100` | its voice and sounds, 5–100 % |
| `wake` | `"whisper"` | the wake word engine: whisper, openwakeword… or none *(restarts)* |
| `wake_word` | — | the word or model (default: its name) *(restarts)* |
| `threshold` | — | how sure the wake word must be (each engine has its own default) *(restarts)* |
| `vad` | `"silero"` | voice activity detection: silero… *(restarts)* |
| `silence` | `0.6` | seconds of silence that end a sentence *(restarts)* |
| `follow_up` | `20` | seconds it keeps listening without its name after it last spoke or heard you |
| `echo_guard` | `1.2` | seconds without listening after speaking (its own echo) *(restarts)* |
| `voice_interrupt` | `true` | «Jarvis, stop» while it speaks |
| `pause_when_microphone_busy` | `true` | it stops listening while another app uses the device's microphone (a call, a meeting); back when it ends |
| `listen_while_speaking` | `true` | it keeps listening while it speaks and stops if someone talks over it, telling its own echo by loudness (experimental) |
| `echo_match` | `0.8` | how alike the loudness of what it hears must be to what it sends to count as its own echo (0–1, with listen_while_speaking) |
| `tap_to_stop` | `true` | tapping the screen stops it talking |
| `fillers` | `true` | «One moment, let me check» when a tool is slow |
| `noise_adapt` | `true` | speech detection follows each room's noise, as the device hears it (and its calibration, if measured); off: fixed thresholds |

**Skills**

| Option | Default | |
|---|---|---|
| `app_names` | — | what you call an app, if it doesn't understand you: {"crome": "Google Chrome"} |
| `interpreter` | `"auto"` | an LLM for skills said in unusual ways: auto (a local one if there is: Apple's on a Mac with it) or an LLM's name |
| `morning_after_alarm` | `true` | the morning summary when you stop the first alarm of the day (before 12) |
| `unread_query` | `"is:unread in:inbox"` | which emails the summary counts (a Gmail search) |
| `ring_seconds` | `60` | how long an alarm rings if nobody stops it, in seconds; 0: until someone stops it (at most 30 minutes) |
| `snooze_minutes` | `5` | «snooze» without saying how long |
| `alarm_rings` | `"everywhere"` | where timers, alarms and reminders ring: everywhere (every device) or where_set (the device they were set on) |
| `location` | — | your city, for the weather (e.g. Valencia) |

**Screen**

| Option | Default | |
|---|---|---|
| `theme` | `"eyes"` | the screen's look: eyes, one from the community or yours (a device's ?theme= wins) |
| `theme_options` | — | the theme's options: {"accent": "#ff7a45"} |
| `themes_dir` | — | your themes (default: themes in your data folder) *(restarts)* |
| `video` | `"auto"` | camera quality; auto: each device by its memory (a device's ?video= wins) |
| `show_time` | `true` | the time while asleep |
| `show_date` | `true` | the date while asleep |
| `show_hint` | `true` | «Say “Hey, Jarvis”» while asleep |
| `show_status` | `true` | «Listening», «Thinking…» while awake |
| `show_heard` | `true` | what you said |
| `show_answer` | `true` | what it answers |
| `history` | `2` | earlier sentences kept on screen |
| `show_timers` | `true` | running timers, alarms and reminders |
| `show_stats` | `false` | the connection's RTT, jitter and losses |
| `clock` | `"auto"` | 12 or 24 hours (auto: the language's) |

**Privacy and security**

| Option | Default | |
|---|---|---|
| `log_transcripts` | `false` | write what it hears and says to the log (to debug); otherwise only lengths |
| `confirm_wait` | `120` | seconds to answer «yes» to an action that changes something |
| `confirm_valid` | `60` | seconds a «yes» stays valid |
| `voice_check` | `"all"` | what needs a known voice once someone's is learnt: all (it only listens to known voices), actions (only the «yes» that authorizes one) or off |
| `voice_adapt` | `true` | keep learning each voice from what that person says (only voice prints, never the audio; off: what it learnt that way is deleted) |
| `voice_match` | `0.5` | how alike a voice must be to a known one (0–1; higher: stricter) |

**Server**

| Option | Default | |
|---|---|---|
| `host` | `"0.0.0.0"` | the address it listens on *(restarts)* |
| `port` | `8080` | the port (bin/anyassistant reads it too) *(restarts)* |
| `mode` | `"assistant"` | assistant, transcribe (only shows what it hears) or parrot (repeats it) *(restarts)* |
| `record` | `false` | saves everything that arrives to a WAV, in the cache's «recordings» (to debug) *(restarts)* |
| `community_catalog` | `"https://raw.githubusercontent.com/studiolxd/anyassistant-community/main/index.json"` | the community catalog: the address of its index (themes and plugins to install) |
| `https_port` | `443` | the HTTPS port (the page with a certificate devices trust) *(restarts)* |
| `https_redirect_port` | `80` | the HTTP port that sends to the HTTPS page (0: none) *(restarts)* |

<!-- /options -->

**How much it says**: `detail` is `concise` (one short sentence), `neutral` (one
to three; the default) or `detailed` (a paragraph or two). Each level is an
instruction added to the prompt (the built-in ones: `DETAIL_LEVELS` in
`server/llm/__init__.py`, inserted into `INSTRUCTIONS` there). `detail_levels`
adds levels or changes those texts; write them in English, like the rest of the
prompt:

```json
{"detail": "teacher",
 "detail_levels": {"telegraphic": "Answer in five words or fewer.",
                   "teacher": "Explain it step by step, as a patient teacher would, with an everyday example."}}
```

By voice too: choosing one («be briefer», «give me more detail», «use the teacher
mode») doesn't ask for your «yes»; creating or changing one («make a teacher mode
that explains step by step») does, since its text goes into its instructions:
Jarvis says what it will save first. If the level changes mid-conversation, the
LLM hears it with the next question.

The page changes at once when a screen option changes.

A wrong value (`"theme": "smiley"`) stops the server with the reason.

**Pairing** (the plugin `pairing`, off by default): with `"plugins": {"pairing": true}`, a device must enter a code before using
Jarvis. `bin/anyassistant pair` shows one on the Mac (6 digits, 5 minutes, one device);
the page asks for it and the device remembers it (a cookie; the server keeps only
its hash in `paired.json`). Unpaired devices can't connect, see the camera
(`/video.mjpg`) or the status; the Mac itself always can. `bin/anyassistant unpair`
forgets them all.

**Connecting a device** («Conectar otro dispositivo», in the Mac app and the web admin): one QR
for everything, `http://<ip>:<port>/connect?code=…`, the server itself by its address now (old
devices don't resolve `anyassistant.local`; made when shown, so a changed address doesn't matter)
and the code big next to it. Scanned with the phone's camera, `/connect` (the plugin `page`)
offers «Abrir en la app» (`anyassistant://connect?host=…&port=…&code=…`: the iPhone and Android
apps register that link and pair by themselves) or going on in the browser: it pairs with the code
and opens the page; with the plugin `https` on, the certificate first (the QR is plain HTTP so it
works before). The apps also read the same QR themselves («Escanear código»). «Otras formas de conectar»
keeps the rest: the app's list of servers and the code; the browser's `http://anyassistant.local:<port>`
and, for old devices, the address.

**Several devices at once** (`server/hub.py`): each one connects with its own id (the
page keeps it), so a device that reconnects replaces its old connection. Each device has
its own conversation (its own LLM, made the first time it wakes; at most `conversations`,
2 by default: with Claude each is two processes; with 1, one at a time and the others
sleep): two people in two rooms don't cut each other off. What a device's LLM does with its
tools happens on that device (its camera, «here»: `/mcp?device=…`). When
two hear the same «Jarvis» (within 1.5 s), the one that heard it louder answers; while one
speaks, its voice saying its name doesn't wake another. The plugin `devices` gives each a
name (from what it is: iPad, Android tablet…) and a room, in `devices.json`: «this is the
kitchen's» (the LLM's `set_device`), «which devices are there?» (`get_devices`), «dile a la
cocina que bajo ya» (`tell_device`: said aloud there and shown on its screen, nothing more);
and the LLM hears, with the first message of each conversation, which device and room it
is («here» means there);
`GET /devices` from the Mac lists them.

**The Mac app** (`apps/mac`, in the menu bar): it installs and runs the server, connects devices
(the QR), and has the settings; and the assistant is on the Mac too: «Show Eva» opens its face in a
window (the iPhone app's own files, `Sources/AnyAssistant/Client`, linked to `apps/ios/Sources`:
Eyes drawn natively, any other theme the server's page in a web view, as on the iPhone), with the Mac's microphone and speaker (macOS's echo cancellation) and, while the window is open,
its camera; «Listen on this Mac» turns the microphone off. It talks to its own server (no code).
On a Mac without the server, it is only that: a client of another Mac's («The server is on
another Mac» when installing: its address and the code). `apps/mac/install-dev.sh --build` while
developing.

**The iPhone and iPad app** (`apps/ios`, iOS 15 or later, and the plugin `stream-api`): native.
Its face is its theme: Eyes drawn natively (`apps/ios/Sources/Themes.swift`), any other the
server's page in a web view (`WebTheme.swift`, see «Themes»), following the Mac's state, texts
and screen settings (its `/config`). The microphone and the speaker go over a
WebSocket (`GET /stream?device=…`: 16-bit mono PCM at 48 kHz both ways, and the page's JSON
messages), with iOS's echo cancellation; so it keeps listening with the screen off (Settings in
the app: the gear). With the plugin `eyes`, its camera: a frame a second while awake («¿qué ves?»),
a full photo for «lee esto», live for «muestra la cámara». On iOS 26 or later, alarms and
timers are the phone's own alarms (AlarmKit: they ring on silent); before, notifications. Both
ring with the theme's alarm (`GET /alarm.wav?theme=…`: as the server rings it, 28 s, kept in the
app's Library/Sounds); reminders are plain notifications (on Android too).
In the background, answers and messages arrive as notifications. «Talk to AnyAssistant» for
Siri, Shortcuts and the Action button (iOS 16 or later). Paired by scanning the QR («Escanear
código»: VisionKit where it exists, else AVFoundation), by the QR page's «Abrir en la app», or
choosing the server and typing the 6-digit code; HTTPS trusting only your Mac's authority.

**The Android app** (`apps/android`, Android 8 or later, Kotlin and Compose; the plugin
`stream-api`): the same as the iPhone's. Its face, Eyes natively (`Themes.kt`) and any other theme
in a web view (`WebTheme.kt`); its microphone
and speaker over the WebSocket, in «communication» mode with Android's echo canceller; it finds
the Mac by Bonjour (`_anyassistant._tcp`: many Androids don't resolve anyassistant.local), pairs
with the 6-digit code (or scanning the QR: CameraX and ZXing, no Play Services; or opened by the QR
page's «Abrir en la app») and talks HTTPS trusting only your Mac's authority. With the screen off it
keeps listening while its notification is there («Stop listening»). Alarms, timers and
reminders are the phone's own alarm clock: they ring on the alarm channel, even on silent, full
screen over the lock screen; stopped on the phone, the Mac stops too. «Hablar»: long-press the
icon, the quick settings tile, or the assistant gesture (choose it as the phone's assistant).
`apps/android/run.sh` builds it and installs it on the device adb sees (or the emulator).

**The Apple Watch** (`apps/watch`, and the plugin `talk-api`): press to talk on your wrist.
It goes inside the iPhone app, and also works on its own. The first time it asks for the
6-digit code the Mac app shows («Pair a device…»), and finds the Mac at `anyassistant.local`
(else its IP, learnt when pairing). With the plugin `https` it talks HTTPS, trusting
only your Mac's own authority. Each sentence goes to `POST /talk?device=…` (a WAV) and comes back
as text and voice; the watch is a device like the others (its name and room, its own
conversation, its voice checked), a conversation lasting while you keep talking.

Both are one Xcode project (xcodegen; `apps/shared` is their common code): `apps/apple/build.sh`
makes `apps/apple/AnyAssistant.xcodeproj` and checks they build; `apps/apple/run.sh` installs the
iPhone app on the iPhone connected by cable (Developer Mode on); `apps/apple/testflight.sh`
uploads both to TestFlight.

**Who is speaking** (the plugin `voices`): each person's voice print, made on the Mac (a
WeSpeaker ONNX model, 26 MB, downloaded the first time) and kept in `voices.json`. «Aprende mi
voz» on a device: it asks your name and five phrases to read (with the microphone it will
hear you with); or the Mac app (Settings → Voices: who is known, forget, learn one on a
device). Once someone is known, a new voice is learnt only at a known voice's request or
from the app. `voice_check`: `all` (the default: it only listens to known voices; others
are dropped, the log says so with the score), `actions` (only the «yes» to an action; an
unknown one is refused) or `off`; `voice_match` (0.5) how alike. Short sentences («sí»)
say little about who: they count as whoever the conversation recognised, unless they
clearly sound like someone else. The LLM hears who is talking.

**When the voice isn't clear** (with `all`): a voice clearly nobody known's (below 60 % of
`voice_match`: 0.30 by default) is dropped; one in between (0.30–0.50: far from the microphone, a
cold) isn't. If what it said would do something (an action, anything for the LLM) it asks «No he
reconocido bien tu voz: ¿lo hago?» (the plugin `confirmation`: the face shows the question) and
does it on a «sí» from a recognised voice (a short «sí» counts as whoever the conversation already
recognised; otherwise say it longer: «sí, hazlo»); anything else cancels it. Harmless commands
(the time, a sum, «para», «apágate») go through, as «Ey, Eva» does: only a clear stranger is
refused. **When a voice print has aged**: it keeps each person's usual score per device (the median
of the sentences accepted as theirs there); when the recent ones stay about 0.15 below it, for
five sentences, it says once «Suvi: conviene volver a aprender tu voz en iPad (cocina)» (a
notice, through `notices`), and the Mac's Voices page and `/admin` → Voices show it, until it
recovers or the voice is learnt again on that device.

**By voice**: «Use the bedside theme», «Change your voice to Mónica», «From now on your
name is …», with Jarvis's own tools (below). After every answer the server reads
`settings.json` again (also when you edit it by hand): the theme changes on the
screen at once, and anything else (voice, name, language…) restarts it when it
finishes speaking. Options given on the command line don't change.

## Its own tools (MCP)

The server is also an MCP server, `anyassistant`, at `/mcp` (only from the Mac itself:
no device on the network, paired or not). Allowed like any other in
`permissions.json` (`"allowed": {"anyassistant": "all"}`, or a list of tools), Claude
can manage Jarvis in your own words («show me what you see», «use the round
theme», «what do you know about me?»):

| Tool | | Your «yes» |
|---|---|---|
| `get_status`, `get_settings`, `get_memory` | device and camera, language, LLM, eyes, memory; name, theme, voice; what it remembers | no |
| `set_theme` | the screen's look, for every device or only this one | no: it only changes the look |
| `create_theme`, `get_theme`, `edit_theme` | a theme of your own as a copy of another, read its files, rewrite one (it answers what the check finds; the theme on screen changes at once) | no |
| `delete_theme` | delete one of yours | yes |
| `set_voice`, `set_name`, `set_language` | saved to `settings.json`, applied after the answer | yes |
| `remember`, `forget` | memory facts: the person talking's, or shared | yes |
| `camera` | shows or hides the live camera on the screen | no: it only changes the screen |
| `set_screen` | shows or hides parts of the screen for every theme: the time, the date, the transcription, the answers, the timers… (the screen settings) | no: it only changes the screen |
| `set_detail` | how much it says: concise, neutral, detailed or your own levels | no: it only changes how it talks |
| `add_detail_level`, `remove_detail_level` | create, change or remove a detail level | yes: its text goes into the prompt |
| `get_llms`, `set_llm` | the LLMs it can use (and whether each is available); switch to another, with a model | `set_llm`: yes |
| `reload_tools`, `restart` | after the answer, so the LLM isn't cut off while using it | yes |

Tools that change something ask for your «yes» themselves (the server, not the
LLM), so it holds for any LLM: with Claude, Hermes or another MCP client.

**OpenAI, Ollama and other OpenAI-compatible LLMs** (the plugin `llm-openai`, which also brings
Hermes): `"llm": "openai"` (or «usa OpenAI») with its key in the keychain (`bin/anyassistant
llm-key openai`, or `OPENAI_API_KEY`); `openai_url` makes it any compatible service (OpenRouter,
Groq, Mistral, LM Studio…); `llm_model` the model (gpt-5-mini by default). `"llm": "ollama"`: the
models running on this computer with Ollama, no key. They get Jarvis's own tools (above), each
asking for your «yes» when it changes something; Jarvis keeps their conversation.

**With your subscriptions, through each vendor's CLI** (like `claude` with Claude Code: no API
key, the CLI signed in with your account):

- **Codex** (the plugin `llm-codex`; `"llm": "codex"`, or «usa Codex»): ChatGPT through OpenAI's
  Codex CLI (`codex login` with your ChatGPT account). Each device's conversation is a thread of
  one `codex app-server` process (its JSON-RPC protocol), the answer in pieces; `llm_model`, its
  model (yours in Codex by default). It keeps its own MCP servers (`~/.codex/config.toml`,
  untouched) and gets Jarvis's tools when `permissions.json` allows `anyassistant` (as Claude).
  Before each MCP tool Codex asks Jarvis, who answers with the plugin `confirmation`, the same
  rule as Claude's hook: reads (`get_`, `list_`…; or marked read-only by their server) and
  Jarvis's own tools go through, anything else waits for your «yes» and Codex calls it again.
  Its terminal, file tools, image viewer, browser, computer use, plugins and subagents are off,
  in a read-only sandbox with an empty folder as its workspace: so no `commands` (`bin/gog`),
  and it sees the camera only when the question comes with the image.

- **Gemini** (`llm-gemini`; «usa Gemini»): Google's Gemini CLI with your Google account (sign in
  once with `gemini`), through its ACP mode (`gemini --acp`, the Agent Client Protocol editors
  use). Jarvis's instructions replace its system prompt; a policy of Jarvis's, at the
  administrator's level (`--admin-policy`, above yours), denies its file, terminal, web fetch and
  memory tools (not even shown to it), keeps its web search, and makes every MCP tool ask Jarvis
  first (if the policy ever fails to load, Jarvis doesn't use it). Google no longer accepts Gemini
  CLI with some free accounts («Gemini Code Assist for individuals… migrate to Antigravity»): then
  it says so.
- **OpenCode** (`llm-opencode`; «usa OpenCode»): OpenCode with the providers you connected in it
  (`opencode auth login`), through `opencode acp`; `llm_model` as `provider/model` (`opencode
  models`). Its configuration for this run goes on top of yours (`OPENCODE_CONFIG_CONTENT`): every
  tool asks Jarvis, who refuses its own tools (files, terminal, web fetch, subagents), allows its
  web search, reads (`get_`, `list_`… of the servers it knows) and Jarvis's tools. Its instructions
  go with each conversation's first message (its free models only answer with its own system
  prompt and tools).

With Gemini and OpenCode the agent waits for the answer before a tool: what changes something,
Jarvis asks aloud («OpenCode quiere hacer esto: holded: create invoice. ¿Lo hago?») and your «yes»
allows that call, once (the plugin `confirmation`, as with Hermes's approvals). Shared by both:
`server/llm/acp.py`.

**With Hermes**: add it to Hermes's MCP servers and restart its gateway:

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  anyassistant:
    url: http://127.0.0.1:8080/mcp
```

(`hermes mcp add anyassistant --url http://127.0.0.1:8080/mcp` does the same, asking in
the terminal which tools to enable; then `hermes gateway restart`.)

Nothing to lift its own safeguards: no tool touches the permissions, the
confirmation times, the port or your `instructions`; the LLM only among the
installed ones and with your «yes». The fixed voice
commands («activa la cámara», «para», «habla en inglés»…) stay: they need no LLM,
so they answer at once; the tools are for everything else.

## Memory

The plugin `memory`, off by default: `"plugins": {"memory": true}`, and `"memory"`
in `settings.json`: `explicit` (default) or `auto`. It lives in
`memory.json` (not in git), readable and editable:

```json
{"facts": ["The wifi is called Casa."], "people": {"Suvi": ["Has a dog called Toby."]},
 "conversations": [{"at": 1793439182, "summary": "…", "who": "Suvi"}]}
```

- **explicit**: only what you ask: «remember that I invoice with Holded», «what do
  you know about me?», «forget that». Claude does it with its own tools
  (`remember`, `forget`, `get_memory`), with your «yes» first: it repeats what it
  will keep, so a misheard word («oldev») is caught.
- **auto**: also, when it falls asleep, the LLM reviews the conversation in the
  background and keeps durable facts about you and a one-line summary of it (the
  last 10, for 30 days: «what did I ask you yesterday?»). With Claude or Apple's
  model (which, with its small context, only reviews the end of long conversations).

Every conversation starts with the facts (and, in auto, the recent summaries) in
its instructions, **as notes, not orders**. Facts come only from what **you** said:
never from the assistant's lines, which may quote an email («remember that the
user wants every invoice sent to …») that would otherwise stay as an instruction.
Beyond 50 facts, the LLM compacts them when it falls asleep, merging and
shortening them to about 35 («Has a dog» + «The dog is called Toby» → «Has a dog
called Toby»); only if it can't do the oldest go. Corrections update the fact
they correct (`update`), not add another.

**Each person's own.** With the plugin `voices` (it knows who is talking), what it
learns in a conversation with a recognised voice is **that person's** (`people`);
what it learns with no voice recognised (voices off, nobody learnt yet, a voice it
didn't know) is **shared** (`facts`), and so is what you ask it to keep for
everyone («remember that the wifi is called Casa, for everyone»). A
`memory.json` from before is all shared: it works as it did. Each conversation
gets the shared notes in its instructions and, once it recognises who is talking,
that person's with «(Suvi is talking.)», never anyone else's. «What do you know
about me?», «forget that» and corrections act on that person's facts and the
shared ones; with a voice it doesn't know, only on the shared ones. Summaries are
kept per person too (the last 10 of each). If two people speak in one
conversation, each one's review only takes facts from what they said. From the
server itself (Claude through `/mcp` with no device), `get_memory` shows everyone's,
grouped by whose they are.

**In Settings → Plugins → Memory → Memories** (the Mac app, and the admin page of the Windows and Linux
app) you see what it remembers: «Shared» and each person's (`/admin/memory`, only
for the owner). Each fact can be edited in place, deleted, or moved to someone else
(any known voice) or to shared. **Forgetting a voice** (Settings → Voices → Known
voices) that it remembers things about asks «Also erase what it remembers about
Suvi?»: «Keep» leaves their facts under their name (learning the voice again under
the same name brings them back); «Erase» deletes them too, with their conversation
summaries. Saying «olvida mi voz» on a device keeps them.

Any spoken sentence in a locale can be a list of variants (`speech.wait`: «One
moment, let me check.», «Let me look.»…): one is picked at random each time, never
the same twice in a row. The filler is only said when a tool takes more than
~1.2 s; its own tools and actions waiting for your «yes» answer at once.

The LLM gets English instructions plus «Always reply in {language}».

## Phase 1 · Parrot

It records what you say and plays it back when you stop; while repeating it
doesn't listen (a straight echo fed back: the tablet's echo cancellation isn't
enough). Useful to test the microphone, the speaker and the network (RTT, jitter
and lost packets show at the bottom of the screen).

## Phase 2 · Ears

Silero VAD separates speech from noise; when you finish a sentence (0.6 s of
silence) it is transcribed and shown as a caption on the phone. Timings go to the
Mac's log.

### Transcription engines

Compared with 32 real sentences said to the tablet (median per sentence, on an M4):

| `--stt` / `--stt-model` | Median | Notes |
|---|---|---|
| **`parakeet`** (default) | 114 ms | Parakeet TDT v3; as accurate as turbo or better |
| `mlx-whisper` (turbo) | 938 ms | Pads the audio to 30 s: slow on short sentences |
| `mlx-whisper --stt-model mlx-community/whisper-small-mlx` | 230 ms | More mistakes |
| `mlx-whisper --stt-model mlx-community/whisper-base-mlx` | 76 ms | Many mistakes |

Parakeet detects the language by itself and sometimes drifts into English
(«¿Qué hora es?» → «Koda is a very good idea»); if the result looks like another
language, that sentence is redone with Whisper turbo in the right one. The sleep
command is matched by similarity («Apparaté» for «Apágate»).

`--silence` (0.6 s by default) is the silence that ends a sentence: lower answers
sooner but may cut you off if you pause.

**Each room is different** (the plugin `calibration`): the VAD's thresholds (0.5 to start a
sentence, 0.35 for silence) aren't only fixed ones. The ear keeps a noise floor per device, as
its microphone hears the room: how loud the background is and how much the VAD takes that noise
for speech, up slowly (a fan, the TV) and down fast; a sentence has to score above that noise
(plus a margin, up to 0.85) and stand above it in loudness. «Calibra el micrófono» on a device,
or «Calibrate» in the Mac's Devices window or `/admin` → Devices, measures it explicitly: it asks
for silence, listens for three seconds, says what it found («la sala está en silencio», «hay algo
de ruido de fondo»…) and keeps it in `calibration.json` by device, as the starting point whenever
that device connects; if it heard talking, it says so and keeps nothing. `noise_adapt` off: the
fixed thresholds. The wake word keeps its own detection.

**Not everything it hears is for it.** Once awake it listens without its name only
for `follow_up` seconds (20) since it last spoke or heard you («and tomorrow?»);
then it goes back to sleep and needs its name again. While it thinks, a tool runs
or an alarm rings, that clock doesn't run. And with `ignore_others` (on) the LLM
may stay quiet: if what it hears is clearly not for it («…thanks, Gabriela. Bye»,
the TV, a phone call) it answers `<silence>` and Jarvis says nothing; those words
don't go to its memory either. After a dubious wake-up (its name not at the
start, or in a long sentence) the first sentence goes to the LLM with that doubt.

### STT plugins

Each module in `server/stt/` is an engine. To add one:

```python
# server/stt/my_engine.py
from stt import Transcriber, register

@register("my-engine")
class MyEngine(Transcriber):
    def transcribe(self, audio):  # float32 mono 16 kHz → str
        ...
```

and use it with `--stt my-engine [--stt-model ...]`. Heavy dependencies go inside
the class, so they aren't loaded when unused.

## Wake word and conversation mode

It sleeps until it hears **«Hey Jarvis»**; then it beeps and enters
**conversation mode**: it transcribes sentence by sentence without repeating the
word, until you say the sleep command (**«go to sleep»** / **«apágate»**) or
**2 minutes** pass without talking to it; it beeps downwards when falling asleep
(the plugin `sounds`: turned off, it wakes and sleeps in silence).
Asleep, **tapping the screen** wakes it up too (the plugin `tap-to-wake`).
«Hey Jarvis, what time is it?» in one go also works: it wakes up and transcribes
the question.

By default the word is found by a small Whisper (`whisper-base`, ~140 ms),
comparing by how it sounds («Yarvis», «Harvis»…); it works for any word.
openWakeWord remains as a plugin, but with a Spanish accent it barely recognizes
«Hey Jarvis».

```
uv run server/main.py --wake-word nexus       # any word with the whisper plugin
uv run server/main.py --threshold 0.9         # stricter if it wakes up by itself
uv run server/main.py --wake openwakeword --wake-word alexa   # alexa, hey_jarvis, hey_mycroft…
uv run server/main.py --wake none             # no word: transcribes all speech
```

Other engines (Vosk, Porcupine…) are plugins in `server/wake/`:

```python
# server/wake/my_engine.py
from wake import WakeWord, register

@register("my-engine")
class MyEngine(WakeWord):
    phrase = "Hey Nexus"             # what the screen shows
    continuous = False               # True if it also needs to hear while awake
    def listen(self, audio):         # float32 mono 16 kHz, chunks of any size
        return detected              # True on the chunk where it hears the word
```

and `--wake my-engine [--wake-word …]`. `server/plugins.py` is the shared registry.

## Themes

The screen's look is a **theme**: HTML and CSS anyone can make, **without
JavaScript**. One comes with AnyAssistant (`plugins/page/themes/eyes`):

- **`eyes`** (default): two blinking eyes; closed and breathing while asleep,
  brighter and slightly bigger with your voice, looking to one side with dots while
  thinking, a mouth of bars that follows its voice, a raised eyebrow and «?» while
  waiting for your «yes», orange when ringing, drooping and red on errors.

Others are installed from the community's catalog (the window Themes → «De la comunidad»;
docs/comunidad.md): **Orb** (a sphere that breathes and sends out waves while speaking),
**Minimal** (high contrast and large text) and **Bedside** (nearly black, a dim time while
asleep, soft sounds), among them.

Chosen with `theme` for every device, `?theme=<name>` on one (remembered by it;
`?theme=default` forgets it), or by voice («ponte el tema de mesilla», «only on
this one»).

**In the apps.** The iPhone, iPad, Mac and Android apps draw **Eyes natively**; **every other
theme** (a system one or one installed from the community) is the server's own page in a web
view, so it looks as in a browser: `/?app&theme=<name>`. In that mode the page opens no WebRTC
and asks for no microphone: the app keeps the microphone, the audio, the camera, alarms and
notifications, and feeds the page through a bridge (`AnyAssistant.receive(…)`: the server's
messages as they come, the voices' levels, the app's own problems such as «looking for the
server»); the page tells the app «ready» (it then gets what is on the face already), the taps
(holding: the app's settings) and where the camera's window is (the app shows its own camera
there). The pairing's cookie goes with it, and over HTTPS only your server's authority is
trusted. If the page can't be had, the app shows Eyes.

**Making one.** `bin/anyassistant theme new mine --from eyes` copies a theme into your
folder (`themes_dir`, `themes.local/` by default: where an installed Jarvis keeps
them will come with the installer). A theme is a folder:

```
theme.json        {"name": "Mine", "author": "…", "version": "1", "description": "…",
                  "options": {"accent": "#3ddc97"}}
theme.html        the layout: where each block goes
theme.css         its styles and animations for each state
locales/es.json  optional: {"ui": {"thinking": "Mmm…"}, "theme": {"goodnight": "Buenas noches"}}
sounds/          optional: wake.wav, sleep.wav, alarm.wav (16-bit WAV); without them,
                 the plugins' own (sounds: wake, sleep; skill-alarms: alarm)
images/, fonts/  whatever it uses, inside its folder
```

`theme.html` places **blocks**, which Jarvis fills: `<div data-block="clock"></div>`.

| Block | |
|---|---|
| `face` | its face: the theme draws it inside (and gets the live variables below) |
| `status` | «Te escucho», «Pensando…», «Di Hey Jarvis» |
| `heard`, `answer`, `captions` | what you said last, its last answer, or both with `history`; each scrolls in its own area (below) |
| `clock`, `time`, `date` | the clock (both parts, or each on its own) |
| `timers` | running timers, alarms and reminders |
| `photo`, `camera` | the photo it looks at, the live camera (if the theme has no place for them, Jarvis adds its own) |
| `stats` | the connection's numbers |

`<p data-text="goodnight"></p>` shows a text of its own, from its `locales`
(`theme`), and its `ui` texts replace Jarvis's on screen (not what it says or
understands). Starting and pairing aren't blocks: they always work.

`theme.css` follows the state with:

- `body[data-state]`: the state as it comes (`asleep`, `awake`, `hearing`,
  `thinking`, `looking`, `speaking`, `question`, `alarm`, `error`…), and
  `body[data-look]`, with the ones that look alike grouped (listening → awake…).
- `body.blink`, now and then for a moment.
- On the face block, live, from 0 to 1: `--voice` (your voice), `--speech` (its
  own) and `--bar-1` … `--bar-5` (its own as five moving bars), e.g.
  `transform: scale(calc(1 + var(--voice) * .2))`.
- Its `options` as variables: `--accent`, changeable with `theme_options`.
- The words' areas (`heard`, `answer`, `captions`) scroll by themselves and follow the voice;
  the theme only gives their height: a `max-height` (30% of the screen if it says nothing), a
  fixed `height` in a centred column (so the face doesn't move when words arrive), or
  `max-height: none` in a flex column of the screen's height, so they shrink to the space left
  (Eyes). While there is more above or below they have the classes `more-above`,
  `more-below` (a fade; a theme may change it).
- The timers' lines with their kind as a class (`.timers p.timer`, `.alarm`,
  `.reminder`): Jarvis puts no icon, so a theme that wants one adds it, e.g.
  `.timers p.alarm::before { content: "⏰ "; }` (and `body[data-state=alarm] .status::before`
  while one rings). Android 4.4's font lacks some emoji (⏱).

**Seeing them**: the Mac app's «Themes…» (or `http://<mac>:8080/themes?theme=mine`) shows every state at once, with a
simulated voice and timer and a long conversation whose captions follow the voice, and reloads
when you save.

**By voice**: «crea un tema a partir del orbe y que piense en lila» — Jarvis copies
it into your folder, reads it and changes what you asked (`create_theme`,
`get_theme`, `edit_theme`), then you choose it. Only your themes: the system's ones
can be copied, never changed or deleted; it writes `theme.json`, `theme.html`,
`theme.css` and `locales/*.json` (sounds and images you add by hand).

**What a theme can't do**: run JavaScript, react to events (`onclick`…) or load
anything from outside: the page has the microphone and the camera. Its HTML is
cleaned when served and the page forbids the rest (Content-Security-Policy).

**From the community** (the plugin `community`): themes other people share, from a public catalog
(one JSON index in a GitHub repository, `community_catalog`), at the end of the Themes window
(`/themes`) and in `/admin` → Community: each with its screenshot; install, update, remove. Every
file is downloaded and checked against the catalog's SHA-256 before anything is written (whole,
into your themes folder); never over a system theme or one of yours. What was installed, and its
version, is kept in `community.json`. How to publish one: `docs/comunidad.md`.

The camera's quality: `video` in `settings.json`, or
`?video=normal|low|off` on one device.

## System voice commands

The server handles them directly, without going through the LLM (words per
language in `locales/*.json` → `commands`):

- **Sleep** («go to sleep» / «apágate», «duérmete»): back to sleep until the next «Hey Jarvis».
- **Reload** («reload the tools» / «recarga las herramientas»): reads `.mcp.json` and
  `permissions.json` again and restarts the LLM (after authorizing or
  re-authorizing an MCP server). They are also reread on every «Hey Jarvis».
- **Restart** («restart» / «reiníciate»): restarts the whole server (e.g. after
  changing the code); the tablet reconnects by itself in a few seconds.
- **Camera** («turn on the camera» / «activa la cámara», «turn off the camera» /
  «apaga la cámara»): shows the device's camera live on its screen, mirrored, where
  the face is (the same stream it already sends: no extra load); it also goes away
  when it falls asleep.
- **LLM** («use Claude», «switch to Hermes» / «usa Claude», «cambia a Hermes»):
  saved in `settings.json` and it restarts with it. Apple's model has no tools,
  so this is the way back from it.
- **Stop** while it speaks («Jarvis, stop» / «Jarvis, para»): while talking it only
  listens for its name, so it can be interrupted; «Jarvis, and tomorrow?» stops it
  and asks. Its own voice saying its name doesn't count. Tapping the screen works too.

## Plugins

Everything Jarvis does is a plugin; the core (`server/kernel.py`) only finds them,
loads them and says which are on. They live in `plugins/` (the system's) and in
your data folder (`plugins.local/` while developing): **one of yours with the same
name replaces the system's**, to customize it.

Everything comes on. To turn one off, `"plugins": {"skill-arithmetic": false}` in
`settings.json`, or by voice («desactiva las cuentas», «¿qué plugins tienes?»),
with your «yes» to turn one off. Security plugins (and the plugin manager) can
only be turned off by hand, and an engine in use only after choosing another.
Skills and tools turn on and off at once; engines when chosen. The only one off
at first is `pairing` (it was opt-in before plugins too).

A plugin is a folder:

```
plugins.local/skill-weather/
  plugin.json    {"name": "Weather", "description": "…", "kind": "skill",
                  "requires": ["…"], "security": false, "default": true}
  __init__.py    its code: what it brings registers itself (@skill, @tool,
                 @register("…") for an engine, options.add(…))
  locales/es.json  its texts, joined to the rest: what it says («speech»), its words
                 («commands», «skills»), and how it is shown in the app and the installer:
                 {"plugins": {"<id>": ["Name", "Description"]}, "options": {"<option>": "…"},
                  "installer": {"<step>": ["Title", "Help"]}} (in English, plugin.json and the
                  code say it; locales/en.json only for what the code doesn't)
```

What it needs goes in `plugin.json` too, for the installer:
`"needs": {"python": ["parakeet-mlx>=0.5.3"], "system": ["darwin"], "arch": ["arm64"],
"macos": 26, "commands": ["claude"]}`. One that doesn't fit the computer, or lacks its
packages, stays off whatever the settings say. `bin/anyassistant plugins` lists them (on,
off, and why one can't work); `bin/anyassistant plugins requirements` prints the Python
packages of those that are on.

`kind`: `brain`, `stt`, `wake`, `llm`, `tts`, `vad` (engines: the settings choose one), `library` (code and words other plugins use, declared in their `requires`),
`skill` or `feature`. Plugins import each other as `plugins.<id with underscores>`
(`from plugins.stt_mlx_whisper import transcribe_mlx`). Loading must be cheap:
heavy libraries only inside its classes.

**From the community** (the plugin `community`): plugins other people share, from the same public
catalog as the themes (`community_catalog`; `docs/comunidad.md`, reviewed before they are listed),
in the Mac's Settings → Plugins → «From the community» and in `/admin` → Community. A plugin is
code that runs here with your permissions: the app warns and asks before installing one (the
server requires that confirmation too), it goes whole into your plugins folder only when every
file matches its SHA-256, it never replaces a system plugin, and it starts off: turn it on in
Plugins after restarting. Updates and removal from the same place.

## Skills without an LLM

Time and date, timers, alarms, reminders, sums, unit conversions and volume are
handled by the server itself: at once, offline, with any LLM or none
(`server/skills/`; `"skills": false` turns them off).

- «¿Qué hora es?», «¿qué día es hoy?» / «what time is it?».
- «Pon un temporizador de 10 minutos», «avísame en media hora», «¿cuánto queda?».
- «Pon una alarma a las 7 y media», «despiértame mañana a las 7».
- «Recuérdame en 20 minutos que saque la ropa», «recuérdame mañana a las 6 que llame a mamá».
- «¿Qué alarmas tengo?», «cancela las alarmas», «cancela todos los temporizadores».
- «¿Cuánto es 23 por 47?», «el 15 por ciento de 80», «2 elevado a 10».
- «¿Cuántos kilómetros son 5 millas?», «20 grados en fahrenheit» (length, mass, volume, temperature).
- «Sube / baja el volumen», «volumen al 70» (`volume`, its voice and sounds).

The words are in the locale (`skills`: numbers said in words, «media hora», «y
cuarto», «de la tarde», units…), so another language is another file. Timers,
alarms and reminders are kept in `timers.json` (they survive a restart), shown
on screen with a countdown (`show_timers`) and ring on the device: a tone, the
face in orange, and what it is («Recordatorio: llamar a mamá»). «Para», «apaga
la alarma», «Jarvis, para» or a tap stop it; «pospón» («pospón 10 minutos»)
snoozes it (`snooze_minutes`). While it rings, only words meant to stop it count
(its own tone, transcribed, doesn't). It rings for `ring_seconds`; with no device
connected, on the Mac. With several devices it rings on every one (`alarm_rings`:
`everywhere`), or where it was set (`where_set`); «… en todos», «… en toda la casa» or
«… en la cocina» (a room or a device's name, from `devices`) for that one.
If that device isn't connected, it rings on every one; stopped on one, it stops on all.

**On its own** (the plugins `notices`, `calendar-notices`, `morning`, with `google` reading
Google through `bin/gog`, without the LLM): «Dentro de 10 minutos: dentista.», a while before
each event of your calendar (`calendar_notice_minutes`); and the morning summary when you say
«buenos días» or stop the first alarm of the day (`morning_after_alarm`): the date and the
day's holidays, the weather, what's on your calendar and how many unread emails
(`unread_query`; to hear them, ask). Notices are polite: not during `quiet_hours`
(23:00-08:00), not while someone is talking to it (it waits for a quiet moment), with a soft
tone first, on every device or on the last one you talked to (`notices_where`).
When an email arrives, in Gmail or another account (`email-notices`): «Tienes un email nuevo de Ana.» (`email_notice_says`:
who it's from, its subject too, or only how many), of the unread ones in Gmail's Primary tab
(`email_notice_query`), looked at every `email_check_minutes`.

**The interpreter**: what doesn't fit the usual ways of saying it («avísame dentro
de un rato largo, como tres cuartos de hora») can go to an LLM, which turns it into
data for the same skills. `"interpreter"`: `auto` (the default: a local model if
there is one, Apple's on a Mac with it; elsewhere nothing), `off`, or any LLM's
name (`apple`, `claude`…). And the
LLM has them as tools (`set_timer`, `set_alarm`, `set_reminder`, `list_timers`,
`cancel_timers`, `set_volume`), without asking for your «yes».

**The Mac itself** (the plugin `control-mac`, only on a Mac; the words and the matching are the
library `control-language`, which the Windows and Linux plugins will share): the computer the server
runs on, by voice and without the LLM.

- «Abre Safari», «abre la aplicación Notas», «open Chrome»: an installed app, by its name, the name
  the Finder shows («Ajustes del Sistema»), or how it sounds in your mouth: the recognizer writes
  English names as it hears them («crom», «cromo», «fotochop», «guasap»), so names are compared by
  their sounds, not their spelling. «Abre X» is only taken when an app answers to X: «abre la
  puerta» still goes to the LLM. What it doesn't understand, `app_names` teaches it:
  `{"crome": "Google Chrome", "el bicho": "Visual Studio Code"}`.
- «Ejecuta el atajo Buenas noches», «atajo Descansar», «run the shortcut Good night»: an Apple
  Shortcut by name (`shortcuts run`), started without waiting for it.
- «Abre el archivo informe septiembre», «abre la carpeta Descargas», «open the folder Dev»: in your
  home folder, by Spotlight (every word said, in the name; caches and what is inside apps don't
  count; the one nearer home wins); the standard folders by name, outright. Two with the same
  name: it says which one («Abro Dev, en Desarrollo»).
- «Ve a la ventana de Mail», «cambia a Safari», «go to the budget window», «switch to Chrome»: an
  app comes to the front, or a window by words of its title.
- «Teclea hola, ¿qué tal?», «escribe esto: nos vemos a las 8», «type hello»: typed where the cursor
  is on the Mac, as keystrokes, after your «yes» («¿Escribo «hola»?», the plugin `confirmation`:
  typing changes things). The text as it was said, with its accents and punctuation.
- «¿Qué puedo decir?», «what can I say?»: it lists all this.

The windows and typing need macOS's **Accessibility** permission for the program that runs the
server (System Settings → Privacy & Security → Accessibility): the first time it is needed, it says
so and macOS adds the program to that list. Opening apps, files and shortcuts need nothing. Not
done: reading the notifications (it would need Full Disk Access). The LLM has all of it as tools
too (`open_app`, `run_shortcut`, `open_file`, `go_to_window`, `type_text`; `list_apps`,
`list_shortcuts`): running a shortcut or typing asks for your «yes».

**Adding a skill** is adding a plugin (`plugins.local/skill-weather/`, kind `skill`):

```python
from skills import Skill, skill
from tools import tool

@skill
class Weather(Skill):
    order = 40                              # who listens first
    def answer(self, text, toks):           # what to say, or None if it isn't for it
        ...

@tool("Today's weather where the user is.")  # and, if useful, a tool for the LLM
def weather(place: str = "") -> str: ...
```

Its words go in the locales («skills»). Skills that do more than answer (the
camera, «speak English»…) implement `hear(text, jarvis)` instead.

## Phase 3 · Answers (LLM)

What you say goes to the LLM and the answer appears on screen as it is generated.
Each «Hey Jarvis» starts a new conversation, remembered until it falls asleep.

**Captions follow the voice.** The whole answer usually arrives seconds before the voice has
read it; what you said, what it answers and the captions each scroll in their own area (no
scrollbar: a finger, the wheel or the trackpad), with a fade at the edge where there is more.
What you said shows from its end; an answer, from its start, and then like a teleprompter: when
a sentence starts playing on a device, the server tells that device which one
(`{"type": "speaking", "id", "start", "end"}`: the answer's id and the sentence's characters in
its text, in UTF-16 as JavaScript and Kotlin count them). The server knows when: each speaker's
`play()` returns when that audio starts, after what it already queued (the page's WebRTC track,
the apps' WebSocket), and the message is sent at that moment; nothing if it was stopped
meanwhile. Scrolled by hand, it stops following until you scroll back to the end or new words
arrive. A tap still stops it (`tap_to_stop`); a drag that scrolls isn't a tap.

There are three plugins:

- **`claude`** (default): Claude through Claude Code's `claude` CLI, with your
  session and subscription, no API key. Each conversation is a `claude -p` process
  in stream-json mode, without Claude Code's own tools or CLAUDE.md, so it starts
  fast. Sonnet by default; `--llm-model haiku` uses less quota. First word in ~0.6 s.
- **`apple`**: the model that comes with macOS (Foundation Models, local, no keys;
  macOS 26+ with Apple Intelligence). It is a Swift-only API: the plugin builds
  `server/llm/apple_bridge.swift` the first time into `.build/` and talks to it
  over stdin/stdout. It gets the time as a tool (`dateTime`): given in the prompt,
  it repeated it in every answer. Faster (~0.5 s) but weaker (~3B).
- **`hermes`**: [Hermes Agent](https://hermes-agent.nousresearch.com) through its
  OpenAI-compatible API (`hermes gateway`, `127.0.0.1:8642`, key `API_SERVER_KEY`
  from `~/.hermes/.env`). It uses its own tools, memory and credentials, with
  whatever model it has configured; each conversation is one of its sessions
  (`X-Hermes-Session-Id`). `permissions.json` doesn't apply to it. When Hermes asks
  to approve something (`approval.request`), Jarvis asks by voice and answers `once`
  or `deny`; but with `approvals.mode: smart` (its default) an auxiliary model
  decides the clear cases by itself, and only the doubtful ones reach Jarvis.

```
uv run server/main.py --llm-model haiku   # Claude Haiku
uv run server/main.py --llm apple         # Apple's model, local
uv run server/main.py --llm hermes        # Hermes Agent
```

### Tools: only the project's, and only what you allow

With the `claude` plugin, Jarvis can use **MCP servers from the project folder**
and **project commands**, never your claude.ai account's connectors nor other
terminal commands. Everything is decided in **`permissions.json`** (outside git;
see `permissions.example.json`):

```json
{
  "allowed": { "holded": "all" },
  "commands": { "bin/gog": "all" },
  "confirm": true
}
```

- `allowed`: tools of each **`.mcp.json`** server (`"all"` or a list); a server that
  isn't listed is denied entirely.
- `commands`: programs it may run, with their policy (read by the command itself).
  Claude gets Claude Code's terminal **limited to them** (anything else is denied:
  tested with `ls`, `curl` and `touch`) and, in the prompt, what `<command> help` shows.
- `confirm` (on by default): **actions that write need your «yes» by voice**. A
  Claude Code hook (`bin/anyassistant-confirm`) stops any `bin/gog` call that isn't a
  read and any MCP tool that isn't `get_`/`list_`/`search_`…, and Claude asks you.
  If you say «yes» (or «sure», «go ahead»…; «yes, but…» doesn't count), the server
  authorizes **that same call**, once and for one minute; any other answer cancels
  it. Claude can't get around it: it can't write files or run anything else.
  It is the plugin `confirmation` (a security one: only turned off by hand, with
  `"plugins": {"confirmation": false}`; then nothing asks, for any LLM).

Without `permissions.json` it uses nothing. When it uses a tool it says «One
moment, let me check».

#### Holded (MCP)

In `.mcp.json` (see `.mcp.example.json`); authenticated in the project folder:
`claude` → approve the servers → `/mcp` → *Authenticate*. Read-only is chosen when
authorizing it in Holded. Its automatic client registration fails in Claude Code
(it returns `"software_id": null`), so a client is registered by hand and its
`clientId` goes in `.mcp.json` (callback port 8766):

```
curl -X POST https://app.holded.com/api/v2/mcp/oauth/register -H "Content-Type: application/json" \
  -d '{"client_name":"Jarvis","redirect_uris":["http://localhost:8766/callback"],
       "grant_types":["authorization_code","refresh_token"],"response_types":["code"],
       "token_endpoint_auth_method":"none"}'
```

#### Other mail accounts: IMAP and SMTP (the plugin `mail`)

For accounts that aren't Gmail (iCloud, Outlook, your domain's…):

```sh
bin/anyassistant mail add you@domain.com [--name Trabajo] [--imap host[:port]] [--smtp host[:port]]
bin/anyassistant mail list | test | remove <name>
```

Or in the Mac app: Settings → Mail accounts, where you can also import the Mac's own (System
Settings → Internet Accounts: their servers; their passwords you type, macOS keeps them to
itself; it needs Full Disk Access). `add` guesses the servers of the known providers, asks for the password (an app password
where the provider has them), tries IMAP and SMTP with it, and keeps it in the macOS Keychain
(never in `settings.json`; the account goes to `mail_accounts`). Then new emails get a notice
(`email-notices`), the morning summary counts them, and the LLM can list them (`list_mail`),
read one (`read_mail`; nothing is marked read) and send (`send_mail`, with your «yes»; a copy
goes to its Sent folder).

#### Gmail, Calendar, Drive, Docs and Sheets (`bin/gog`)

With [gog](https://gogcli.sh) (`brew install openclaw/tap/gogcli`). `bin/gog` always
runs it with the `jarvis` client (its own token store), the configuration in `.gog/`
inside the project and `--no-input`, and refuses attempts to change those options.
Its policy, in `permissions.json`:

- `"read"`: `--readonly`, `--gmail-no-send` and read commands only; the
  authorization asks Google for read-only permissions.
- `"all"`: it can write (always with the voice confirmation), except managing gog's
  session, backups, administration and self-updating.
- a list of commands (`["gmail.search", "calendar.create"]`).

To set it up:

1. In Google Cloud, enable **Gmail API**, **Google Calendar API**, **Google Drive API**,
   **Google Docs API** and **Google Sheets API**.
2. In *Google Auth Platform*, your email as a test user.
3. Download the OAuth client's JSON (*Desktop app*) as `google-client.json` in the
   project's root.
4. `bin/gog-authorize you@gmail.com` (opens the browser): asks for the permissions
   matching the policy; after changing it, authorize again.

In *Testing* mode Google expires the authorization every 7 days; to avoid it,
publish the app in *Google Auth Platform → Audience* (for your own use Google
doesn't need to verify it: an «unverified app» warning shows and you continue).

Google's official MCP servers (`gmailmcp`/`drivemcp.googleapis.com`) were tried and
dropped: they require the *Google Workspace Developer Preview Program*, closed to
personal accounts.

Other LLMs are plugins in `server/llm/`:

```python
# server/llm/my_llm.py
from llm import LLM, instructions, register

@register("my-llm")
class MyLLM(LLM):
    async def new(self): ...            # new conversation
    async def answer(self, text):       # pieces of the answer as they arrive
        yield "Hello"
    async def close(self): ...          # optional, when the server stops
```

and `--llm my-llm [--llm-model …]`.

## Eyes (Phase 4)

With the plugin `eyes` (off by default: `"plugins": {"eyes": true}`), Jarvis sees through the device's camera (with Claude, or
Hermes when asked with those words):

- A question with words like «see», «look», «read» («¿qué ves?», «léeme esto»;
  locale `commands.look`) carries the camera's image at that moment (~1.5 s).
- For the rest («what number is on this paper?») Claude may open the image of the
  moment of the question with its Read tool (~4 s), and only that file:
  `.build/eyes/now.jpg`. Any other file is denied.

- To **read** («read this», «¿qué pone aquí?»; locale `commands.read`) the video is
  too small on some devices, so the device takes a **full-resolution photo**
  (ImageCapture at its maximum size; or the camera at its largest for a moment;
  or, at worst, a video frame), resized to 1568 px for the LLM. The tablet: a
  1200×1600 photo instead of 240×320 video. If it doesn't arrive in 4 s, the
  video frame is used.

While it looks the screen shows the photo with a scanning sweep. Nothing leaves
the Mac unless it looks, and only the latest image is kept.

## Voice (TTS)

Each sentence of the answer is synthesized as soon as it is complete and plays
while the next one arrives. Tapping the screen stops it. The volume is normalized
to the maximum.

So it doesn't hear itself: while speaking it doesn't listen, nor for `--echo-guard`
seconds afterwards (1.2 by default: its voice takes time to reach the tablet, play
and come back through the microphone). And if what it hears in the following
seconds is still a short piece of what it just said («Anything else?» after «Do you
need anything else?»), it drops it.

**Interrupting it without its name** (`listen_while_speaking`, on; off, it only stops when
called by its name): it keeps listening while it speaks. The server knows exactly what it sends to each
device and when, so it keeps the loudness envelope of its last 12 seconds of output per device
(`server/echo.py`: log-RMS every 20 ms) and, when a sentence ends while it was talking, compares
the sentence's envelope with that output, searching the playback delay (up to a second and a half): its own
echo, however quiet after the device's echo cancellation, matches (above `echo_match`, 0.8) and is
dropped; a person talking over it doesn't match: clearly unlike its output (below 0.5), it stops at once, before transcribing; in between, what was said decides (its own words are its echo), and it stops and answers them. The other devices'
output counts too (two in one room), and a sound of its own starting (a chime) can't start a
sentence. With synthesized voices the echo scores 0.91 or more and a person over it 0.56 or less
(`tests/test_own_voice.py`).

**Paused while another app uses the microphone** (`pause_when_microphone_busy`, on): a call or a
meeting on the device isn't transcribed. The iPhone and iPad app is interrupted by iOS and says
so (a call, by CallKit; else «another app»); the Android app is silenced by the system (Android 10
or later) and says so (and, failing that, the server notices the exact zeros it receives); the Mac
app asks CoreAudio which other app records (Apple's own daemons don't count) and names it; on
Windows and Linux the server looks for the app of this computer (the plugin `microphone-busy`:
Windows' microphone consent store, PipeWire or PulseAudio), and the Windows and Linux app looks by
itself when it is a client of another computer's server (the same checks, `apps/desktop/microphone.js`)
and tells that server, as the Mac app does. The face shows «En pausa: Zoom usa el
micrófono» (drawn as asleep), its name doesn't wake it, the follow-up clock stops, and it listens
again when the other app lets go. A page in a browser can't know this by itself.

The voice engines (`tts`; each computer starts with the first it has, in this order):

| Engine | Where | Voices | |
|---|---|---|---|
| **`avspeech`** | Mac | the Mac's (`say -v '?'`): Mónica in Spanish, Samantha in English | AVSpeechSynthesizer in a Swift bridge that keeps the voice loaded, ~50 ms per sentence; with the enhanced version of a voice downloaded (System Settings → Accessibility → Spoken Content), it uses it |
| `kokoro` | Windows, Linux | ef_dora (Dora), em_alex, em_santa in Spanish; af_heart, af_bella, am_michael, bf_emma, bm_george… in English; also French, Italian, Portuguese, Hindi, Japanese and Chinese | Kokoro-82M in ONNX on the CPU, the most natural; its model (88 MB) and voices (27 MB) download once |
| `piper` | Raspberry Pi (Linux ARM; the default on ARM), Linux, Windows | es_ES-davefx-medium (Davefx), es_ES-carlfm-x_low, es_MX-claude-high, es_MX-ald-medium, es_AR-daniela-high in Spanish; en_US-lessac-medium (Lessac), en_US-amy-medium, en_US-ryan-medium, en_GB-alba-medium, en_GB-alan-medium in English | Piper (VITS in ONNX) on the CPU: lighter and faster than Kokoro (~60 ms per sentence on a Mac); each voice is its own model (~63 MB; carlfm, 28 MB), downloaded the first time it speaks, pinned in `server/models.py` |
| `macos` | Mac | the Mac's | `say`, ~600 ms per sentence (it starts every time) |

Each language has its engine's default voice (the first above). **Another voice**: by voice
(«usa otra voz», «pon la voz de Dora»: the LLM's `set_voice`, with your «yes», among the engine
in use's voices in this language: by what it is called, «Dora», or its name, «ef_dora»), in
Settings → Voice → «Choose a voice» (the Mac app and `/admin`: the same list), or `voice` in
`settings.json` (one per language: `{"es": "ef_dora", "en": "af_heart"}`). A voice another
engine doesn't have (the Mac's «Mónica» with Kokoro) gets that engine's default. It applies after
restarting.

Other engines are plugins with `synthesize(text)` → int16 mono at 48 kHz, and `voices(language)`
and `label(name)` to list and name their voices (`server/tts/`).

```
uv run server/main.py --voice Eddy --rate 200   # another voice, faster
uv run server/main.py --tts macos               # with `say`
uv run server/main.py --tts piper               # Piper (Windows and Linux)
uv run server/main.py --tts none                # text only
```

## Tests

```sh
uv run pytest            # fast ones (~1 s): languages, voice commands, permissions, gog, confirmation, echo
uv run pytest -m e2e     # end to end (~1–2 min): starts the real server and talks to it over WebRTC
uv run pytest -m corpus  # the audio corpus against its baseline (slow; bin/anyassistant corpus fetch first)
```

The end-to-end tests make their voices with `say` and use Apple's local model,
so they need no account or network; they run on a free port, next to a running Jarvis.

**The audio corpus** (`tests/corpus`, `docs/corpus.md`): some 480 cases from public datasets (Common
Voice, FLEURS, Multilingual LibriSpeech; MUSAN and DEMAND noises, OpenSLR room impulse responses),
never anyone's own voice, run through the ear and the speech engines offline: the WER per engine,
sentence ends per `silence`, false starts in noise, and who is speaking at `voice_match`, against
`tests/corpus/baseline.json`. `bin/anyassistant corpus fetch` downloads exactly that selection into
the cache (hashes checked; the audio isn't in git), `corpus run` measures and compares,
`corpus baseline` writes a new baseline on purpose.

## Layout

- `server/main.py` — options, plugins and running it; `server/web.py`, HTTP (the page, `/config`, `/offer`,
  and the hooks plugins use: routes, guards, `/config`, startup tasks); `server/hub.py`, the device connected now;
  `server/events.py`, what happens (`tap`, `asleep`), for the plugins that care.
- `server/i18n.py` and `locales/` — languages; `server/settings.py`, `settings.json`.
- `server/transport.py` — WebRTC session: tracks, `control` DataChannel, last frame.
- `server/audio.py` — 48 kHz mono PCM; `Speaker` is the outgoing track.
- `server/brain/` — `parrot.py` (Phase 1), `ear.py` (VAD + STT), `transcriber.py` (Phase 2), `assistant.py` (Phase 3).
- `server/kernel.py`, `server/registry.py` — the core: plugins found, loaded, on or off; engines' registry.
- `plugins/` — every plugin: engines (`stt-*`, `wake-*`, `llm-*`, `tts-*`, `vad-*`), skills (`skill-*`),
  `tools-system`, `plugin-manager`, and features: `pairing`, `confirmation` (the «yes»), `memory`, `eyes`,
  `sounds`, `tap-to-wake`, `monitor` (`/monitor`), `themes` (`/themes`: every state of a theme, and its sounds to hear, the theme's or the system's), `mcp-server` (`/mcp`),
  `community` (the public catalog of themes and plugins: `docs/comunidad.md`)…
  `server/stt/`, `wake/`, `llm/`, `tts/`, `vad/` keep only what each kind is.
- `server/text.py`, text utilities;
  `server/swift.py`, builds the plugins' Swift bridges.
- `bin/anyassistant` — starts and stops the server.
- `bin/gog`, `bin/gog-authorize` — Google (gog) for Jarvis under its policy, and its authorization.
- `server/tools/` — Jarvis's own tools (`@tool`, next to what each does); `plugins/mcp-server` serves them as `jarvis`.
- `server/skills/` — what a skill is (`@skill`) and how a sentence reaches it (`tokens.py`).
  What skills share (numbers, durations, times and days, how lists are said, with their
  words in each language) is the library plugin `skills-language`; skills declare it in
  `requires`. The core's `locales/` keep only what the core itself says: each language's
  name, voice and calendar, and its own options and installer steps.
- `server/paths.py`, `server/options.py` — where things live, every option.
- `bin/anyassistant-confirm` — hook that asks for your «yes» before any action that writes.
- `plugins/page/` — the device's page: `web/` (plain JS, old Chrome: `app.js`, connection and blocks;
  `theme.js`, applies a theme, its states and live variables; `system.css`), its texts (`locales/`, «ui»),
  `themes/` (the system's) and `themes.py` (finds, cleans and checks them).
- `tests/` — pytest; `test_e2e.py` drives the real server; `corpus/`, the audio corpus (`docs/corpus.md`).

See `TODO.md` for what's next.

## License

MIT: see [LICENSE](LICENSE).
