# TODO

## Before daily use

- [ ] **Pairing**: right now anyone on the Wi-Fi can connect and use Jarvis (which
  can already send emails and delete things). A code the tablet stores the first
  time, without which the server refuses connections.
- [ ] **macOS service (launchd)**: start the server with the Mac and restart it if
  it fails. For now, by hand with `bin/jarvis start|stop|restart|status|log`.
- [ ] **Stop recording**: `--record` is no longer used by default; delete the old
  debugging recordings.

## Conversation quality

- [ ] **Interrupt by voice** («Jarvis, stop») while it speaks; today only by tapping
  the screen. Hard with the tablet's echo cancellation.
- [ ] **Latency** (~2–3 s, mostly until Claude's first sentence): start the process
  earlier, Haiku for short answers…
- [ ] **Wake word**: watch false positives and negatives; maybe a name in the
  user's language.

## Features

- [ ] **Eyes (Phase 4)**: look through the camera when asked («what do you see?», «read this»).
- [ ] **Memory across conversations** with Claude (Hermes already has it).
- [x] **Face**: «eyes» (default) and «orb» (`?face=orb`), clock while asleep,
  «question» state; `?demo` cycles through the states without connecting. One
  still has to be chosen.
- [ ] **Native apps** (later, once we know what they should be like): Android, Android TV,
  iOS, macOS and Windows, with the same features on all of them.
- [x] **Languages**: English base and Spanish in `locales/`; detected from the Mac.

## Maintenance

- [x] **Automated tests**: pytest in `tests/` (`uv run pytest`; `-m e2e` for the real server).

## To do by hand

- [x] Re-authorize **Holded**.

## Postponed

- **Publish the Google app** (Google Auth Platform → Audience) so the authorization
  doesn't expire every 7 days; then `bin/gog-authorize` again. Re-authorize meanwhile.
- **Fixed IP for the Mac**: for now, update the tablet's URL when it changes.
- **The app's name**: a new one is coming (instead of «Jarvis»); the folder will be
  renamed then, not to «jarvis».
