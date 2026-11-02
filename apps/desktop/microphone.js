// Another program is using this computer's microphone (a call in Teams or Zoom, a meeting in the
// browser), seen by the app itself: as a client of another server nobody else looks at this
// computer (with its own server, the plugin «microphone-busy» does it). The same checks as that
// plugin, ported from its Python, with the same rules:
//
// - Windows (10 1903 or later): the registry's microphone consent store (`reg query … /s`), what
//   Windows reads for the microphone icon in the taskbar: a key per packaged app and, under
//   NonPackaged, one per executable (its path with «#» for «\»), each with LastUsedTimeStart and
//   LastUsedTimeStop; LastUsedTimeStop == 0 means «in use now».
// - Linux: PipeWire's `pw-dump` (input audio streams running), or PulseAudio's `pactl list
//   source-outputs` (the ones not corked).
//
// Our own app (its page keeps the microphone open) is left out by its name: «anyassistant», and
// this executable's (electron, developing). Busy a second before pausing, free two before
// resuming (a change of a moment is normal). The parsers are pure, so tests feed them samples.

const { execFile } = require('child_process');
const path = require('path');

const EVERY = 1.0;  // seconds between looks
const BUSY_AFTER = 1.0;  // seconds another program must have been recording before pausing
const FREE_AFTER = 2.0;  // seconds free before resuming
const OURS = ['anyassistant', path.basename(process.execPath).replace(/\.exe$/i, '').toLowerCase()];

const CONSENT = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone';

/// Whether a program's name or path is our own app's.
function ours(name) {
  const lower = (name || '').toLowerCase();
  return OURS.some((word) => word && lower.includes(word));
}

// --- Windows: the consent store ---

/// `reg query <consent store> /s`, as [key name under the store, LastUsedTimeStart, LastUsedTimeStop]
/// (BigInt: they are 64-bit times); only the keys with those values.
function registryEntries(listing) {
  const entries = [];
  let current = null;
  for (const raw of (listing || '').split(/\r?\n/)) {
    if (/^HKEY_/i.test(raw)) {
      const at = raw.toLowerCase().indexOf('\\consentstore\\microphone\\');
      current = at >= 0 ? { name: raw.slice(at + '\\consentstore\\microphone\\'.length).trim(), start: null, stop: null } : null;
      if (current) entries.push(current);
      continue;
    }
    const value = raw.match(/^\s+(LastUsedTimeStart|LastUsedTimeStop)\s+REG_QWORD\s+(0x[0-9a-f]+)/i);
    if (current && value) current[value[1] === 'LastUsedTimeStart' ? 'start' : 'stop'] = BigInt(value[2]);
  }
  return entries.filter((e) => e.start !== null || e.stop !== null).map((e) => [e.name, e.start || 0n, e.stop || 0n]);
}

/// The names of the apps recording now, from [key name, start, stop]: started and not stopped. Ours left out.
function windowsBusy(entries) {
  return entries.filter(([name, start, stop]) => start && !stop && !ours(name)).map(([name]) => windowsName(name));
}

/// A readable name: a packaged app's family name («Microsoft.Teams») or an executable's («Zoom»).
function windowsName(key) {
  let leaf = key.replace(/#/g, '\\').split('\\').pop();
  if (leaf.toLowerCase().endsWith('.exe')) leaf = leaf.slice(0, -4);
  return leaf.includes('_') && !key.startsWith('C:') ? leaf.split('_')[0] : leaf;
}

// --- Linux: PipeWire or PulseAudio ---

/// The apps recording now, from `pw-dump`'s JSON: input audio streams that are running.
function pipewireBusy(dump) {
  let nodes;
  try { nodes = JSON.parse(dump); } catch (e) { return []; }
  const found = [];
  for (const node of Array.isArray(nodes) ? nodes : []) {
    const info = (node && node.info) || {};
    const props = info.props || {};
    if (props['media.class'] !== 'Stream/Input/Audio' || info.state !== 'running') continue;
    const name = props['application.name'] || props['node.name'] || '';
    const binary = props['application.process.binary'] || '';
    if (ours(name) || ours(binary)) continue;
    found.push(name || binary);
  }
  return found;
}

/// The apps recording now, from `pactl list source-outputs`: the ones not corked.
function pulseBusy(listing) {
  const found = [];
  for (const block of (listing || '').split(/^Source Output #/m).slice(1)) {
    const corked = block.match(/^\s*Corked:\s*(\w+)/m);
    if (corked && corked[1].toLowerCase() === 'yes') continue;
    const name = (block.match(/application\.name = "([^"]*)"/) || [])[1] || '';
    const binary = (block.match(/application\.process\.binary = "([^"]*)"/) || [])[1] || '';
    if (ours(name) || ours(binary)) continue;
    found.push(name || binary || '?');
  }
  return found;
}

// --- Asking the system ---

/// A command's output; null if it isn't there (or fails to run).
function output(command, args) {
  return new Promise((done) => {
    execFile(command, args, { timeout: 3000, windowsHide: true, maxBuffer: 8 * 1024 * 1024 }, (error, stdout) => {
      done(error && (error.code === 'ENOENT' || !stdout) ? null : stdout);
    });
  });
}

/// The other programs recording now on this computer (their names).
async function busy() {
  if (process.platform === 'win32') {
    const listing = await output('reg', ['query', CONSENT, '/s']);
    return listing === null ? [] : windowsBusy(registryEntries(listing));
  }
  if (process.platform === 'linux') {
    for (const [command, args, parse] of [['pw-dump', [], pipewireBusy], ['pactl', ['list', 'source-outputs'], pulseBusy]]) {
      const found = await output(command, args);
      if (found !== null) return parse(found);
    }
  }
  return [];
}

/// Busy a while before pausing, free a while before resuming: tick(found, now) says what changed:
/// 'busy' (program: the first one's name), 'free', or null. reset(): free at once (looking stopped).
class Watch {
  constructor() {
    this.busy = false;
    this.since = null;
    this.program = '';
  }

  tick(found, now) {
    if (Boolean(found.length) === this.busy) {
      this.since = null;
      return null;
    }
    this.since = this.since !== null ? this.since : now;
    if (now - this.since < (this.busy ? FREE_AFTER : BUSY_AFTER)) return null;
    this.busy = Boolean(found.length);
    this.since = null;
    this.program = found[0] || '';
    return this.busy ? 'busy' : 'free';
  }

  reset() {
    this.since = null;
    if (!this.busy) return null;
    this.busy = false;
    this.program = '';
    return 'free';
  }
}

module.exports = { EVERY, BUSY_AFTER, FREE_AFTER, ours, registryEntries, windowsBusy, windowsName, pipewireBusy, pulseBusy, busy, Watch };
