// AnyAssistant for Windows and Linux, in the tray (as the Mac app is in the menu bar): the same
// menu, the same windows. The first time, it installs the server (with what comes, or step by
// step: setup.js, the installer's window) or connects to another server; then it runs it, says how
// it is, and pairs devices. The assistant is on this computer too: «Show Eva» opens its face (the
// page, with Chromium's microphone, camera and echo cancellation). Settings, devices and
// «Connect another device» are the admin page (/admin), each in its window, as on the Mac.
//
//   cd apps/desktop && npm install && npm start      (ANYASSISTANT_SETUP=1 npm start: the installer's window too)

const { app, BrowserWindow, Menu, Tray, nativeImage, session, shell, dialog, systemPreferences, ipcMain } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Server } = require('./server');
const setup = require('./setup');
const microphone = require('./microphone');

// Its texts: the key is the English in the code (the Mac app's); locales/<language>.json says it
// in the system's language (app.getLocale: known once the app is ready).
let TEXTS = {};
function loadTexts() {
  TEXTS = require((app.getLocale() || '').startsWith('es') ? './locales/es.json' : './locales/en.json');
}
const T = (english, ...values) => {
  let text = TEXTS[english] || english;
  for (const v of values) text = text.replace('%s', v);
  return text;
};
/// A menu item's text: without the «…» (in the menu, an item says what it does, plainly).
const M = (english) => T(english).replace(/…\s*$/, '');

if (!app.requestSingleInstanceLock()) app.quit();

// Packaged (the Windows installer, the AppImage, the .deb): it carries the program and uv; the
// program is copied, the first time and when a newer one comes, to where it can make its Python
// (%LOCALAPPDATA%\AnyAssistant\program, ~/.local/opt/AnyAssistant), keeping that Python.
function installProgram() {
  const bundled = path.join(process.resourcesPath, 'program');
  const target = process.platform === 'win32'
    ? path.join(process.env.LOCALAPPDATA || os.homedir(), 'AnyAssistant', 'program')
    : path.join(os.homedir(), '.local', 'opt', 'AnyAssistant');
  const number = (folder) => {
    try { return parseInt(fs.readFileSync(path.join(folder, 'VERSION'), 'utf8'), 10) || 0; } catch (e) { return 0; }
  };
  if (number(target) < number(bundled)) {
    fs.mkdirSync(target, { recursive: true });
    for (const entry of fs.readdirSync(target)) {  // what a new version removed goes; its Python stays
      if (!['.venv', 'install.env', 'native'].includes(entry)) fs.rmSync(path.join(target, entry), { recursive: true, force: true });
    }
    fs.cpSync(bundled, target, { recursive: true });
  }
  process.env.ANYASSISTANT_PROGRAM = target;
  const uv = path.join(process.resourcesPath, 'uv', process.platform === 'win32' ? 'uv.exe' : 'uv');
  if (fs.existsSync(uv)) process.env.UV = uv;
}
if (app.isPackaged) installProgram();

const server = new Server(__dirname);
let tray = null;
let name = 'Eva';
const windows = {};

// --- What the app remembers (app.json, with your data): whether it listens on this device, and another server it talks to ---

const stateFile = () => path.join(server.data, 'app.json');
let state = { listening: true, client: null };  // client: {host, port, name}: another server; null: this one
try { state = { ...state, ...JSON.parse(fs.readFileSync(stateFile(), 'utf8')) }; } catch (e) { /* the first time */ }
function remember(changes) {
  Object.assign(state, changes);
  try { fs.mkdirSync(path.dirname(stateFile()), { recursive: true }); fs.writeFileSync(stateFile(), JSON.stringify(state)); } catch (e) { /* */ }
}
const isClient = () => Boolean(state.client);
/// Where the assistant is: this computer's server, or another one's.
const base = () => (isClient() ? `http://${state.client.host}:${state.client.port}` : server.url);
/// Whether it has a server to talk to, or still needs installing (then: only the installer's window).
const ready = () => isClient() || server.installed;

// --- Its windows: the face, the admin page's (settings, devices, pairing) and the themes ---

