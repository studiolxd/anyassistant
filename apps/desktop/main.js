// AnyAssistant for Windows and Linux, in the tray (as the Mac app is in the menu bar): it runs the
// server, and the assistant is on this computer too: «Show Eva» opens its face (the page, with
// Chromium's microphone, camera and echo cancellation). Pairing, settings, plugins, devices,
// voices and mail are the admin page (/admin), in a window.
//
//   cd apps/desktop && npm install && npm start

const { app, BrowserWindow, Menu, Tray, nativeImage, session, shell, dialog } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Server } = require('./server');

const SPANISH = (app.getLocale() || '').startsWith('es');
const TEXTS = {
  'Starting…': 'Arrancando…', 'Running': 'Funcionando', 'Stopped': 'Parado',
  'Preparing it (the first time it downloads Python and the models: a few minutes)…':
    'Preparándolo (la primera vez descarga Python y los modelos: unos minutos)…',
  'It failed': 'Ha fallado', 'Show %s': 'Mostrar a %s', 'Pair a device…': 'Emparejar un dispositivo…',
  'Administer…': 'Administrar…', 'Start': 'Arrancar', 'Stop': 'Parar', 'Restart': 'Reiniciar',
  'Show the log': 'Ver el registro', 'Open at login': 'Abrir al iniciar sesión', 'Quit AnyAssistant': 'Salir de AnyAssistant',
  'started by systemd': 'lo arranca systemd',
  'uv isn\'t installed: it brings Python and the server\'s packages.': 'uv no está instalado: trae Python y los paquetes del servidor.',
  'Install it and open AnyAssistant again:': 'Instálalo y vuelve a abrir AnyAssistant:',
  'The server keeps running (systemd): only the app closes.': 'El servidor sigue funcionando (systemd): solo se cierra la app.',
};
const T = (english, ...values) => {
  let text = SPANISH ? (TEXTS[english] || english) : english;
  for (const v of values) text = text.replace('%s', v);
  return text;
};

if (!app.requestSingleInstanceLock()) app.quit();

const server = new Server(__dirname);
let tray = null;
let name = 'Eva';
const windows = {};

// --- Its windows: the face and the admin page ---

function open(id, route, options) {
  const found = windows[id];
  if (found && !found.isDestroyed()) {
    found.loadURL(server.url + route);
    found.show();
    found.focus();
    return;
  }
  const made = new BrowserWindow({
    width: options.width, height: options.height, title: options.title, icon: path.join(__dirname, 'icons', 'icon.png'),
    autoHideMenuBar: true, backgroundColor: options.dark ? '#000000' : '#f6f7f9',
    webPreferences: { contextIsolation: true, sandbox: true },
  });
  made.loadURL(server.url + route);
  made.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  windows[id] = made;
}

const showFace = () => open('face', '/', { width: 480, height: 720, title: name, dark: true });
const showAdmin = (part = '') => open('admin', '/admin' + part, { width: 1100, height: 780, title: 'AnyAssistant' });

// The page may use the microphone and camera, keep the screen on and go full screen; only the
// server's own page (127.0.0.1), nothing else.
function permissions() {
  const ours = (url) => { try { return new URL(url).hostname === '127.0.0.1'; } catch (e) { return false; } };
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

// --- The tray ---

function status() {
  switch (server.state) {
    case 'starting': return server.ours ? T('Preparing it (the first time it downloads Python and the models: a few minutes)…') : T('Starting…');
    case 'running': return T('Running') + (server.systemd ? ' · ' + T('started by systemd') : '');
    case 'failed': return T('It failed') + (server.why ? ` (${server.why})` : '');
    default: return T('Stopped');
  }
}

function menu() {
  const running = server.state === 'running';
  const items = [
    { label: status(), enabled: false },
    { type: 'separator' },
    { label: T('Show %s', name), enabled: running, click: showFace },
    { label: T('Pair a device…'), enabled: running, click: () => showAdmin('#pair') },
    { label: T('Administer…'), enabled: running, click: () => showAdmin() },
    { type: 'separator' },
    server.state === 'stopped' || server.state === 'failed'
      ? { label: T('Start'), click: () => server.start() }
      : { label: T('Restart'), click: () => server.restart() },
    { label: T('Stop'), enabled: server.state !== 'stopped', click: () => server.stop() },
    { label: T('Show the log'), click: () => shell.openPath(server.log) },
    { label: T('Open at login'), type: 'checkbox', checked: opensAtLogin(), click: (item) => setOpensAtLogin(item.checked) },
    { type: 'separator' },
    { label: T('Quit AnyAssistant'), click: () => app.quit() },
  ];
  tray.setContextMenu(Menu.buildFromTemplate(items));
  tray.setToolTip(`AnyAssistant · ${status()}`);
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
  if (server.state === 'running') await learnName();
  if (tray) menu();
});

app.on('second-instance', () => (server.state === 'running' ? showFace() : null));
app.on('window-all-closed', (e) => e.preventDefault());  // it stays in the tray

let quitting = false;
app.on('before-quit', async (e) => {
  if (quitting) return;
  e.preventDefault();
  quitting = true;
  await server.quit();  // its own server goes with it; systemd's stays
  app.exit(0);
});

app.whenReady().then(async () => {
  permissions();
  const icon = nativeImage.createFromPath(path.join(__dirname, 'icons', 'tray.png'));
  tray = new Tray(icon);
  tray.on('click', () => (server.state === 'running' ? showFace() : null));  // Windows: a click shows it
  menu();
  await server.begin();
  if (server.state === 'running' && !opensAtLogin()) showFace();  // the first time: its face
});
