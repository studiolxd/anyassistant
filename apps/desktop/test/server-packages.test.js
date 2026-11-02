// The server's packages: installing again keeps the plugins' (--inexact), and a new version gets
// its plugins' packages before the server starts (as the Mac's update does).
const test = require('node:test');
const assert = require('node:assert');
const { Server } = require('../server');

function fake() {
  const server = Object.create(Server.prototype);
  Object.assign(server, { program: '/p', cache: require('os').tmpdir(), data: require('os').tmpdir(), venv: '/nowhere', calls: [] });
  server.run = (command, args) => { server.calls.push(args); return Promise.resolve(0); };
  server.set = () => {};
  server.answers = async () => false;
  server.start = async () => { server.calls.push(['start']); };
  return server;
}

test('installing again keeps the plugins\' packages', async () => {
  const saved = process.env.ANYASSISTANT_PROGRAM;
  process.env.ANYASSISTANT_PROGRAM = '/p';
  try {
    const server = fake();
    await server.prepare(() => {});
    assert.ok(server.calls[0].includes('--inexact'));
  } finally {
    if (saved === undefined) delete process.env.ANYASSISTANT_PROGRAM; else process.env.ANYASSISTANT_PROGRAM = saved;
  }
});

test('after an update, the plugins\' packages before the server', async () => {
  const server = fake();
  server.updated = true;
  await server.begin();
  assert.ok(server.calls[0].includes('packages'));
  assert.deepEqual(server.calls[1], ['start']);
  server.calls = [];
  await server.begin();  // the next start: straight away
  assert.deepEqual(server.calls, [['start']]);
});
