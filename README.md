# Jarvis

An old phone or tablet becomes the eyes, mouth and ears of a voice assistant;
all the processing runs on the Mac. WebRTC transport (Opus + Chrome's echo
cancellation) over Wi-Fi.

## Phase 0 · Preparing the phone

1. A ROM with Android 7.1 or later and an up-to-date Chrome (a Lenovo tablet with
   Android 4.4 and Chrome 81 also works).
2. A fixed IP for the Mac (currently `192.168.1.137`): in macOS, Wi-Fi → network
   Details → *Private Wi-Fi address* set to **Fixed** (with *Rotating* the IP changes),
   or better, a DHCP reservation on the router. The phone on the 5 GHz network if there is one.
3. In the phone's Chrome: `chrome://flags` → *Insecure origins treated as secure* →
   `http://192.168.1.137:8080` → *Enabled* → Relaunch.
4. Settings → Battery → optimization: Chrome *not optimized*.

## Running it

```
bin/jarvis start [options]   # in the background; e.g. bin/jarvis start --llm hermes
bin/jarvis stop
bin/jarvis restart           # like saying «restart»: same options
bin/jarvis status
bin/jarvis log               # live log (.build/jarvis.log)
```

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
the preferences, so `bin/jarvis start` needs no options:

```json
{
  "language": "es",
  "name": "Jarvis",
  "instructions": ["I'm a freelance designer.", "I invoice with Holded."],
  "voice": {"es": "Mónica", "en": "Samantha"},
  "face": "eyes",
  "video": "auto"
}
```

Keys are the server's options with underscores instead of dashes; options on the
command line win over it (`uv run server/main.py --help` lists them all). Besides
the plugins' (`llm`, `llm_model`, `stt`, `tts`, `voice`, `wake`…) and the ear's
(`silence`, `idle_timeout`, `echo_guard`):

| Key | Default | |
|---|---|---|
| `language` | the Mac's | `en`, `es`… (also by voice) |
| `name` | `Jarvis` | the assistant's name: wake word («Hey …»), page title, the LLM's instructions |
| `instructions` | — | text (or a list of lines) added to the LLM's instructions: who you are, your tools, how to talk |
| `voice` | the language's | one voice or one per language: `{"es": "Mónica", "en": "Samantha"}` |
| `face` | `eyes` | `eyes` or `orb`; a device's `?face=` wins |
| `video` | `auto` | `normal`, `low` or `off`; `auto` lets each device choose (low with ≤ 1 GB of RAM); a device's `?video=` wins |
| `port` | `8080` | `bin/jarvis` uses it too |
| `memory` | `off` | remember across conversations: `explicit` (only when asked) or `auto` (below) |
| `eyes` | `false` | it may look through the device's camera, with Claude (below) |
| `pairing` | `false` | only devices paired with a code may connect (below) |
| `log_transcripts` | `false` | write what it hears and says to the log (to debug); otherwise only lengths |
| `confirm_wait` | `120` | seconds to answer «yes» to an action that writes |
| `confirm_valid` | `60` | seconds a «yes» stays valid |

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

**The screen**: `show_time`, `show_date` and `show_hint` («Say Hey Jarvis») while
asleep; `show_status` («Listening», «Thinking…»), `show_heard` (what you said),
`show_answer` (its answer) and `history` (earlier sentences kept, 2) while awake;
`show_stats` (the connection's RTT, jitter and losses; off) and `clock` (`auto`,
`12`, `24`). **Sounds and behavior**: `beeps` (on waking up and falling asleep),
`fillers` («One moment, let me check» when a tool is slow), `voice_interrupt`
(«Jarvis, stop»), `tap_to_stop`, `read_photo` (a full-resolution photo to read).
**Memory**: `memory_facts` (50, then compacted), `memory_conversations` (10),
`memory_days` (30). All apply without restarting: the page changes at once.

A wrong value (`"face": "smiley"`) stops the server with the reason.