// The window's content, from the server; while it doesn't answer, what to do (unavailable.html:
// start it if it is stopped, else try again), in the middle, instead of Chromium's error page.
function open(id, route, options) {
  const found = windows[id];
  if (found && !found.isDestroyed()) {
    if (found.webContents.getURL() !== base() + route) found.loadURL(base() + route);
    if (!options.hidden) { found.show(); found.focus(); }  // the face, listening hidden: left as it is
    return found;
  }
  const made = new BrowserWindow({
    width: options.width, height: options.height, minWidth: options.minWidth, minHeight: options.minHeight,
    title: options.title, icon: path.join(__dirname, 'icons', 'icon.png'), show: options.hidden !== true,
    autoHideMenuBar: true, backgroundColor: options.dark ? '#000000' : '#f6f7f9',
    webPreferences: { contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js'),
                      autoplayPolicy: 'no-user-gesture-required', backgroundThrottling: false },
  });
  made.on('page-title-updated', (e) => e.preventDefault());  // the window's title is the app's, not the page's
  made.webContents.on('did-fail-load', (e, code, why, url, isMainFrame) => {
    if (isMainFrame && code !== -3) made.loadFile(path.join(__dirname, 'unavailable.html'), { query: { route } });
  });
  made.loadURL(base() + route);
  for (const event of ['show', 'hide', 'closed']) made.on(event, () => tray && menu());  // the menu follows it
  // A link to another of the app's windows (the page's «Connect another device…» in Devices) opens
  // it; any other link, the browser.
  made.webContents.setWindowOpenHandler(({ url }) => {
    const wanted = url.startsWith(base() + '/admin?window=') ? new URL(url).searchParams.get('window') : null;
    if (wanted && WINDOWS[wanted]) WINDOWS[wanted]();
    else shell.openExternal(url);
    return { action: 'deny' };
  });
  windows[id] = made;
  return made;
}

/// The windows showing «the server isn't responding»: its content again once it answers.
function retryUnavailable() {
  for (const window of Object.values(windows)) {
    if (window.isDestroyed()) continue;
    const url = window.webContents.getURL();
    if (!url.startsWith('file:')) continue;
    const route = new URL(url).searchParams.get('route') || '/';
    window.loadURL(base() + route);
  }
}

const faceShown = () => Boolean(windows.face && !windows.face.isDestroyed() && windows.face.isVisible());

// Its face: the page. With «Listen on this device» on, the page runs while the window is hidden (its
// microphone keeps listening; closing the window only hides it), and starts by itself.
function face(show = true) {
  const had = windows.face && !windows.face.isDestroyed();
  const made = open('face', '/', { width: 480, height: 640, minWidth: 320, minHeight: 400, title: name, dark: true, hidden: !show });
  if (had) return;
  made.on('close', (e) => {
    if (!state.listening || app.quitting) return;
    e.preventDefault();
    made.hide();
  });
  // Listening: «Start» pressed for you, once the page shows it (after its texts come).
  made.webContents.on('did-finish-load', () => {
    if (state.listening && made.webContents.getURL().startsWith('http')) {
      made.webContents.executeJavaScript('(function () { var tries = 0; var wait = setInterval(function () {' +
        ' var b = document.getElementById("start"); if (b && !b.hidden) { b.click(); clearInterval(wait); }' +
        ' if (++tries > 40) clearInterval(wait); }, 250); })()').catch(() => {});
    }
  });
}
const showFace = () => face(true);
const hideFace = () => { if (windows.face && !windows.face.isDestroyed()) windows.face.close(); };

/// Listening on this device: its face runs (hidden) while nobody looks at it; off, only while shown.
function listen(on) {
  remember({ listening: on });
  if (on) { if (running() && !faceShown()) face(false); }
  else if (windows.face && !windows.face.isDestroyed() && !windows.face.isVisible()) windows.face.destroy();
  menu();
}

// The admin page's windows, as the Mac's: the page shows that window's part only (?window=).
const showSettings = () => open('settings', '/admin?window=settings#settings', { width: 940, height: 640, minWidth: 780, minHeight: 520, title: T('Settings') });
const showDevices = () => open('devices', '/admin?window=devices#devices', { width: 520, height: 460, minWidth: 440, minHeight: 320, title: T('Devices') });
const showPair = () => open('pair', '/admin?window=pair#pair', { width: 680, height: 500, minWidth: 680, minHeight: 440, title: T('Pair a device') });
const showThemes = () => open('themes', '/themes', { width: 1100, height: 780, minWidth: 640, minHeight: 480, title: T('Themes'), dark: true });
const WINDOWS = { settings: showSettings, devices: showDevices, pair: showPair };

// The page may use the microphone and camera, keep the screen on and go full screen; only the
// server's own page (this computer's, or the other server it talks to), nothing else.
function permissions() {
  const ours = (url) => { try { const u = new URL(url); return u.origin === base() || u.hostname === '127.0.0.1'; } catch (e) { return false; } };
  const allowed = new Set(['media', 'fullscreen', 'screen-wake-lock', 'notifications']);
  session.defaultSession.setPermissionRequestHandler((contents, permission, done, details) => {
    done(allowed.has(permission) && ours(details.requestingUrl || contents.getURL()));
  });
  session.defaultSession.setPermissionCheckHandler((contents, permission, origin) => allowed.has(permission) && ours(origin));
  // It says what it is: the server lists it as a PC («AnyAssistant Desktop»).
  session.defaultSession.setUserAgent(session.defaultSession.getUserAgent() + ' AnyAssistant Desktop');
}

