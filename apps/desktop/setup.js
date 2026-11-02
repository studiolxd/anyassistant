// The installer in a window (as the Mac's Setup.swift and SetupView): welcome with the app's icon,
// «Install» (every default), «Customize…» (the installer's questions first) or «Connect to another
// server…» (the servers on this network, or a host and port, then the pairing code); the program's
// Python while it prepares, the steps as they go, and «Installed». The same steps as
// bin/anyassistant setup, through its JSON (setup.html draws them; this side runs them).

const { BrowserWindow, ipcMain, app, session } = require('electron');
const path = require('path');
const { Browser } = require('./bonjour');

let window = null;
let given = {};  // what main.js gives: the server, the texts and what to do when it ends
let phase = 'welcome';
let browser = null;

function configure(options) { given = options; }

function say(event, data) {
  if (window && !window.isDestroyed()) window.webContents.send(event, data);
}

function show(next, data) {
  phase = next;
  say('setup:phase', { phase: next, ...data });
}

/// The installer: its own window (before installing there is no menu to open it from). Closed
/// before installing (nor using another server), the app quits.
function open() {
  if (phase === 'finished') phase = 'welcome';  // «Install steps again»
  if (window && !window.isDestroyed()) {
    window.show();
    window.focus();
    show(phase);
    return;
  }
  window = new BrowserWindow({
    width: 520, height: 560, resizable: false, minimizable: false, maximizable: false, fullscreenable: false,
    title: 'AnyAssistant', icon: path.join(__dirname, 'icons', 'icon.png'), autoHideMenuBar: true,
    backgroundColor: '#f6f7f9',
    webPreferences: { contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
  });
  window.loadFile(path.join(__dirname, 'setup.html'));
  window.webContents.on('did-finish-load', () => show(phase));
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
  const code = await given.server.setup(['--json', ...args], (line) => {
    const event = decode(line);
    if (event && event.event) say('setup:event', event);
  });
  if (startAtLogin && given.setOpensAtLogin) { try { given.setOpensAtLogin(true); } catch (e) { /* */ } }
  show('finished', { failed: code !== 0 });
  if (given.installed) given.installed();
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
