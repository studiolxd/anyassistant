# TODO

## Next

- [ ] **AnyAssistant, the Mac app**: a menu bar app (SwiftUI, .dmg) on top of
  `bin/anyassistant setup --list/--json`: «install with what comes» or step by step,
  settings, plugins, pairing (QR + code), log, update. Signing and notarizing.
- [ ] **macOS Local Network permission**: started by launchd (no app), the server
  can't reach the tablet (WebRTC stays «connecting»); from a terminal it can. The
  AnyAssistant app should start it, so it inherits the app's permission
  (NSLocalNetworkUsageDescription), or the installer must guide the user to allow it.
- [ ] **Installer, next**: a release tarball
  (install.sh copies the git checkout for now); the voice enrolment step
  (`@installer.device`) when that plugin exists.
- [ ] **Swift bridges on macOS 27**: `LanguageModelSession.GenerationError` is deprecated
  (apple_bridge.swift); AVSpeech's synthesizer warns about the main actor.
- [ ] **A flaky end-to-end test**: once, the wake word heard nothing in 35 s with the
  synthetic voice (test_memory_with_claude); passed when repeated.

- [ ] **An always-on mode**: it never falls asleep (no wake word needed), for when you
  don't want to switch it off between sentences.
- [ ] **HTTPS served locally?** (a local certificate the device trusts): would remove
  Chrome's flag; less urgent with the native apps.

## Apps and devices

- [ ] **The app finds a local server**: AnyAssistant on the network (Bonjour/mDNS), no IP
  to type.
- [ ] **More than one device** (hub.py: «one at a time»): the device that heard you
  answers; an alarm rings where it was set, or everywhere; talking room to room
  («dile a la cocina que bajo ya»).

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

## Local skills

- [ ] **Lists and notes** (shopping, tasks, quick notes): very much voice, shouldn't go
  through the LLM.
- [ ] **«¿Qué tiempo hace?»**: today it depends on the LLM having a tool for it.

## Robustness

- [ ] **A plan B when the LLM fails** (network down, usage limit): switch to Apple or
  Hermes and say «now I answer with the local model». (Not found in the code; to
  confirm.)

## Conversation quality

- [ ] **Interrupting it without its name**: while it speaks it doesn't listen (echo), so
  only «Jarvis, stop» or a tap work. Needs better echo cancellation than the
  tablet's; what would most make it feel like a conversation, and the hardest.

- [ ] **Wake word**: keep watching false positives and negatives (31 Oct: 28 wake-ups,
  one false, fixed; no misses found). A name in the user's language comes with the
  app's new name (`name`).

## Done

- [x] **update and uninstall** (31 Oct): `bin/anyassistant update` (from where it was installed
  from; removes what a version removed) and `uninstall` (data only if you say so).

- [x] **The app is AnyAssistant** (`bin/anyassistant`, `ANYASSISTANT_HOME`…, the MCP
  server `anyassistant`, in Hermes's config too); the assistant is still Jarvis by default.

- [x] **Installer (terminal)**: install.sh + `bin/anyassistant setup`, steps from the core and
  the plugins, launchd; tried in a clean folder (31 Oct).

- [x] **Everything is a plugin** (31 Oct): the core only finds, loads and joins them
  (kernel, web hooks, events, kinds). Pairing, confirmation, memory, eyes, the page
  and skins, sounds, tap to wake, monitor, lab, MCP server, interpreter, the brains,
  «go to sleep» and «stop»… each a plugin, with what it needs in plugin.json.

- [x] **Skins**: the screen as HTML + CSS anyone can make (blocks, states, live variables,
  options, texts, sounds); eyes, orb, minimal and bedside; a lab and a checker.
- [x] **Not every sentence is for it**: a `follow_up` window (20 s) instead of 2 minutes
  listening, and `ignore_others`: the LLM answers `<silence>` to what isn't for it.
- [x] **Hermes with Jarvis's tools**: `jarvis` in Hermes's MCP servers; the «yes» is asked
  by the server itself, so it holds for Hermes too.
- [x] **Skills without an LLM**: time, date, timers, alarms, reminders, sums, units and
  volume; Apple's model as an optional interpreter; also as the LLM's tools.
- [x] **Eyes, second step**: a full-resolution photo to read (1200×1600 on the tablet);
  Hermes sees too (asked with «look», «read»…).
- [x] **Memory, more**: compacted by the LLM beyond 50 facts; reviewed by Apple's model
  too (it misses some new facts; Claude doesn't); corrections update the fact.
- [x] **Choosing the LLM**: `get_llms`/`set_llm` and «use Claude» / «cambia a Hermes».
- [x] **Memory**: `"memory": "explicit"|"auto"`; `memory.json`, a review
  of each conversation when it falls asleep (auto).
- [x] **Eyes (Phase 4)**: `"eyes": true`; with Claude, by words («what do you see?»,
  «read this») or by its own decision (Read on the image of the moment).
- [x] **Pairing** (optional: `"pairing": true`; `bin/anyassistant pair|unpair`).
- [x] **Interrupt by voice**: «Jarvis, stop» or «Jarvis, and tomorrow?» while it speaks.
- [x] **Latency**: a spare Claude process always ready (~1.5 s to the first word
  instead of 2.5–3). The model stays a setting (`llm_model`).
- [x] **Recordings**: the old debugging ones deleted; `record` only on request.
  Transcripts in the log only with `log_transcripts`.
- [x] **Languages**: English base and Spanish in `locales/`; `language` or by voice.
- [x] **Settings**: `settings.json`; face, voice, name, language also by voice with your «yes».
- [x] **Its own tools (MCP)**: the server is the `jarvis` MCP server (settings, memory,
  camera, reload, restart), used by Claude.
- [x] **Automated tests**: pytest in `tests/` (`uv run pytest`; `-m e2e` for the real server).

## Postponed

- **Native apps** (Android, Android TV, iOS, macOS, Windows, with the same features),
  after the server is a packaged app.
- **Bilingual at once**: answer in the language each sentence is spoken in; when
  everything else works.

The Mac's fixed IP and publishing the Google app are up to whoever installs it
(see the README).
