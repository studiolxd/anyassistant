// The phone's client: microphone and camera to the Mac, the Mac's audio to the speaker.
// Plain JS without a bundler, for old Chrome versions (81 on Android 4.4).
// The texts (in the active language) and the settings come from the server (/config).

var pc = null;
var channel = null;
var statusLine = document.getElementById('status');
var stats = document.getElementById('stats');
var rtt = null;
var T = {};  // texts of the active language (locale «ui»)
var settings = {};  // name, face, video

function text(key, values) {
  var s = T[key] || key;
  for (var name in values || {}) s = s.split('{' + name + '}').join(values[name]);
  return s;
}

// Texts and settings; again after reconnecting, in case they changed («speak English», a restart).
function loadTexts() {
  return fetch('/config').then(function (r) { return r.json(); }).then(function (data) {
    T = data.ui;
    settings = data;
    document.documentElement.lang = data.lang;
    document.title = data.name;
    Face.language(data.lang);
    Face.kind(data.face);
    showScreen(data.screen || {});
  });
}

// What the screen shows (settings show_time, show_date, show_stats, clock…).
var screen = {};
function showScreen(s) {
  screen = s;
  var hide = { 'hide-time': s.show_time === false, 'hide-date': s.show_date === false, 'hide-stats': !s.show_stats };
  for (var name in hide) document.body.classList.toggle(name, hide[name]);
  Face.clock(s.clock);
}

// Loads the texts and then shows the start button (or the demo, or the pairing form).
loadTexts().then(function () {
  if (!settings.paired) return askForCode();
  var start = document.getElementById('start');
  start.textContent = text('start');
  statusLine.textContent = text('connecting');
  if (new URLSearchParams(location.search).has('demo')) demo();
  else start.hidden = false;
});

// Pairing (settings «pairing»): the code that «bin/jarvis pair» shows on the Mac.
function askForCode() {
  var form = document.getElementById('pair');
  document.getElementById('pair-prompt').textContent = text('pair_prompt');
  document.getElementById('pair-button').textContent = text('pair_button');
  form.hidden = false;
  form.onsubmit = function (ev) {
    ev.preventDefault();
    fetch('/pair', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: document.getElementById('pair-code').value })
    }).then(function (r) {
      if (r.ok) location.reload();
      else document.getElementById('pair-error').textContent = text('pair_wrong');
    });
  };
}

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

// Camera constraints for each quality.
var VIDEO = {
  normal: { facingMode: 'user', width: 640, height: 480, frameRate: 15 },
  low: { facingMode: 'user', width: 320, height: 240, frameRate: 10 },
  off: false
};

// ?video= on this device, else the settings' video, else «auto»: low with ≤ 1 GB of RAM.
function videoQuality() {
  var asked = new URLSearchParams(location.search).get('video');
  if (asked in VIDEO) return asked;
  if (settings.video in VIDEO) return settings.video;
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
    await loadTexts();  // before the states arrive, which show them
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
    if (response.status === 403) {  // unpaired meanwhile (bin/jarvis unpair)
      shutDown = true;
      fail(text('pair_needed'));
      return;
    }
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
  if (state === 'asleep') {
    statusLine.textContent = screen.show_hint === false ? '' : text('asleep', { wake: wakePhrase || 'Hey Jarvis' });
  } else {
    statusLine.textContent = screen.show_status === false && state !== 'error' ? '' : text(state);
  }
  Face.state(state);
  photoFollows(state);
  if (state === 'asleep' && !camera.hidden) showCamera(false);
}

function message(m) {
  if (m.type === 'pong') rtt = Math.round(performance.now() - m.t);
  else if (m.type === 'state') showState(m.state, m.wake_phrase);
  else if (m.type === 'text') caption(m);
  else if (m.type === 'config') loadTexts();  // the settings changed
  else if (m.type === 'look') showPhoto(m.at);
  else if (m.type === 'camera') showCamera(m.on);
  else if (m.type === 'photo') takePhoto(m.id);
}

