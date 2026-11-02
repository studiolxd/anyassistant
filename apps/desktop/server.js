// The server, run by the app (as the Mac app does): it finds the program and your data, adopts a
// server already running (Linux's systemd service, another start), or starts its own and keeps
// an eye on it. Stopped cleanly through /admin/stop (Windows has no signals for it). «Restart» by
// voice (or the admin page's): the server it started ends with RESTART (it asks for it in
// ANYASSISTANT_RESTART_EXIT) and the app starts it again, not counted as a failure (on Windows
// os.execv would be another process, out of the app's sight).

const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { EventEmitter } = require('events');

const home = os.homedir();
const WINDOWS = process.platform === 'win32';
const RESTART = 75;  // the exit code of a server that asks to be started again

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
    // An installed copy says where its data is (as install.sh does): bin/anyassistant reads it too.
    if (process.env.ANYASSISTANT_PROGRAM === this.program && !exists(path.join(this.program, 'install.env'))) {
      fs.writeFileSync(path.join(this.program, 'install.env'),
        `# Where this copy keeps your data (the AnyAssistant app wrote it).\nANYASSISTANT_HOME="${this.data}"\nANYASSISTANT_CACHE="${this.cache}"\n`);
    }
    this.unit = path.join(home, '.config', 'systemd', 'user', 'anyassistant.service');
    this.venv = path.join(this.program, '.venv', WINDOWS ? 'Scripts' : 'bin', WINDOWS ? 'python.exe' : 'python');
  }

  // Installed (as the Mac app sees it): its Python is made and the installer's steps were gone
  // through (install.env, which the app writes with where your data is; developing from the
  // project, uv sync made the environment: no steps to go through). Not yet: the app shows the
  // installer's window instead of the menu.
  get installed() {
    return exists(this.venv) && (exists(path.join(this.program, 'install.env')) || !process.env.ANYASSISTANT_PROGRAM);
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

  // Every few seconds (as the Mac app polls it): one adopted (systemd's, another start) that stops
  // answering is «stopped»; one that answers again (restarted by hand) is running.
  async check() {
    if (this.child || this.state === 'starting') return;
    const up = await this.answers();
    if (this.state === 'running' && !up) this.set('stopped');
    else if (this.state !== 'running' && up && !this.stopping) { this.ours = false; this.set('running'); }
  }

  // uv: the app's own (packaged), or the one installed on this computer.
  uv() {
    return [process.env.UV, path.join(home, '.local', 'bin', WINDOWS ? 'uv.exe' : 'uv'),
            path.join(home, '.cargo', 'bin', WINDOWS ? 'uv.exe' : 'uv')].find((p) => p && exists(p)) || 'uv';
  }

  // The program's Python, to run a script of the server's: [command, arguments before the script].
  python() {
    // The app's own uv (packaged): its environment kept up to date with the program (uv.lock) each start.
    if (process.env.UV) return [process.env.UV, ['run', '--frozen', '--project', this.program, 'python']];
    if (exists(this.venv) && exists(path.join(this.program, 'install.env'))) return [this.venv, []];
    // Developing (or not prepared yet): uv makes the environment and runs it.
    return [this.uv(), ['run', '--project', this.program, 'python']];
  }

  environment() {
    // The system's language for the server and its installer (its steps' texts, the language it
    // proposes): Windows has no $LANG, nor does a Linux desktop session at times (main.js: app.getLocale).
    const locale = (this.systemLanguage || '').replace('-', '_');
    const language = !process.env.LANG && !process.env.LC_ALL && locale ? { LANG: `${locale}.UTF-8` } : {};
    return { ...process.env, ...language, ANYASSISTANT_APP: '1', ANYASSISTANT_HOME: this.data, ANYASSISTANT_CACHE: this.cache,
             ANYASSISTANT_RESTART_EXIT: String(RESTART), PYTHONUNBUFFERED: '1', PYTHONUTF8: '1' };
  }

  // Runs a program to the end: its output, line by line, to «line»; the exit code (-1: it couldn't run).
  run(command, args, line) {
    return new Promise((done) => {
      let child;
      try {
        child = spawn(command, args, { cwd: this.program, env: this.environment(), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
      } catch (e) { return done(-1); }
      let pending = '';
      const read = (chunk) => {
        pending += chunk.toString('utf8');
        let at;
        while ((at = pending.indexOf('\n')) >= 0) {
          if (line) line(pending.slice(0, at).replace(/\r$/, ''));
          pending = pending.slice(at + 1);
        }
      };
      child.stdout.on('data', read);
      child.stderr.on('data', read);
      child.on('error', () => done(-1));
      child.on('exit', (code) => { if (pending && line) line(pending); done(code === null ? -1 : code); });
    });
  }

  // The installer's window (as the Mac's Setup.swift): the program's Python first («Preparing
  // the installation…»: uv makes the environment), then the installer's steps through their JSON.
  prepare(line) {
    fs.mkdirSync(this.cache, { recursive: true });
    fs.mkdirSync(this.data, { recursive: true });
    if (!process.env.ANYASSISTANT_PROGRAM && exists(this.venv)) return Promise.resolve(0);  // developing: uv sync did it
    return this.run(this.uv(), ['sync', '--frozen', '--no-dev', '--project', this.program], line);
  }

  // bin/anyassistant setup, as the Mac runs it (its own Python: bin/anyassistant is a shell script, not for
  // Windows): `--list --json` lists the questions; `--json [--defaults|--set k=v…]` runs the steps,
  // one JSON event per line. The app starts the server and shows how to connect: not the installer.
  setup(args, line) {
    const [command, before] = this.python();
    const script = 'import sys; sys.path.insert(0, "server"); import installer; sys.exit(installer.main(sys.argv[1:]))';
    return this.run(command, [...before, '-c', script, ...args, '--skip', 'service', '--skip', 'connect'], line);
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
    const [command, before] = this.python();
    this.stopping = false;
    this.ours = true;
    this.set('starting');
    try {
      this.child = spawn(command, [...before, 'server/main.py'], {
        cwd: this.program, stdio: ['ignore', out, out], windowsHide: true, env: this.environment(),
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
    if (code === RESTART) return this.start();  // «reinicia»: it asked to be started again (not a failure)
    this.set('failed', 'crashed');  // «It stopped; starting it again…» (as the Mac says)
    await new Promise((r) => setTimeout(r, 4000));
    if (this.child || this.stopping) return;  // started or stopped by hand meanwhile
    if (await this.answers()) { this.ours = false; return this.set('running'); }  // another one has its port
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
