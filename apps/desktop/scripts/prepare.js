// Before packaging (npm run dist): what the app carries inside.
//   build/program   the server (the committed files it needs, and VERSION «<commits>-<hash>»)
//   build/uv        uv for this system (Python and the packages, the first time it runs)
// Run on the system it packages for (GitHub Actions: Windows and Linux).
//   --program-only  only build/program: the release's AnyAssistant-program.tar.gz (install.sh without a copy)

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const UV = '0.13.6';  // github.com/astral-sh/uv/releases
const here = path.resolve(__dirname, '..');
const root = path.resolve(here, '..', '..');
const build = path.join(here, 'build');
const git = (...args) => execFileSync('git', ['-C', root, ...args], { encoding: 'utf8' }).trim();

fs.rmSync(build, { recursive: true, force: true });
fs.mkdirSync(path.join(build, 'program'), { recursive: true });
fs.mkdirSync(path.join(build, 'uv'), { recursive: true });

// The program: only what the server uses (not the phone and watch apps).
const parts = ['server', 'plugins', 'bin', 'locales', 'install.sh', 'pyproject.toml', 'uv.lock', '.python-version',
               'README.md', 'settings.example.json', 'permissions.example.json', '.mcp.example.json'];
const tar = path.join(build, 'program.tar');
git('archive', '--format=tar', '-o', tar, 'HEAD', '--', ...parts);
execFileSync('tar', ['-xf', tar, '-C', path.join(build, 'program')]);
fs.rmSync(tar);
const version = `${git('rev-list', '--count', 'HEAD')}-${git('rev-parse', '--short', 'HEAD')}`;
fs.writeFileSync(path.join(build, 'program', 'VERSION'), version + '\n');
if (process.argv.includes('--program-only')) {
  console.log(`program ${version}`);
  process.exit(0);
}

// uv for this system.
const arch = os.arch() === 'arm64' ? 'aarch64' : 'x86_64';
const target = process.platform === 'win32' ? `${arch}-pc-windows-msvc` : `${arch}-unknown-linux-gnu`;
const file = `uv-${target}.${process.platform === 'win32' ? 'zip' : 'tar.gz'}`;
const archive = path.join(build, file);
execFileSync('curl', ['-fsSL', '-o', archive, `https://github.com/astral-sh/uv/releases/download/${UV}/${file}`]);
execFileSync('tar', ['-xf', archive, '-C', path.join(build, 'uv')]);  // Windows' tar opens .zip too
fs.rmSync(archive);
// The .tar.gz has it in a folder: uv (and uvx) at the top.
for (const entry of fs.readdirSync(path.join(build, 'uv'))) {
  const inner = path.join(build, 'uv', entry);
  if (fs.statSync(inner).isDirectory()) {
    for (const f of fs.readdirSync(inner)) fs.renameSync(path.join(inner, f), path.join(build, 'uv', f));
    fs.rmSync(inner, { recursive: true });
  }
}
console.log(`program ${version}, uv ${UV} (${target}):`, fs.readdirSync(path.join(build, 'uv')).join(', '));
