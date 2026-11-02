// The community's updates (updates.js): announced once per notice, and where a click goes.
//
//   node --test apps/desktop/test/

const test = require('node:test');
const assert = require('node:assert');
const updates = require('../updates');

const T = (english, ...values) => values.reduce((text, v) => text.replace('%s', v), english);
const BEDSIDE = { kind: 'theme', id: 'bedside', name: 'Bedside', from: '1.0.0', to: '1.1.0' };
const GREETER = { kind: 'plugin', id: 'greeter', name: 'Greeter', from: '2.1', to: '2.2' };

test('a new notice is announced once', () => {
  const answer = { updates: [BEDSIDE], notice: { id: 3, updates: [BEDSIDE] } };
  assert.deepStrictEqual(updates.read(answer, 2), { pending: [BEDSIDE], notice: 3, announce: [BEDSIDE] });
  assert.deepStrictEqual(updates.read(answer, 3), { pending: [BEDSIDE], notice: null, announce: [] });
  assert.deepStrictEqual(updates.read(answer, undefined).notice, 3);  // never shown one: this one
});

test('nothing waiting, the plugin off, or an error: nothing to show', () => {
  assert.deepStrictEqual(updates.read({ updates: [], notice: null }, 0), { pending: [], notice: null, announce: [] });
  assert.deepStrictEqual(updates.read({ error: 'only the owner' }, 0), { pending: [], notice: null, announce: [] });
  assert.deepStrictEqual(updates.read(null, 0), { pending: [], notice: null, announce: [] });
});

test('installed meanwhile: the notice is remembered, nothing announced', () => {
  const read = updates.read({ updates: [], notice: { id: 4, updates: [] } }, 3);
  assert.strictEqual(read.notice, 4);
  assert.deepStrictEqual(read.announce, []);
});

test('what it says, and where a click goes', () => {
  assert.strictEqual(updates.sentence([BEDSIDE], T), 'There\'s an update of Bedside (1.1.0)');
  assert.strictEqual(updates.sentence([BEDSIDE, GREETER], T), 'There are updates of 2 themes and plugins');
  assert.strictEqual(updates.place([BEDSIDE]), 'themes');
  assert.strictEqual(updates.place([BEDSIDE, GREETER]), 'plugins');
  assert.strictEqual(updates.place([GREETER]), 'plugins');
});
