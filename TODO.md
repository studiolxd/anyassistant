# TODO

## Next

- [ ] **Eyes, second step**: a high-resolution photo when asked to read (the video
  is 320×240 on small devices); with Hermes too if its model takes images.
- [ ] **Memory across conversations** with Claude (Hermes already has it). For now,
  what you ask it to remember goes to `instructions` in `settings.json` (`bin/settings`).
- [ ] **The server as a packaged app** (the Mac first): install, start with the
  system, settings and pairing from its own window. What launchd would have done
  belongs to its installer.

## Conversation quality

- [ ] **Wake word**: watch false positives and negatives; maybe a name in the
  user's language.
- [ ] **Not every sentence is for it**: once awake it answers everything it hears,
  even a conversation with someone else («…thanks, Gabriela. Bye.» → «I'm Jarvis,
  not Gabriela»). Ignore what clearly isn't addressed to it, at least right after a
  dubious wake-up.

## Done

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
- [x] **Settings**: `settings.json`, also by voice with your «yes» (`bin/settings`).
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
