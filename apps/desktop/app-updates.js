// The app's own updates (electron-updater), as the Mac's Sparkle: every few hours it looks at the
// latest release on GitHub (its latest.yml, latest-linux.yml: apps/release.sh); a newer version is
// a notification, once per version, and an item in the tray's menu: «Actualizar a la versión
// 0.2.0…» downloads it, installs it and opens the new one (which updates the server it carries, as
// on any start). Nothing is installed by itself. Not while developing (only the packaged app), and
// on Linux only the AppImage and the .deb update themselves.

const EVERY = 6 * 3600 * 1000;  // how often it looks

/// Whether a version found is to be told (a notification): only once each.
function announce(version, told) {
  return Boolean(version) && version !== told;
}

/// What the menu shows: nothing; «Downloading 0.2.0…»; or «Update to version 0.2.0…».
function items(state, T, M, install) {
  if (state.downloading) return [{ label: T('Downloading version %s…', state.version), enabled: false }];
  if (state.version) return [{ label: M('Update to version %s…').replace('%s', state.version), click: install }];
  return [];
}

/// Starts looking (the packaged app only). `changed`: the menu again; `notify(version)`: its notification.
function begin({ app, log, changed, notify }) {
  const state = { version: null, downloading: false };
  if (!app.isPackaged) return { state, check: () => {}, install: () => {} };
  const { autoUpdater } = require('electron-updater');
  autoUpdater.autoDownload = false;  // only when asked
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.logger = { info: () => {}, warn: (m) => log(`updates: ${m}`), error: (m) => log(`updates: ${m}`), debug: () => {} };
  autoUpdater.on('update-available', (info) => {
    state.version = info.version;
    changed();
    notify(info.version);
  });
  autoUpdater.on('error', (e) => {
    log(`updates: ${e && e.message}`);
    if (state.downloading) { state.downloading = false; changed(); }
  });
  autoUpdater.on('update-downloaded', () => autoUpdater.quitAndInstall(false, true));  // installs and opens it
  const check = () => autoUpdater.checkForUpdates().catch((e) => log(`updates: ${e && e.message}`));
  const install = () => {
    if (!state.version || state.downloading) return;
    state.downloading = true;
    changed();
    autoUpdater.downloadUpdate().catch((e) => {
      log(`updates: ${e && e.message}`);
      state.downloading = false;
      changed();
    });
  };
  setTimeout(check, 30 * 1000);  // a moment after starting
  setInterval(check, EVERY);
  return { state, check, install };
}

module.exports = { announce, items, begin };
