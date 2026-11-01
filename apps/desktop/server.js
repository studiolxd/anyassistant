// The server, run by the app (as the Mac app does): it finds the program and your data, adopts a
// server already running (Linux's systemd service, another start), or starts its own and keeps
// an eye on it. Stopped cleanly through /admin/stop (Windows has no signals for it).

const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { EventEmitter } = require('events');

const home = os.homedir();
const WINDOWS = process.platform === 'win32';

function exists(p) {
  try { fs.accessSync(p); return true; } catch (e) { return false; }
}

// install.env (install.sh writes it): where an installed copy keeps your data.
function installEnv(program) {
  const found = {};
  try {
    for (const line of fs.readFileSync(path.join(program, 'install.env'), 'utf8').split('\n')) {
      const m = line.match(/^(\w+)=(.*)$/);
      if (m) found[m[1]] = m[2].trim().replace(/^"|"$/g, '');
    }
  } catch (e) { /* not installed: the app says where */ }
  return found;
}

class Server extends EventEmitter {
  constructor(appDir) {
    super();
    this.state = 'stopped';  // stopped, starting, running, failed
    this.why = '';
    this.child = null;
    this.ours = false;  // started by this app (not systemd, not another)
    this.stopping = false;
    this.crashes = [];
    // The program: $ANYASSISTANT_PROGRAM, an installed copy, or this project (developing).
    const candidates = [
      process.env.ANYASSISTANT_PROGRAM,
      WINDOWS ? path.join(process.env.LOCALAPPDATA || '', 'AnyAssistant', 'program') : path.join(home, '.local', 'opt', 'AnyAssistant'),
      path.resolve(appDir, '..', '..'),
    ].filter(Boolean);
    this.program = candidates.find((p) => exists(path.join(p, 'server', 'main.py'))) || candidates[candidates.length - 1];
    const installed = installEnv(this.program);
    // Your data and what can be rebuilt: the installed copy's, or each system's place.
    this.data = process.env.ANYASSISTANT_HOME || installed.ANYASSISTANT_HOME || (WINDOWS
      ? path.join(process.env.APPDATA || home, 'AnyAssistant')
      : process.platform === 'darwin' ? path.join(home, 'Library', 'Application Support', 'AnyAssistant')
      : path.join(process.env.XDG_DATA_HOME || path.join(home, '.local', 'share'), 'AnyAssistant'));
    this.cache = process.env.ANYASSISTANT_CACHE || installed.ANYASSISTANT_CACHE || (WINDOWS
      ? path.join(process.env.LOCALAPPDATA || home, 'AnyAssistant', 'Cache')
      : process.platform === 'darwin' ? path.join(home, 'Library', 'Caches', 'AnyAssistant')
      : path.join(process.env.XDG_CACHE_HOME || path.join(home, '.cache'), 'AnyAssistant'));
    this.log = path.join(this.cache, 'anyassistant.log');
    this.unit = path.join(home, '.config', 'systemd', 'user', 'anyassistant.service');
  }

  get port() {
    try {
      return JSON.parse(fs.readFileSync(path.join(this.data, 'settings.json'), 'utf8')).port || 8080;
    } catch (e) { return 8080; }
  }

  get url() { return `http://127.0.0.1:${this.port}`; }

  // Linux, installed with its systemd service: systemd starts and stops it.
  get systemd() {
    return process.platform === 'linux' && exists(this.unit) &&
      fs.readFileSync(this.unit, 'utf8').includes(path.join(this.program, 'bin', 'anyassistant'));
  }

  set(state, why = '') {
    this.state = state;
    this.why = why;
    this.emit('change');
  }

  async answers(timeout = 2000) {
    try {
      const r = await fetch(`${this.url}/status`, { signal: AbortSignal.timeout(timeout) });
      return r.ok;
    } catch (e) { return false; }
  }

  async call(method, route, body) {
    const r = await fetch(`${this.url}${route}`, {
      method, headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(5000),
    });
    return r.json();
  }

