// The server and its installer get the system's language (Windows has no $LANG: they were in English).
const test = require('node:test');
const assert = require('node:assert');
const { Server } = require('../server');

test('the system language goes as LANG when there is none', () => {
  const saved = { LANG: process.env.LANG, LC_ALL: process.env.LC_ALL };
  delete process.env.LANG;
  delete process.env.LC_ALL;
  try {
    const server = Object.create(Server.prototype);
    server.systemLanguage = 'es-ES';
    assert.equal(server.environment().LANG, 'es_ES.UTF-8');
    process.env.LANG = 'en_GB.UTF-8';  // a system that has its own: kept
    assert.equal(server.environment().LANG, 'en_GB.UTF-8');
  } finally {
    for (const [k, v] of Object.entries(saved)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
  }
});
