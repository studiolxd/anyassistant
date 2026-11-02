// The app's own updates (app-updates.js): when it tells, and what the menu shows.
const test = require('node:test');
const assert = require('node:assert');
const appUpdates = require('../app-updates');

const T = (english, ...values) => values.reduce((s, v) => s.replace('%s', v), english);
const M = (english) => T(english).replace(/…\s*$/, '');

test('a version is told once', () => {
  assert.equal(appUpdates.announce('0.2.0', null), true);
  assert.equal(appUpdates.announce('0.2.0', '0.2.0'), false);
  assert.equal(appUpdates.announce('0.3.0', '0.2.0'), true);
  assert.equal(appUpdates.announce(null, null), false);
});

test('the menu: nothing, then «Update to…», then «Downloading…»', () => {
  const install = () => {};
  assert.deepEqual(appUpdates.items({ version: null }, T, M, install), []);
  const [update] = appUpdates.items({ version: '0.2.0' }, T, M, install);
  assert.equal(update.label, 'Update to version 0.2.0');
  assert.equal(update.click, install);
  const [downloading] = appUpdates.items({ version: '0.2.0', downloading: true }, T, M, install);
  assert.equal(downloading.label, 'Downloading version 0.2.0…');
  assert.equal(downloading.enabled, false);
});

test('while developing it does nothing', () => {
  const found = appUpdates.begin({ app: { isPackaged: false }, log: () => {}, changed: () => {}, notify: () => {} });
  assert.deepEqual(found.state, { version: null, downloading: false });
});