// --- Opening at login ---

function autostartFile() {
  return path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'autostart', 'anyassistant.desktop');
}

function opensAtLogin() {
  if (process.platform === 'linux') return fs.existsSync(autostartFile());
  return app.getLoginItemSettings().openAtLogin;
}

function setOpensAtLogin(on) {
  if (process.platform !== 'linux') return app.setLoginItemSettings({ openAtLogin: on });
  const file = autostartFile();
  if (!on) return fs.rmSync(file, { force: true });
  // Packaged, the app itself; developing, Electron with this folder.
  const command = app.isPackaged ? `"${process.execPath}"` : `"${process.execPath}" "${__dirname}"`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `[Desktop Entry]\nType=Application\nName=AnyAssistant\nExec=${command}\n` +
                         `Icon=${path.join(__dirname, 'icons', 'icon.png')}\nX-GNOME-Autostart-enabled=true\n`);
}

// --- Windows' privacy: the microphone and the camera (Linux has none to ask) ---

function refused(what) {
  if (process.platform !== 'win32') return false;
  try { return systemPreferences.getMediaAccessStatus(what) === 'denied'; } catch (e) { return false; }
}

const PRIVACY = { microphone: 'ms-settings:privacy-microphone', camera: 'ms-settings:privacy-webcam' };

// --- The connected devices, for the menu (its name, room and LLM) ---

let connected = [];
const LLM_NAMES = { claude: 'Claude', codex: 'Codex', gemini: 'Gemini', opencode: 'OpenCode', openai: 'OpenAI',
                    ollama: 'Ollama', hermes: 'Hermes', apple: 'Apple' };
const running = () => server.state === 'running';

async function followDevices() {
  if (!running()) { connected = []; return; }
  try { connected = (await server.call('GET', '/status')).devices || []; } catch (e) { /* not now */ }
}

// Each connected one: its name, room and LLM; a click opens Devices (rename it, its room, its own LLM).
function deviceItems() {
  if (!running()) return [];
  if (!connected.length) return [{ type: 'separator' }, { label: T('No device connected'), enabled: false }];
  const items = connected.slice(0, 5).map((d) => ({
    label: [d.name || T('a device'), d.room, LLM_NAMES[d.llm] || d.llm].filter(Boolean).join(' · '),
    click: showDevices,
  }));
  if (connected.length > 5) items.push({ label: T('and %s more', connected.length - 5), click: showDevices });
  return [{ type: 'separator' }, ...items];
}

// --- The other server, as a client (the Mac's «Conectarse a otro servidor») ---

let linked = false;  // the other server answers
async function followLink() {
  if (!isClient()) return;
  try {
    const r = await session.defaultSession.fetch(base() + '/status', { signal: AbortSignal.timeout(2000) });
    linked = r.ok;
  } catch (e) { linked = false; }
}

/// What the menu says about it, as a client of another server.
function clientStatus() {
  if (linked) return T('Connected to %s', state.client.host);
  return state.listening ? T('Looking for the server…') : T('The microphone is off');
}

// --- Another app using the microphone, as a client (the Mac's MicrophoneWatch) ---
//
// With its own server, the server looks (the plugin «microphone-busy») and pauses this computer's
// page. As a client of another server nobody looks at this computer: the app does (microphone.js:
// the same checks), and its page tells the server it talks to, as the Mac app does: «paused» (why
// «microphone», the app's name) and «listening» again. Only if that server wants it (its
// «pause_when_microphone_busy», from /config) and while the face runs (listening, or shown).

const micWatch = new microphone.Watch();
let pauseWanted = true;  // the other server's «pause_when_microphone_busy»
let configAsked = 0;

async function followPauseOption() {
  if (!isClient() || !linked || Date.now() - configAsked < 30000) return;
  configAsked = Date.now();
  try {
    const r = await session.defaultSession.fetch(base() + '/config', { signal: AbortSignal.timeout(3000) });
    const found = (await r.json()).screen || {};
    pauseWanted = found.pause_when_microphone_busy !== false;
  } catch (e) { /* not now: as it was */ }
}

const faceRuns = () => Boolean(windows.face && !windows.face.isDestroyed() && windows.face.webContents.getURL().startsWith('http'));

