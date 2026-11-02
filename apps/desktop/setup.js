// The installer in a window (as the Mac's Setup.swift and SetupView): welcome with the app's icon,
// «Install» (every default), «Customize…» (the installer's questions first) or «Connect to another
// server…» (the servers on this network, or a host and port, then the pairing code); the program's
// Python while it prepares, the steps as they go, its «device» steps (your voice: on this computer,
// once the server runs, through its /setup/device/<id>) and «Installed». The same steps as
// bin/anyassistant setup, through its JSON (setup.html draws them; this side runs them).

const { BrowserWindow, ipcMain, app, session } = require('electron');
const path = require('path');
const { Browser } = require('./bonjour');

let window = null;
let given = {};  // what main.js gives: the server, the texts and what to do when it ends
let phase = 'welcome';
let browser = null;
let devices = [];  // the «device» steps still to offer, the first one now
let following = null;  // the one going on: {id, stage}
let failed = false;

function configure(options) { given = options; }

function say(event, data) {
  if (window && !window.isDestroyed()) window.webContents.send(event, data);
}

let shown = {};  // what the phase showed last: the same again when the window opens again

function show(next, data) {
  phase = next;
  shown = data || {};
  say('setup:phase', { phase: next, ...shown });
}

/// The installer: its own window (before installing there is no menu to open it from). Closed
/// before installing (nor using another server), the app quits.
function open() {
  if (phase === 'finished') phase = 'welcome';  // «Install steps again»
  if (window && !window.isDestroyed()) {
    window.show();
    window.focus();
    show(phase, shown);
    return;
  }
  window = new BrowserWindow({
    width: 520, height: 560, resizable: false, minimizable: false, maximizable: false, fullscreenable: false,
    title: 'AnyAssistant', icon: path.join(__dirname, 'icons', 'icon.png'), autoHideMenuBar: true,
    backgroundColor: '#f6f7f9',
    webPreferences: { contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
  });
  window.loadFile(path.join(__dirname, 'setup.html'));
  window.webContents.on('did-finish-load', () => show(phase, shown));
  window.on('closed', () => {
    window = null;
    if (browser) { browser.stop(); browser = null; }
    if (given.quitUnlessReady) given.quitUnlessReady();
  });
}

// --- Installing (the server's installer, through its JSON) ---

/// The program and its Python, before any question.
async function prepare() {
  show('preparing', { note: given.T('Copying the program and preparing Python…') });
  const code = await given.server.prepare(() => {});
  if (code !== 0) show('failed', { note: given.T('It couldn\'t prepare the program.') });
  return code === 0;
}

const decode = (line) => { try { return JSON.parse(line); } catch (e) { return null; } };

/// «Install with what comes»: every default, no questions.
async function installWithDefaults() {
  if (!(await prepare())) return;
  await install(['--defaults']);
}

/// «Step by step»: the questions first.
async function askQuestions() {
  if (!(await prepare())) return;
  let questions = [];
  await given.server.setup(['--list', '--json'], (line) => {
    const steps = decode(line);
    if (!Array.isArray(steps)) return;
    questions = steps.filter((s) => s.kind === 'question').map((s) => ({
      id: s.id, title: s.title, help: s.help || '', choices: s.choices || null, default: s.default === undefined ? null : s.default,
    }));
  });
  show('questions', { questions });
}

async function installWithAnswers(answers, startAtLogin) {
  const args = [];
  for (const [id, value] of Object.entries(answers)) args.push('--set', `${id}=${typeof value === 'boolean' ? (value ? 'true' : 'false') : value}`);
  await install(args, startAtLogin);
}

async function install(args, startAtLogin = true) {
  show('installing');
  devices = [];
  const code = await given.server.setup(['--json', ...args], (line) => {
    const event = decode(line);
    if (event && event.event === 'device') devices.push(event);  // done on this computer once installed
    if (event && event.event) say('setup:event', event);
  });
  if (startAtLogin && given.setOpensAtLogin) { try { given.setOpensAtLogin(true); } catch (e) { /* */ } }
  failed = code !== 0;
  if (given.installed) given.installed();
  nextDevice();
}

// --- «Device» steps: on this computer, once the server runs ---

function nextDevice() {
  following = null;
  if (devices.length) show('device', { step: devices[0], stage: 'offer' });
  else show('finished', { failed });
}

async function call(id, body) {
  try {
    const r = await fetch(`${given.server.url}/setup/device/${id}`, {
      method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(5000),
    });
    return { status: r.status, answer: await r.json() };
  } catch (e) { return { status: 0, answer: {} }; }
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/// Its end: the step's row says how it went; then the next one, or «Installed».
function ended(step, status, text) {
  if (following && following.id === step.id) following = null;
  devices.shift();
  say('setup:event', { event: status, id: step.id, text });
  nextDevice();
}

/// Its button: once the server and this computer's own device are up, it starts there; then, how it goes.
async function startDevice() {
  const step = devices[0];
  if (!step || following) return;
  const mine = following = { id: step.id, stage: 'waiting' };
  if (given.listenHere) given.listenHere();  // its face, with the microphone
  show('device', { step, stage: 'waiting' });
  for (;;) {  // the server starting, this computer's device connecting
    if (following !== mine) return;
    const { status, answer } = await call(step.id);
    if (status === 404) return ended(step, 'skipped', step.later);  // its plugin isn't on
    if (status === 200 && answer.device) break;
    await pause(1000);
  }
  let { status, answer } = await call(step.id, { do: 'start' });
  mine.stage = 'running';
  while (following === mine) {
    if (status !== 200) return ended(step, 'error', answer.error || '');
    const state = answer.state;
    if (state && state.state === 'done') return ended(step, 'done', state.text || '');
    if (state && state.state === 'cancelled') return ended(step, 'skipped', state.text || '');
    if (state) show('device', { step, stage: 'running', ...state });
    await pause(500);
    ({ status, answer } = await call(step.id));
  }
}

/// «Not now» (or cancelling it while it waits for the server): how to do it later.
function skipDevice() {
  const step = devices[0];
  if (!step) return;
  if (following && following.stage === 'running') { call(step.id, { do: 'cancel' }); return; }  // its end comes as the server says it
  ended(step, 'skipped', step.later);
}

// --- Another server (this device only talks to it): as the iPhone pairs ---

/// Whether that server answers, and whether it asks for a code (403: pairing is on).
async function probe(host, port) {
  try {
    const r = await session.defaultSession.fetch(`http://${host}:${port}/`, { signal: AbortSignal.timeout(4000) });
    return { reachable: true, pairing: r.status === 403 };
  } catch (e) { return { reachable: false }; }
}

/// Pairs with the code (if asked for) in the app's own session: its cookie is what the face uses.
async function pair(host, port, code, pairing) {
  if (pairing) {
    try {
      const r = await session.defaultSession.fetch(`http://${host}:${port}/pair`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
        signal: AbortSignal.timeout(4000),
      });
      if (r.status === 403) return { problem: 'code' };
      if (!r.ok) return { problem: 'unreachable' };
    } catch (e) { return { problem: 'unreachable' }; }
  }
  return { paired: true };
}

// The servers found, but not this computer's own (if it is one too): this device talks to another.
function others() {
  let own = null;
  try { own = require('fs').readFileSync(path.join(given.server.data, 'server-id'), 'utf8').trim(); } catch (e) {}
  return (browser ? browser.servers : []).filter((s) => !s.server || s.server !== own);
}

function browse(on) {
  if (on && !browser) {
    browser = new Browser();
    browser.on('change', () => say('setup:servers', others()));
    browser.start();
  } else if (!on && browser) {
    browser.stop();
    browser = null;
  }
}

ipcMain.handle('setup:install-defaults', () => installWithDefaults());
ipcMain.handle('setup:ask-questions', () => askQuestions());
ipcMain.handle('setup:install', (e, answers, startAtLogin) => installWithAnswers(answers, startAtLogin));
ipcMain.handle('setup:device-start', () => startDevice());
ipcMain.handle('setup:device-skip', () => skipDevice());
ipcMain.handle('setup:phase', (e, next) => { phase = next; browse(next === 'another'); });
ipcMain.handle('setup:servers', () => others());
ipcMain.handle('setup:probe', (e, host, port) => probe(host, port));
ipcMain.handle('setup:pair', async (e, host, port, code, pairing) => {
  const answer = await pair(host, port, code, pairing);
  if (answer.paired) {
    browse(false);
    if (window && !window.isDestroyed()) { phase = 'welcome'; window.destroy(); window = null; }
    if (given.connected) given.connected({ host, port });
  }
  return answer;
});
ipcMain.handle('setup:close', () => { if (window && !window.isDestroyed()) window.close(); });
ipcMain.handle('setup:pair-window', () => {
  if (window && !window.isDestroyed()) window.close();
  if (given.pair) given.pair();
});

app.on('before-quit', () => browse(false));

module.exports = { configure, open };
