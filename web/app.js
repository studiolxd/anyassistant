// The phone's client: microphone and camera to the Mac, the Mac's audio to the speaker.
// Plain JS without a bundler, for old Chrome versions (81 on Android 4.4).
// The texts come from the server (/i18n) in the active language.

var pc = null;
var channel = null;
var statusLine = document.getElementById('status');
var stats = document.getElementById('stats');
var rtt = null;
var T = {};  // texts of the active language (locale «ui»)

function text(key, values) {
  var s = T[key] || key;
  for (var name in values || {}) s = s.split('{' + name + '}').join(values[name]);
  return s;
}

// Loads the texts and then shows the start button (or the demo).
fetch('/i18n').then(function (r) { return r.json(); }).then(function (data) {
  T = data.ui;
  document.documentElement.lang = data.lang;
  Face.language(data.lang);
  var start = document.getElementById('start');
  start.textContent = text('start');
  statusLine.textContent = text('connecting');
  if (new URLSearchParams(location.search).has('demo')) demo();
  else start.hidden = false;
});

document.getElementById('start').onclick = function () {
  this.hidden = true;
  document.getElementById('screen').hidden = false;
  fullScreen();
  keepAwake();
  begin();
};

// Tapping the face: goes back to full screen and, if it is speaking, stops it.
document.getElementById('screen').onclick = function () {
  if (!document.fullscreenElement) fullScreen();
  if (channel && channel.readyState === 'open') channel.send(JSON.stringify({ type: 'tap' }));
};

function fullScreen() {
  var el = document.documentElement;
  if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
}

function keepAwake() {
  if (!('wakeLock' in navigator)) return;
  var request = function () {
    navigator.wakeLock.request('screen').catch(function () {});
  };
  request();
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') request();
  });
}

// ?video=normal|low|off; by default, low on devices with ≤ 1 GB of RAM.
var VIDEO = {
  normal: { facingMode: 'user', width: 640, height: 480, frameRate: 15 },
  low: { facingMode: 'user', width: 320, height: 240, frameRate: 10 },
  off: false
};

function videoQuality() {
  var asked = new URLSearchParams(location.search).get('video');
  if (asked in VIDEO) return asked;
  return (navigator.deviceMemory || 2) <= 1 ? 'low' : 'normal';
}

var media = null;
var retry = null;

// A single connected tab: when one starts, the others shut down.
var tabs = 'BroadcastChannel' in window ? new BroadcastChannel('jarvis') : null;
var shutDown = false;
if (tabs) tabs.onmessage = function (ev) {
  if (ev.data !== 'starting' || !media) return;
  shutDown = true;
  clearTimeout(retry);
  if (pc) pc.close();
  media.getTracks().forEach(function (t) { t.stop(); });
  fail(text('other_tab'));
};

async function begin() {
  if (tabs) tabs.postMessage('starting');
  try {
    media = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: VIDEO[videoQuality()]
    });
  } catch (e) {
    fail(text('no_media', { error: e.name }));
    return;
  }
  levelMeter(media);
  setInterval(ping, 1000);
  setInterval(collectStats, 2000);
  connect();
}

// If the server restarts or the Wi-Fi drops, it reconnects without reloading the page.
function reconnect() {
  if (retry || shutDown) return;
  fail(text('connection_lost'));
  retry = setTimeout(function () { retry = null; connect(); }, 2000);
}