// «Turn on the camera»: what this device's camera sees, live, like a mirror (the same
// stream it already sends, so no extra load); «turn off the camera» hides it.
// Also hidden when it goes to sleep.
var camera = document.getElementById('camera');
function showCamera(on) {
  var video = media && media.getVideoTracks().length;
  if (on && video) {
    camera.srcObject = media;
    camera.hidden = false;
  } else {
    camera.hidden = true;
    camera.srcObject = null;
  }
}

// «Read this»: a photo at the camera's full resolution (the video may be 320×240).
// ImageCapture where it works; else the camera at its largest size for a moment
// (then back); else a frame of the video as it is. ?how= tells the server which.
function takePhoto(id) {
  var track = media && media.getVideoTracks()[0];
  if (!track) return;
  var send = function (how) {
    return function (blob) { fetch('/photo?id=' + id + '&how=' + how, { method: 'POST', body: blob }); };
  };
  if (!('ImageCapture' in window)) return largest(track, send);
  var camera = new ImageCapture(track);
  var video = track.getSettings().width || 0;
  camera.getPhotoCapabilities().then(function (can) {
    // Without asking for a size, some devices take it at the video's (240×320).
    return camera.takePhoto({ imageWidth: can.imageWidth.max, imageHeight: can.imageHeight.max });
  }).then(function (blob) {
    return createImageBitmap(blob).then(function (bitmap) {
      if (Math.max(bitmap.width, bitmap.height) > Math.max(video, 640)) send('photo')(blob);
      else largest(track, send);  // no bigger than the video: try the other way
    });
  }).catch(function () { largest(track, send); });
}

function largest(track, send) {
  var can = track.getCapabilities && track.applyConstraints ? track.getCapabilities() : {};
  if (!can.width || !can.width.max) return videoFrame(track, send('video'));
  var before = track.getConstraints();
  track.applyConstraints({ width: can.width.max, height: can.height.max }).then(function () {
    setTimeout(function () {  // the camera needs a moment to switch
      videoFrame(track, function (blob) {
        track.applyConstraints(before).catch(function () {});
        send('largest')(blob);
      });
    }, 800);
  }).catch(function () { videoFrame(track, send('video')); });
}

function videoFrame(track, send) {
  var video = document.createElement('video');
  video.muted = true;
  video.srcObject = new MediaStream([track]);
  video.onplaying = function () {
    var canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    video.srcObject = null;
    canvas.toBlob(send, 'image/jpeg', 0.92);
  };
  video.play();
}

// What it looks at through the camera, with a scanning sweep while it thinks about it;
// it fades out once it starts answering.
var photo = document.getElementById('photo');
function showPhoto(at) {
  var img = photo.querySelector('img');
  img.onload = function () { photo.hidden = false; photo.className = 'scanning'; };
  img.src = '/eyes.jpg?t=' + at;
}
function photoFollows(state) {
  if (photo.hidden || state === 'looking' || state === 'thinking') return;
  photo.className = 'done';
  setTimeout(function () { if (photo.className === 'done') photo.hidden = true; }, 1500);
}

// Answers arrive in pieces with the same id: the same paragraph is updated.
function caption(m) {
  if (m.author === 'assistant' ? screen.show_answer === false : screen.show_heard === false) return;
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
  var history = screen.history === undefined ? 2 : screen.history;
  while (list.children.length > history + 1) list.removeChild(list.firstChild);
}

async function collectStats() {
  if (!pc || !screen.show_stats) return;
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
  var STATES = ['asleep', 'awake', 'hearing', 'looking', 'thinking', 'speaking', 'question', 'error'];
  var step = 0;
  var next = function () {
    var state = STATES[step++ % STATES.length];
    showState(state);
    if (state === 'looking') showPhoto(Date.now());  // the last photo, if there is one
    stats.textContent = 'demo: ' + state;
  };
  setInterval(function () {  // simulated voice while «hearing»
    Face.voice(Face.current() === 'hearing' ? 0.3 + 0.3 * Math.sin(Date.now() / 150) : 0);
  }, 50);
  next();
  setInterval(next, 3000);
}