// What the page does (its own functions: tell, holdMicrophone): once per connection (a page that
// connects again, or loads again, is told again), the microphone's track sending silence meanwhile.
const PAGE_PAUSED = (program) => `(function (app) {
  if (typeof tell !== 'function' || !channel || channel.readyState !== 'open') return;
  if (window.anyassistantPaused === channel) return;
  window.anyassistantPaused = channel;
  tell({ type: 'paused', why: 'microphone', app: app });
  holdMicrophone(true);
})(${JSON.stringify(program)})`;
const PAGE_LISTENING = `(function () {
  if (!window.anyassistantPaused) return;
  window.anyassistantPaused = null;
  tell({ type: 'listening' });
  holdMicrophone(false);
})()`;

function toPage(code) {
  if (faceRuns()) windows.face.webContents.executeJavaScript(code).catch(() => {});
}

let looking = false;
async function lookAtMicrophone() {
  if (looking) return;
  looking = true;
  try {
    const on = isClient() && pauseWanted && faceRuns() && (process.platform === 'win32' || process.platform === 'linux');
    const change = on ? micWatch.tick(await microphone.busy(), Date.now() / 1000) : micWatch.reset();
    if (change === 'free') toPage(PAGE_LISTENING);
    if (micWatch.busy) toPage(PAGE_PAUSED(micWatch.program));  // again each time: a page connected again is told too
    if (change) menu();
  } catch (e) { /* it keeps looking */ } finally { looking = false; }
}

// --- The tray ---

// How it is, at a glance (the Mac draws a symbol by it; here, a plain mark): its state.
function status() {
  switch (server.state) {
    case 'starting': return '… ' + T('Starting…');
    case 'running': return '✓ ' + T('Running') + (server.systemd ? ' · ' + T('started by systemd') : '');
    case 'failed': return '⚠ ' + (server.why === 'crashed' ? T('It stopped; starting it again…') : T('It failed') + (server.why ? ` (${server.why})` : ''));
    default: return server.installed ? '■ ' + T('Stopped') : '⬇ ' + T('Not installed yet');
  }
}

const faceItem = () => (faceShown()
  ? { label: T('Hide %s', name), click: hideFace }
  : { label: T('Show %s', name), enabled: isClient() || running(), click: showFace });
const listenItem = () => ({ label: T('Listen on this device'), type: 'checkbox', checked: state.listening, click: (item) => listen(item.checked) });
// «Paused: Zoom is using the microphone»: the server paused this computer's own page while another
// program records (the plugin «microphone-busy»); /status says so of the device from 127.0.0.1.
// As a client, the app's own look (lookAtMicrophone).
const pausedText = () => {
  const own = isClient() ? (micWatch.busy ? { app: micWatch.program } : null) : (connected.find((d) => d.local && d.paused) || {}).paused;
  if (!own) return null;
  return own.app ? T('Paused: %s is using the microphone', own.app) : T('Paused: another app is using the microphone');
};
const pausedItems = () => (pausedText() ? [{ label: pausedText(), enabled: false }] : []);
const privacyItems = () => [
  ...(refused('microphone') ? [{ label: M('Allow the microphone…'), click: () => shell.openExternal(PRIVACY.microphone) }] : []),
  ...(refused('camera') ? [{ label: M('Allow the camera…'), click: () => shell.openExternal(PRIVACY.camera) }] : []),
];
const loginItem = () => ({ label: T('Open at login'), type: 'checkbox', checked: opensAtLogin(), click: (item) => setOpensAtLogin(item.checked) });
const quitItem = () => ({ label: T('Quit AnyAssistant'), click: () => app.quit() });

/// A client of another server: its face and its microphone, nothing else here.
function clientMenu() {
  return [
    { label: clientStatus(), enabled: false },
    { type: 'separator' },
    faceItem(), listenItem(), ...pausedItems(), ...privacyItems(),
    { type: 'separator' },
    { label: M('Run the server on this device…'), click: useThisDevice },
    loginItem(),
    { type: 'separator' },
    quitItem(),
  ];
}

