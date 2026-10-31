# TODO

## Next

- [ ] **The server as a packaged app** (the Mac first): install, start with the
  system, settings and pairing from its own window. What launchd would have done
  belongs to its installer.

- [ ] **Hermes with Jarvis's tools**: add the `jarvis` MCP server to Hermes's (not tried yet).

## Conversation quality

- [ ] **Wake word**: watch false positives and negatives; maybe a name in the
  user's language.
- [ ] **Not every sentence is for it**: once awake it answers everything it hears,
  even a conversation with someone else («…thanks, Gabriela. Bye.» → «I'm Jarvis,
  not Gabriela»). Ignore what clearly isn't addressed to it, at least right after a
  dubious wake-up.

## Done

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
- [x] **Pairing** (optional: `"pairing": true`; `bin/jarvis pair|unpair`).
- [x] **Interrupt by voice**: «Jarvis, stop» or «Jarvis, and tomorrow?» while it speaks.
- [x] **Latency**: a spare Claude process always ready (~1.5 s to the first word
  instead of 2.5–3). The model stays a setting (`llm_model`).
- [x] **Recordings**: the old debugging ones deleted; `record` only on request.
  Transcripts in the log only with `log_transcripts`.
- [x] **Face**: «eyes» and «orb», chosen with `face`.
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
- **The app's name**: a new one is coming (instead of «Jarvis»); `name` in the
  settings already changes it everywhere.

The Mac's fixed IP and publishing the Google app are up to whoever installs it
(see the README).
