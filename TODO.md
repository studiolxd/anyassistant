# TODO

## Next

- [ ] **The Android app**: no Chrome flag; finds the server with Bonjour
  (`_anyassistant._tcp`) and pairs with the Mac app's QR. Check first whether it can
  reach the old tablet (Android 4.4) or that one keeps the page in Chrome.
- [ ] **AnyAssistant for the Mac, next**: its design and icon; the client role (talk to it
  from the Mac itself; connect to another Mac's server, found with Bonjour); proper
  settings fields for options that are lists or JSON (today a text field).
- [ ] **Installer, next**: a release tarball (install.sh copies the git checkout, or the
  app's copy); the voice enrolment step (`@installer.device`) when that plugin exists.

## Apps and devices

- [ ] **More than one device** (hub.py: «one at a time»): the device that heard you
  answers; an alarm rings where it was set, or everywhere; talking room to room
  («dile a la cocina que bajo ya»).
- [ ] **HTTPS served locally?** (a local certificate the device trusts): would remove
  Chrome's flag for the page; less urgent with the native apps.

## Skins

- [ ] **A better skin check**: today `skin check` tests for the old tablet's Chrome 81
  in particular. Check against the browsers/devices we support (a target list,
  e.g. «Chrome ≥ 81, Android WebView ≥ …»), or drop it.
- [ ] **The lab as the official skin preview** (a plugin, or part of the page): see and
  edit skins, not only preview them. Its design comes later.

## Who is speaking

- [ ] **Speaker identification** (a voice print, e.g. ECAPA embeddings): the «yes»
  that confirms writing actions (an email, Holded with gog on "all") may come from
  anyone, a guest, a child or the TV; ignore_others helps, but the LLM decides, it
  isn't a barrier. Require a known voice for those «yes». Memory too: «facts only
  from what the user says», but which user? In a house of several, everyone's facts
  mix. Enrolment: the installer's step done on the device (`@installer.device`).

## Taking the initiative

- [ ] **Proactive**: it only reacts (but alarms and reminders). With Calendar and Gmail:
  «you have a meeting in 10 minutes», a summary when you wake up, an important
  email. Needs a scheduler that checks those sources and a polite way to interrupt:
  not if there are people talking, not at night.

## Home and media

- [ ] **Home Assistant / HomeKit**: lights, blinds, climate (the first thing asked of a
  home voice assistant).
- [ ] **Music, radio, podcasts**: it only plays its voice and sounds; control Spotify or
  Apple Music on the Mac.

## Conversation quality

- [ ] **Interrupting it without its name**: while it speaks it doesn't listen (echo), so
  only «Jarvis, stop» or a tap work. Needs better echo cancellation than the
  tablet's; what would most make it feel like a conversation, and the hardest.
- [ ] **Wake word**: keep watching false positives and negatives (31 Oct: 28 wake-ups,
  one false, fixed; no misses found). A name in the user's language comes with the
  app's new name (`name`).

## Maintenance

- [ ] **Swift bridges on macOS 27**: `LanguageModelSession.GenerationError` is deprecated
  (apple_bridge.swift); AVSpeech's synthesizer warns about the main actor. The Mac
  app builds in Swift 5 language mode (Swift 6's strict concurrency: to do).
- [ ] **A flaky end-to-end test**: once, the wake word heard nothing in 35 s with the
  synthetic voice (test_memory_with_claude); passed when repeated.

## Done

- [x] **Each plugin brings its own texts** (31 Oct): its name, description, options,
  installer steps, what it says and its words, in its `locales/`; the core keeps
  only its own and what is shared. A test checks each plugin's Spanish has its English.
- [x] **Lists and notes** (`skill-lists`): «añade leche a la lista de la compra», any list,
  «toma nota de que…»; `lists.json`; also as the LLM's tools.
- [x] **The weather** (`skill-weather`): «¿qué tiempo hace?», «¿va a llover mañana?», «el
  tiempo en Málaga», from Open-Meteo (free, no account); your city in `location`.
- [x] **Plan B** (`llm-fallback`): when the LLM can't answer (no network, a usage limit,
  signed out) Apple's local model does, saying so; LLMs raise `llm.Unavailable`.
- [x] **Always on** (`always-on`, off by default): it doesn't fall asleep by itself.
- [x] **Alarms until stopped**: `ring_seconds` 0 rings until someone stops it (at most 30 min).
- [x] **AnyAssistant for the Mac** (31 Oct): a menu bar app that installs (with what
  comes, or step by step) and runs the server (with its Local Network permission; the
  server follows the app), pairs devices (QR + code), settings and plugins (kept up to
  date: they change by voice too), in English and Spanish (Localizable.strings; the
  server's texts translated too). Signed with Studio LXD's Developer ID:
  `apps/mac/build.sh` while developing, `--release` notarized to share it.
- [x] **Bonjour** (`bonjour`): the server announces itself as `_anyassistant._tcp`.
- [x] **admin**: settings and plugins for the app (`/admin/…`, only from the Mac).
- [x] **The page retries for real**: a watchdog restarts a connection attempt that hangs.
- [x] **update and uninstall**: `bin/anyassistant update` (never to an older version
  unless `--force`) and `uninstall` (your data only if you say so). Terminal and app
  together: start/stop defer to the app when it runs the server.
- [x] **The app is AnyAssistant** (`bin/anyassistant`, `ANYASSISTANT_HOME`…, the MCP
  server `anyassistant`, in Hermes's config too); the assistant is still Jarvis by default.
- [x] **Installer (terminal)**: install.sh + `bin/anyassistant setup`, steps from the core and
  the plugins (questions, tasks, tasks on the device), launchd; tried in a clean folder.
- [x] **Everything is a plugin** (31 Oct): the core only finds, loads and joins them
  (kernel, web hooks, events, kinds). Pairing, confirmation, memory, eyes, the page
  and skins, sounds, tap to wake, monitor, lab, MCP server, interpreter, the brains,
  «go to sleep» and «stop»… each a plugin, with what it needs in plugin.json.
- [x] **Skins**: the screen as HTML + CSS anyone can make (blocks, states, live variables,
  options, texts, sounds); eyes, orb, minimal and bedside; a lab and a checker.
- [x] **Not every sentence is for it**: a `follow_up` window (20 s) instead of 2 minutes
  listening, and `ignore_others`: the LLM answers `<silence>` to what isn't for it.
- [x] **Hermes with the assistant's tools**: the MCP server in Hermes's config; the «yes» is
  asked by the server itself, so it holds for Hermes too.
- [x] **Skills without an LLM**: time, date, timers, alarms, reminders, sums, units and
  volume; Apple's model as an optional interpreter; also as the LLM's tools.
- [x] **Eyes, second step**: a full-resolution photo to read (1200×1600 on the tablet);
  Hermes sees too (asked with «look», «read»…).
- [x] **Memory, more**: compacted by the LLM beyond 50 facts; reviewed by Apple's model
  too (it misses some new facts; Claude doesn't); corrections update the fact.
- [x] **Choosing the LLM**: `get_llms`/`set_llm` and «use Claude» / «cambia a Hermes».
- [x] **Memory**: the plugin `memory`, `"memory": "explicit"|"auto"`; `memory.json`, a review
  of each conversation when it falls asleep (auto).
- [x] **Eyes**: the plugin `eyes`; with Claude, by words («what do you see?», «read this») or
  by its own decision (Read on the image of the moment).
- [x] **Pairing** (the plugin `pairing`; `bin/anyassistant pair|unpair`, the app's QR).
- [x] **Interrupt by voice**: «Jarvis, stop» or «Jarvis, and tomorrow?» while it speaks.
- [x] **Latency**: a spare Claude process always ready (~1.5 s to the first word
  instead of 2.5–3). The model stays a setting (`llm_model`).
- [x] **Recordings**: the old debugging ones deleted; `record` only on request.
  Transcripts in the log only with `log_transcripts`.
- [x] **Languages**: English base and Spanish in `locales/`; `language` or by voice.
- [x] **Settings**: `settings.json`; face, voice, name, language also by voice with your «yes».
- [x] **Its own tools (MCP)**: the server is an MCP server (settings, memory, camera,
  reload, restart), used by Claude and Hermes.
- [x] **Automated tests**: pytest in `tests/` (`uv run pytest`; `-m e2e` for the real server).

## Postponed

- **Native apps for iOS, Android TV, Windows** (Android first, above; the Mac's client role
  with the Mac app).
- **Bilingual at once**: answer in the language each sentence is spoken in; when
  everything else works.

The Mac's fixed IP matters less now (Bonjour, the app's QR); publishing the Google app
is up to whoever installs it (see the README).