async function connect() {
  if (pc) pc.close();
  pc = new RTCPeerConnection({ iceServers: [] });
  var current = pc;
  media.getAudioTracks().forEach(function (t) { pc.addTrack(t, media); });
  media.getVideoTracks().forEach(function (t) {
    pc.addTransceiver(t, { direction: 'sendonly', streams: [media] });
  });

  channel = pc.createDataChannel('control');
  channel.onmessage = function (ev) { message(JSON.parse(ev.data)); };

  pc.ontrack = function (ev) {
    var stream = ev.streams[0] || new MediaStream([ev.track]);
    document.getElementById('speaker').srcObject = stream;
    Face.speaker(stream);  // so the mouth follows its voice
  };
  pc.onconnectionstatechange = function () {
    if (current !== pc) return;
    if (pc.connectionState === 'connected' && Face.current() === 'error') {
      Face.state('connected');
      statusLine.textContent = text('connected');
    } else if (pc.connectionState === 'failed') {
      reconnect();
    } else if (pc.connectionState === 'disconnected') {
      // It usually recovers by itself in a few seconds; only reconnect if not.
      setTimeout(function () {
        if (current === pc && pc.connectionState === 'disconnected') reconnect();
      }, 5000);
    }
  };

  try {
    await pc.setLocalDescription(await pc.createOffer());
    await iceGathered(pc);
    var abort = new AbortController();
    setTimeout(function () { abort.abort(); }, 15000);
    var response = await fetch('/offer', {
      method: 'POST',
      signal: abort.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type })
    });
    await pc.setRemoteDescription(await response.json());
  } catch (e) {
    if (current === pc) reconnect();
  }
}

// On the local network there's no need for trickle ICE: wait for all the candidates.
function iceGathered(pc) {
  return new Promise(function (resolve) {
    if (pc.iceGatheringState === 'complete') return resolve();
    pc.addEventListener('icegatheringstatechange', function () {
      if (pc.iceGatheringState === 'complete') resolve();
    });
    setTimeout(resolve, 2000);
  });
}

function ping() {
  if (channel && channel.readyState === 'open') channel.send(JSON.stringify({ type: 'ping', t: performance.now() }));
}

function showState(state, wakePhrase) {
  statusLine.textContent = state === 'asleep' ? text('asleep', { wake: wakePhrase || 'Hey Jarvis' }) : text(state);
  Face.state(state);
}

function message(m) {
  if (m.type === 'pong') rtt = Math.round(performance.now() - m.t);
  else if (m.type === 'state') showState(m.state, m.wake_phrase);
  else if (m.type === 'text') caption(m);
}

// Answers arrive in pieces with the same id: the same paragraph is updated.
function caption(m) {
  var list = document.getElementById('captions');
  var p = m.id && document.getElementById('answer-' + m.id);
  if (p) {
    p.textContent = m.text;
    return;
  }
  p = document.createElement('p');
  p.textContent = m.text;
  if (m.id) p.id = 'answer-' + m.id;
  if (m.author === 'assistant') p.className = 'assistant';
  list.appendChild(p);
  while (list.children.length > 3) list.removeChild(list.firstChild);
}

async function collectStats() {
  if (!pc) return;
  var report = await pc.getStats();
  var jitter = null, lost = null;
  report.forEach(function (s) {
    if (s.type === 'inbound-rtp' && s.kind === 'audio') {
      jitter = Math.round(s.jitter * 1000);
      lost = s.packetsLost;
    }
  });
  stats.textContent = 'RTT ' + rtt + ' ms · jitter ' + jitter + ' ms · lost ' + lost;
}

// The face reacts to the microphone's volume.
function levelMeter(media) {
  var context = new AudioContext();
  var analyser = context.createAnalyser();
  analyser.fftSize = 512;
  context.createMediaStreamSource(media).connect(analyser);
  var buffer = new Uint8Array(analyser.fftSize);
  (function loop() {
    analyser.getByteTimeDomainData(buffer);
    var peak = 0;
    for (var i = 0; i < buffer.length; i++) peak = Math.max(peak, Math.abs(buffer[i] - 128));
    Face.voice(peak / 128);
    requestAnimationFrame(loop);
  })();
}

function fail(message) {
  Face.state('error');
  statusLine.textContent = message;
}

// ?demo: without connecting, cycles through every state to see the face (?demo&face=orb).
function demo() {
  document.getElementById('screen').hidden = false;
  var STATES = ['asleep', 'awake', 'hearing', 'thinking', 'speaking', 'question', 'error'];
  var step = 0;
  var next = function () {
    var state = STATES[step++ % STATES.length];
    showState(state);
    stats.textContent = 'demo: ' + state;
  };
  setInterval(function () {  // simulated voice while «hearing»
    Face.voice(Face.current() === 'hearing' ? 0.3 + 0.3 * Math.sin(Date.now() / 150) : 0);
  }, 50);
  next();
  setInterval(next, 3000);
}