**Pairing**: with `"pairing": true`, a device must enter a code before using
Jarvis. `bin/jarvis pair` shows one on the Mac (6 digits, 5 minutes, one device);
the page asks for it and the device remembers it (a cookie; the server keeps only
its hash in `.build/paired.json`). Unpaired devices can't connect, see the camera
(`/video.mjpg`) or the status; the Mac itself always can. `bin/jarvis unpair`
forgets them all.

**By voice**: «Use the orb face», «Change your voice to Mónica», «From now on your
name is …», with Jarvis's own tools (below). After every answer the server reads
`settings.json` again (also when you edit it by hand): the face changes on the
screen at once, and anything else (voice, name, language…) restarts it when it
finishes speaking. Options given on the command line don't change.

## Its own tools (MCP)

The server is also an MCP server, `jarvis`, at `/mcp` (only from the Mac itself:
no device on the network, paired or not). Allowed like any other in
`permissions.json` (`"allowed": {"jarvis": "all"}`, or a list of tools), Claude
can manage Jarvis in your own words («show me what you see», «use the round
face», «what do you know about me?»):

| Tool | | Your «yes» |
|---|---|---|
| `get_status`, `get_settings`, `get_memory` | device and camera, language, LLM, eyes, memory; name, face, voice; what it remembers | no |
| `set_face`, `set_voice`, `set_name`, `set_language` | saved to `settings.json`, applied after the answer | yes |
| `remember`, `forget` | memory facts | yes |
| `camera` | shows or hides the live camera on the screen | no: it only changes the screen |
| `set_detail` | how much it says: concise, neutral, detailed or your own levels | no: it only changes how it talks |
| `add_detail_level`, `remove_detail_level` | create, change or remove a detail level | yes: its text goes into the prompt |
| `get_llms`, `set_llm` | the LLMs it can use (and whether each is available); switch to another, with a model | `set_llm`: yes |
| `reload_tools`, `restart` | after the answer, so the LLM isn't cut off while using it | yes |

Tools that change something ask for your «yes» themselves (the server, not the
LLM), so it holds for any LLM: with Claude, Hermes or another MCP client.

**With Hermes**: add it to Hermes's MCP servers and restart its gateway:

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  jarvis:
    url: http://127.0.0.1:8080/mcp
```

(`hermes mcp add jarvis --url http://127.0.0.1:8080/mcp` does the same, asking in
the terminal which tools to enable; then `hermes gateway restart`.)

Nothing to lift its own safeguards: no tool touches the permissions, the
confirmation times, the port or your `instructions`; the LLM only among the
installed ones and with your «yes». The fixed voice
commands («activa la cámara», «para», «habla en inglés»…) stay: they need no LLM,
so they answer at once; the tools are for everything else.

## Memory

`"memory"` in `settings.json`: `off` (default), `explicit` or `auto`. It lives in
`memory.json` (not in git), readable and editable:

```json
{"facts": ["Has a dog called Toby."], "conversations": [{"at": 1793439182, "summary": "…"}]}
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
sooner but may cut you off if you pause; `--idle-timeout` (120 s) is how long it
takes to fall asleep if you don't talk to it.

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
**2 minutes** pass without talking to it; it beeps downwards when falling asleep.
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

## Face

Two, chosen with `face` in `settings.json` or, on one device, in its address
(which wins):

- **`?face=eyes`** (default): two blinking eyes; closed and breathing while asleep,
  brighter and slightly bigger with your voice, looking to one side with dots while
  thinking, with a mouth of bars that follows its voice while speaking, a raised
  eyebrow and «?» while waiting for your «yes», drooping and red on errors.
- **`?face=orb`**: a sphere that breathes, beats with your voice, has a spinning
  ring while thinking and sends out waves while speaking.

Asleep, the screen shows the time and date in large type. `?demo` (or
`?demo&face=orb`) cycles through every state without connecting, to look at them.
It is all CSS and transforms (`web/faces.css`, `web/face.js`), so it runs smoothly
on the tablet. The camera's quality: `video` in `settings.json`, or
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
connected, on the Mac.

**The interpreter**: what doesn't fit the usual ways of saying it («avísame dentro
de un rato largo, como tres cuartos de hora») can go to Apple's local model, which
turns it into data for the same skills. `"interpreter"`: `auto` (the default:
only if this Mac has Apple's model; elsewhere nothing), `apple` or `off`. And the
LLM has them as tools (`set_timer`, `set_alarm`, `set_reminder`, `list_timers`,
`cancel_timers`, `set_volume`), without asking for your «yes».

## Phase 3 · Answers (LLM)

What you say goes to the LLM and the answer appears on screen as it is generated.
Each «Hey Jarvis» starts a new conversation, remembered until it falls asleep.

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
  Claude Code hook (`bin/jarvis-confirm`) stops any `bin/gog` call that isn't a
  read and any MCP tool that isn't `get_`/`list_`/`search_`…, and Claude asks you.
  If you say «yes» (or «sure», «go ahead»…; «yes, but…» doesn't count), the server
  authorizes **that same call**, once and for one minute; any other answer cancels
  it. Claude can't get around it: it can't write files or run anything else.

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

With `"eyes": true`, Jarvis sees through the device's camera (with Claude, or
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

Two plugins with macOS voices (the language's voice by default: Samantha in
English, Mónica in Spanish; `say -v '?'` lists them):

- **`avspeech`** (default): AVSpeechSynthesizer in a Swift bridge that keeps the
  voice loaded, ~50 ms per sentence. If you download the enhanced version of a voice
  (System Settings → Accessibility → Spoken Content), it uses it.
- `macos`: `say`, ~600 ms per sentence (it starts every time).

Other engines are plugins in `server/tts/` with `synthesize(text)` → int16 mono at
48 kHz.

```
uv run server/main.py --voice Eddy --rate 200   # another voice, faster
uv run server/main.py --tts macos               # with `say`
uv run server/main.py --tts none                # text only
```

## Tests

```sh
uv run pytest            # fast ones (~1 s): languages, voice commands, permissions, gog, confirmation, echo
uv run pytest -m e2e     # end to end (~1–2 min): starts the real server and talks to it over WebRTC
```

The end-to-end tests make their voices with `say` and use Apple's local model,
so they need no account or network; they run on a free port, next to a running Jarvis.

## Layout

- `server/main.py` — HTTP, signaling (`/offer`), texts and settings for the page (`/config`), monitor (`/video.mjpg`, `/status`).
- `server/i18n.py` and `locales/` — languages; `server/settings.py`, `settings.json`.
- `server/transport.py` — WebRTC session: tracks, `control` DataChannel, last frame.
- `server/audio.py` — 48 kHz mono PCM; `Speaker` is the outgoing track.
- `server/brain/` — `parrot.py` (Phase 1), `ear.py` (VAD + STT), `transcriber.py` (Phase 2), `assistant.py` (Phase 3).
- `server/stt/`, `server/wake/`, `server/llm/`, `server/tts/` — plugins; `llm/permissions.py`, which MCP servers and commands Claude may use.
- `server/plugins.py` — shared plugin registry; `server/text.py`, text utilities;
  `server/swift.py`, builds the plugins' Swift bridges.
- `bin/jarvis` — starts and stops the server.
- `bin/gog`, `bin/gog-authorize` — Google (gog) for Jarvis under its policy, and its authorization.
- `server/tools.py`, `server/mcp_server.py` — Jarvis's own tools, as the `jarvis` MCP server.
- `server/memory.py` — memory across conversations (`memory.json`).
- `server/skills/` — skills without an LLM: `parse.py` (numbers, durations, clock times), `calc.py`,
  `units.py`, `timers.py` (`timers.json`), `interpreter.py` (Apple's model).
- `bin/jarvis-confirm` — hook that asks for your «yes» before any action that writes.
- `web/` — the phone's page (plain JS, old Chrome) and the monitor.
- `tests/` — pytest; `test_e2e.py` drives the real server.

See `TODO.md` for what's next.