  // At the app's start: one already running is adopted; otherwise it starts.
  async begin() {
    if (await this.answers()) {
      this.ours = false;
      return this.set('running');
    }
    return this.start();
  }

  python() {
    const venv = path.join(this.program, '.venv', WINDOWS ? 'Scripts' : 'bin', WINDOWS ? 'python.exe' : 'python');
    if (exists(venv) && exists(path.join(this.program, 'install.env'))) return [venv, ['server/main.py']];
    // Developing (or not prepared yet): uv makes the environment and runs it.
    const uv = [process.env.UV, path.join(home, '.local', 'bin', WINDOWS ? 'uv.exe' : 'uv'),
                path.join(home, '.cargo', 'bin', WINDOWS ? 'uv.exe' : 'uv')].find((p) => p && exists(p)) || 'uv';
    return [uv, ['run', '--project', this.program, 'python', 'server/main.py']];
  }

  async start() {
    if (this.systemd) {
      try { execFileSync('systemctl', ['--user', 'start', 'anyassistant']); } catch (e) { /* says below */ }
      return this.waitUntilUp();
    }
    if (this.child) return;
    fs.mkdirSync(this.cache, { recursive: true });
    fs.mkdirSync(this.data, { recursive: true });
    const out = fs.openSync(this.log, 'a');
    const [command, args] = this.python();
    this.stopping = false;
    this.ours = true;
    this.set('starting');
    try {
      this.child = spawn(command, args, {
        cwd: this.program, stdio: ['ignore', out, out], windowsHide: true,
        env: { ...process.env, ANYASSISTANT_APP: '1', ANYASSISTANT_HOME: this.data, ANYASSISTANT_CACHE: this.cache,
               PYTHONUNBUFFERED: '1', PYTHONUTF8: '1' },
      });
    } catch (e) {
      return this.set('failed', e.message);
    }
    this.child.on('error', (e) => { this.child = null; this.set('failed', e.code === 'ENOENT' ? 'uv' : e.message); });
    this.child.on('exit', (code) => this.ended(code));
    return this.waitUntilUp();
  }

  // The first time it prepares Python and downloads the models: it may take minutes.
  async waitUntilUp(seconds = 1800) {
    this.set('starting');
    for (let i = 0; i < seconds; i += 2) {
      if (await this.answers()) return this.set('running');
      if (this.ours && !this.child) return;  // it ended: ended() says why
      await new Promise((r) => setTimeout(r, 2000));
    }
    this.set('failed', 'timeout');
  }

  async ended(code) {
    this.child = null;
    if (this.stopping) return this.set('stopped');
    // «Reinicia» by voice on Windows: the server becomes another process (os.execv). Still there?
    await new Promise((r) => setTimeout(r, 4000));
    if (await this.answers()) { this.ours = false; return this.set('running'); }
    // Ended by itself: again, unless it keeps failing (3 times in 5 minutes).
    const now = Date.now();
    this.crashes = this.crashes.filter((t) => now - t < 300000).concat(now);
    if (this.crashes.length > 3) return this.set('failed', `exit ${code}`);
    this.start();
  }

  async stop() {
    if (this.systemd) {
      try { execFileSync('systemctl', ['--user', 'stop', 'anyassistant']); } catch (e) { /* */ }
      return this.set('stopped');
    }
    this.stopping = true;
    try { await this.call('POST', '/admin/stop'); } catch (e) { /* not answering */ }
    const child = this.child;
    if (child) {
      const gone = new Promise((r) => child.once('exit', r));
      const late = new Promise((r) => setTimeout(r, 10000, 'late'));
      if (await Promise.race([gone, late]) === 'late') child.kill();
    }
    this.set('stopped');
  }

  async restart() {
    if (this.ours || !this.systemd) {
      await this.stop();
      return this.start();
    }
    try { execFileSync('systemctl', ['--user', 'restart', 'anyassistant']); } catch (e) { /* */ }
    return this.waitUntilUp();
  }

  // When the app quits: its own server goes with it (as on the Mac); systemd's stays.
  async quit() {
    if (this.ours && this.child) await this.stop();
  }
}

module.exports = { Server };
