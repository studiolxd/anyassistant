// The app's own look at the microphone (microphone.js), with the samples of the plugin
// «microphone-busy»'s tests (tests/test_microphone_busy.py): the same rules in both.
//
//   node --test apps/desktop/test/

const test = require('node:test');
const assert = require('node:assert');
const microphone = require('../microphone');

test('Windows: the entries in use are the ones not stopped', () => {
  const entries = [
    ['Microsoft.Teams_8wekyb3d8bbwe', 133000000000000000n, 0n],  // a packaged app, recording now
    ['Microsoft.WindowsCamera_8wekyb3d8bbwe', 133000000000000000n, 133000000001000000n],  // done
    ['NonPackaged\\C:#Users#me#AppData#Roaming#Zoom#bin#Zoom.exe', 133000000000000000n, 0n],
    ['NonPackaged\\C:#Program Files#Google#Chrome#Application#chrome.exe', 0n, 0n],  // never used
    ['NonPackaged\\C:#Users#me#AppData#Local#Programs#AnyAssistant#AnyAssistant.exe', 133000000000000000n, 0n],  // ours
  ];
  assert.deepStrictEqual(microphone.windowsBusy(entries), ['Microsoft.Teams', 'Zoom']);
});

const STORE = 'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone';
const REG = [
  '',
  STORE,
  '    Value    REG_SZ    Allow',
  '',
  STORE + '\\Microsoft.Teams_8wekyb3d8bbwe',
  '    Value    REG_SZ    Allow',
  '    LastUsedTimeStart    REG_QWORD    0x1d8f3a2b4c5d6e7',
  '    LastUsedTimeStop    REG_QWORD    0x0',
  '',
  STORE + '\\Microsoft.WindowsCamera_8wekyb3d8bbwe',
  '    LastUsedTimeStart    REG_QWORD    0x1d8f3a2b4c5d6e7',
  '    LastUsedTimeStop    REG_QWORD    0x1d8f3a2b4c5d6f0',
  '',
  STORE + '\\NonPackaged',
  '',
  STORE + '\\NonPackaged\\C:#Users#me#AppData#Roaming#Zoom#bin#Zoom.exe',
  '    LastUsedTimeStart    REG_QWORD    0x1d8f3a2b4c5d6e7',
  '    LastUsedTimeStop    REG_QWORD    0x0',
  '',
  STORE + '\\NonPackaged\\C:#Users#me#AppData#Local#Programs#AnyAssistant#AnyAssistant.exe',
  '    LastUsedTimeStart    REG_QWORD    0x1d8f3a2b4c5d6e7',
  '    LastUsedTimeStop    REG_QWORD    0x0',
  '',
].join('\r\n');

test('Windows: reg query\'s listing gives the consent store\'s keys', () => {
  const entries = microphone.registryEntries(REG);
  assert.deepStrictEqual(entries.map((e) => e[0]), [
    'Microsoft.Teams_8wekyb3d8bbwe', 'Microsoft.WindowsCamera_8wekyb3d8bbwe',
    'NonPackaged\\C:#Users#me#AppData#Roaming#Zoom#bin#Zoom.exe',
    'NonPackaged\\C:#Users#me#AppData#Local#Programs#AnyAssistant#AnyAssistant.exe',
  ]);
  assert.strictEqual(entries[0][2], 0n);
  assert.deepStrictEqual(microphone.windowsBusy(entries), ['Microsoft.Teams', 'Zoom']);
  assert.deepStrictEqual(microphone.registryEntries(''), []);
});

const PW_DUMP = JSON.stringify([
  { id: 60, type: 'PipeWire:Interface:Node', info: { state: 'running', props: {
    'media.class': 'Stream/Input/Audio', 'application.name': 'ZOOM VoiceEngine',
    'application.process.binary': 'zoom', 'application.process.id': 4242 } } },
  { id: 61, type: 'PipeWire:Interface:Node', info: { state: 'running', props: {
    'media.class': 'Stream/Input/Audio', 'application.name': 'Chromium',
    'application.process.binary': 'anyassistant' } } },  // our own app's page
  { id: 62, type: 'PipeWire:Interface:Node', info: { state: 'suspended', props: {
    'media.class': 'Stream/Input/Audio', 'application.name': 'Audacity' } } },
  { id: 63, type: 'PipeWire:Interface:Node', info: { state: 'running', props: {
    'media.class': 'Stream/Output/Audio', 'application.name': 'Firefox' } } },
]);

test('Linux: PipeWire\'s running input streams', () => {
  assert.deepStrictEqual(microphone.pipewireBusy(PW_DUMP), ['ZOOM VoiceEngine']);
  assert.deepStrictEqual(microphone.pipewireBusy('not json'), []);
});

const PACTL = `Source Output #12
\tDriver: protocol-native.c
\tCorked: no
\tProperties:
\t\tapplication.name = "Firefox"
\t\tapplication.process.binary = "firefox"
Source Output #13
\tCorked: yes
\tProperties:
\t\tapplication.name = "Audacity"
Source Output #14
\tCorked: no
\tProperties:
\t\tapplication.name = "Chromium"
\t\tapplication.process.binary = "anyassistant"
`;

test('Linux: PulseAudio\'s uncorked source outputs', () => {
  assert.deepStrictEqual(microphone.pulseBusy(PACTL), ['Firefox']);
  assert.deepStrictEqual(microphone.pulseBusy(''), []);
});

test('it waits before pausing and before resuming', () => {
  const watch = new microphone.Watch();
  assert.strictEqual(watch.tick(['Zoom'], 0.0), null);
  assert.strictEqual(watch.tick(['Zoom'], 0.5), null);
  assert.strictEqual(watch.tick([], 0.7), null);  // a moment's change: forgotten
  assert.strictEqual(watch.tick(['Zoom'], 1.0), null);
  assert.strictEqual(watch.tick(['Zoom'], 2.1), 'busy');
  assert.strictEqual(watch.program, 'Zoom');
  assert.strictEqual(watch.tick([], 3.0), null);
  assert.strictEqual(watch.tick([], 4.5), null);
  assert.strictEqual(watch.tick([], 5.1), 'free');
});

test('looking stopped: free at once', () => {
  const watch = new microphone.Watch();
  assert.strictEqual(watch.reset(), null);
  watch.tick(['Zoom'], 0);
  watch.tick(['Zoom'], 1.5);
  assert.strictEqual(watch.busy, true);
  assert.strictEqual(watch.reset(), 'free');
  assert.strictEqual(watch.busy, false);
});

test('our own app is left out by its name, and this executable\'s', () => {
  assert.ok(microphone.ours('C:\\Users\\me\\AppData\\Local\\Programs\\AnyAssistant\\AnyAssistant.exe'));
  assert.ok(microphone.ours(process.execPath));  // node here; electron (developing) or AnyAssistant in the app
  assert.ok(!microphone.ours('zoom'));
  assert.ok(!microphone.ours(''));
});