function serverMenu() {
  return [
    { label: status(), enabled: false },
    ...deviceItems(),
    // The server, right under how it is: start it when stopped (or failed); while it starts, only
    // stop it; running, restart or stop.
    ...(server.state === 'stopped' || server.state === 'failed' ? [{ label: T('Start'), click: () => server.start() }]
      : server.state === 'starting' ? [{ label: T('Stop'), click: () => server.stop() }]
      : [{ label: T('Restart'), click: () => server.restart() }, { label: T('Stop'), click: () => server.stop() }]),
    { type: 'separator' },
    faceItem(), listenItem(), ...pausedItems(), ...privacyItems(),
    { label: M('Themes…'), enabled: running(), click: showThemes },  // every state of each theme, to see them (the plugin «themes»)
    { type: 'separator' },
    { label: M('Pair a device…'), click: showPair },
    { label: M('Devices…'), click: showDevices },
    { type: 'separator' },
    { label: T('Show the log'), click: () => shell.openPath(server.log) },
    { label: M('Settings…'), click: showSettings },
    { label: M('Install steps again…'), click: () => setup.open() },
    loginItem(),
    { type: 'separator' },
    quitItem(),
  ];
}

function menu() {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate(isClient() ? clientMenu() : serverMenu()));
  tray.setToolTip(`AnyAssistant · ${isClient() ? clientStatus() : status().replace(/^\S+ /, '')}`);
}

/// Installed, or using another server: the tray (there is none before: only the installer's window).
function showTray() {
  if (tray) return;
  const icon = nativeImage.createFromPath(path.join(__dirname, 'icons', 'tray.png'));
  tray = new Tray(icon);
  tray.on('click', () => ((isClient() || running()) ? showFace() : null));  // Windows: a click shows it
  menu();
  setInterval(async () => { if (!isClient()) await server.check(); await followDevices(); await followLink(); await followPauseOption(); menu(); }, 5000);  // the server, its devices, permissions: as they are
  setInterval(lookAtMicrophone, microphone.EVERY * 1000);  // as a client: another app using the microphone
}

async function learnName() {
  try {
    const found = await server.call('GET', '/admin/status');
    name = found.name || name;
  } catch (e) { /* not yet */ }
}

server.on('change', async () => {
  if (server.state === 'failed' && server.why === 'uv') {
    dialog.showMessageBox({ type: 'warning', message: T('uv isn\'t installed: it brings Python and the server\'s packages.'),
      detail: T('Install it and open AnyAssistant again:') + '\n\n' + (process.platform === 'win32'
        ? 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        : 'curl -LsSf https://astral.sh/uv/install.sh | sh') });
  }
  if (running()) {
    await learnName();
    retryUnavailable();
    if (state.listening && !faceShown()) face(false);  // it listens on this device too
  }
  menu();
});

// --- This computer's server, or another one's (the installer's window decides) ---

/// Only a client of another server: paired there (setup.js did it), its face talks to it.
function useAnother(client) {
  if (server.ours) server.stop();
  remember({ client });
  configAsked = 0;  // its own «pause_when_microphone_busy», at once
  for (const id of Object.keys(windows)) if (windows[id] && !windows[id].isDestroyed()) windows[id].destroy();
  showTray();
  menu();
  followLink().then(menu);
  if (state.listening) face(false);
}

/// The server on this computer again: installed, it starts; else the installer.
function useThisDevice() {
  remember({ client: null });
  for (const id of Object.keys(windows)) if (windows[id] && !windows[id].isDestroyed()) windows[id].destroy();
  menu();
  if (server.installed) server.begin(); else setup.open();
}

// --- The windows' own buttons (unavailable.html): start the server, try again ---

ipcMain.handle('texts', () => TEXTS);  // the app's own pages (setup.html, unavailable.html)
ipcMain.handle('server-state', () => ({ state: server.state, client: isClient() }));
ipcMain.handle('server-start', () => { if (!isClient()) server.start(); });
ipcMain.handle('retry', () => retryUnavailable());

app.on('second-instance', () => (ready() ? showFace() : setup.open()));
app.on('window-all-closed', (e) => e.preventDefault());  // it stays in the tray

app.quitting = false;
app.on('before-quit', async (e) => {
  if (app.quitting) return;
  e.preventDefault();
  app.quitting = true;
  await server.quit();  // its own server goes with it; systemd's stays
  app.exit(0);
});

app.whenReady().then(async () => {
  loadTexts();
  permissions();
  setup.configure({ server, T,
    installed: () => { showTray(); server.begin(); menu(); },  // installed now: the menu, and the server runs
    listenHere: () => (state.listening ? face(false) : showFace()),  // a «device» step (your voice): its microphone
    connected: useAnother, pair: showPair, setOpensAtLogin, quitUnlessReady: () => { if (!ready()) app.quit(); } });
  if (!ready()) return setup.open();  // not installed yet (nor using another server): no menu, the installer
  if (process.env.ANYASSISTANT_SETUP) setup.open();  // developing: the installer's window, to see it
  showTray();
  if (isClient()) { await followLink(); menu(); if (state.listening) face(false); return; }
  await server.begin();
});
