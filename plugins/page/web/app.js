// The phone's client: microphone and camera to the Mac, the Mac's audio to the speaker.
// Plain JS without a bundler, for old Chrome versions (81 on Android 4.4).
// The texts (in the active language) and the settings come from the server (/config).

var pc = null;
var channel = null;
var rtt = null;
var T = {};  // texts of the active language (locale «ui», and the theme's own)
var settings = {};  // name, theme, video, screen…
var lastState = 'connecting';

// A message to the Mac, on the call's control channel.
function tell(m) {
  if (channel && channel.readyState === 'open') channel.send(JSON.stringify(m));
}

// The theme's blocks (they may be missing: a theme shows what it wants).
function setText(name, value) {
  var box = Theme.block(name);
  if (box) box.textContent = value;
}
function status(value) { setText('status', value); }

// This device's own id, kept: the server tells devices apart (several at once), and a device
// that connects again replaces its old connection instead of counting as another.
function deviceId() {
  try {
    var id = localStorage.getItem('device');
    if (!id) {
      id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
      localStorage.setItem('device', id);
    }
    return id;
  } catch (e) {
    return '';
  }
}

// This device's own theme: ?theme= (remembered; ?theme=default forgets it), or the one in the settings.
function deviceTheme(name) {
  var asked = new URLSearchParams(location.search).get('theme');
  try {
    if (name === 'default') localStorage.removeItem('theme');
    else if (name !== undefined) localStorage.setItem('theme', name);
    return (asked !== 'default' && asked) || localStorage.getItem('theme') || '';
  } catch (e) {
    return asked !== 'default' && asked || '';
  }
}
(function () {
  var params = new URLSearchParams(location.search);
  if (params.get('theme') && !params.has('demo')) deviceTheme(params.get('theme'));  // the themes page's views don't
})();

function text(key, values) {
  var s = T[key] || key;
  for (var name in values || {}) s = s.split('{' + name + '}').join(values[name]);
  return s;
}

// Texts, settings and theme; again after reconnecting, in case they changed («speak English», a restart).
function loadTexts() {
  var theme = deviceTheme();
  return fetch('/config' + (theme ? '?theme=' + encodeURIComponent(theme) : '')).then(function (r) {
    return r.json();
  }).then(function (data) {
    T = {};
    for (var key in data.ui) T[key] = data.ui[key];
    for (key in data.theme.ui) T[key] = data.theme.ui[key];  // the theme may say it its way
    settings = data;
    document.documentElement.lang = data.lang;
    Theme.language(data.lang);
    if (Theme.apply(data.theme)) redraw();
    showScreen(data.screen || {});
    tellTheme();
  });
}

// A new theme: what was on screen goes into its blocks.
function redraw() {
  showState(lastState, lastWake);
  drawTimers();
}

// The server plays the theme's sounds: it needs to know which one this device has.
function tellTheme() {
  if (settings.theme) tell({ type: 'theme', name: settings.theme.name });
}

// What the screen shows (settings show_time, show_date, show_stats, clock…).
var screen = {};
function showScreen(s) {
  screen = s;
  var hide = { 'hide-time': s.show_time === false, 'hide-date': s.show_date === false, 'hide-stats': !s.show_stats };
  for (var name in hide) document.body.classList.toggle(name, hide[name]);
  Theme.clock(s.clock);
}

// Loads the texts and then shows the start button (or the demo, or the pairing form).
loadTexts().then(function () {
  if (settings.paired === false) return askForCode();  // the pairing plugin's
  var start = document.getElementById('start');
  start.textContent = text('start');
  status(text('connecting'));
  if (new URLSearchParams(location.search).has('demo')) demo();
  else start.hidden = false;
});

// Pairing (the plugin «pairing»): the code that «bin/anyassistant pair» shows on the Mac.
function askForCode() {
  var form = document.getElementById('pair');
  var input = document.getElementById('pair-code');
  document.getElementById('pair-prompt').textContent = text('pair_prompt');
  document.getElementById('pair-button').textContent = text('pair_button');
  form.hidden = false;
  form.onsubmit = function (ev) {
    if (ev) ev.preventDefault();
    fetch('/pair', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: input.value })
    }).then(function (r) {
      if (r.ok) location.replace(location.pathname);  // paired: the page, without the code
      else document.getElementById('pair-error').textContent = text('pair_wrong');
    });
  };
  // The Mac app's QR brings the code (?code=…): it pairs by itself, nothing to type.
  var given = new URLSearchParams(location.search).get('code');
  if (given) {
    input.value = given;
    form.onsubmit();
  }
}

document.getElementById('start').onclick = function () {
  this.hidden = true;
  document.getElementById('screen').hidden = false;
  keepAwake();
  begin();  // full screen once it may use the microphone and camera: in full screen, Safari
            // on the iPad doesn't show the permission prompt, and it stays «connecting»
};

// Tapping the face: goes back to full screen and, if it is speaking, stops it.
document.getElementById('screen').onclick = function () {
  if (!document.fullscreenElement) fullScreen();
  tell({ type: 'tap' });
};

function fullScreen() {
  var el = document.documentElement;
  if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
}

// The screen stays on: the Wake Lock API, or, where there is none (Chrome before 84, as on
// Android 4.4) or it says no, a tiny silent video playing in a loop (what a playing video does).
function keepAwake() {
  var video = null;
  var fallback = function () {
    if (!video) {
      video = document.createElement('video');
      video.src = '/web/awake.mp4';
      video.loop = true;
      video.muted = true;
      video.setAttribute('muted', '');
      video.setAttribute('playsinline', '');
      // In the page and barely visible: a video out of sight may not keep the screen on.
      video.style.cssText = 'position:fixed;left:0;bottom:0;width:1px;height:1px;opacity:0.01;pointer-events:none';
      document.body.appendChild(video);
    }
    var playing = video.play();
    if (playing && playing.catch) playing.catch(function () {});
  };
  var request = function () {
    if (!('wakeLock' in navigator)) return fallback();
    navigator.wakeLock.request('screen').catch(fallback);
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
var tabs = 'BroadcastChannel' in window ? new BroadcastChannel('anyassistant') : null;
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
  fullScreen();  // if the browser still allows it after the prompt; a tap on the face does it too
  levelMeter(media);
  setInterval(ping, 1000);
  setInterval(collectStats, 2000);
  connect();
}

// If the server restarts or the network drops, it reconnects without reloading the page.
function reconnect() {
  if (retry || shutDown) return;
  fail(text('connection_lost'));
  retry = setTimeout(function () { retry = null; connect(); }, 2000);
}

async function connect() {
  if (pc) pc.close();
  pc = new RTCPeerConnection({ iceServers: [] });
  var current = pc;
  // A watchdog: an attempt that hangs (the server restarting right then, a request that
  // never answers) would otherwise never be retried, while the screen says «retrying».
  setTimeout(function () {
    if (current === pc && pc.connectionState !== 'connected' && !shutDown) {
      retry = null;
      reconnect();
    }
  }, 25000);
  media.getAudioTracks().forEach(function (t) { pc.addTrack(t, media); });
  media.getVideoTracks().forEach(function (t) {
    pc.addTransceiver(t, { direction: 'sendonly', streams: [media] });
  });

  channel = pc.createDataChannel('control');
  channel.onmessage = function (ev) { message(JSON.parse(ev.data)); };
  channel.onopen = tellTheme;

  pc.ontrack = function (ev) {
    var stream = ev.streams[0] || new MediaStream([ev.track]);
    document.getElementById('speaker').srcObject = stream;
    Theme.speaker(stream);  // so the face follows its voice
  };
  pc.onconnectionstatechange = function () {
    if (current !== pc) return;
    if (pc.connectionState === 'connected' && Theme.current() === 'error') {
      Theme.state('connected');
      status(text('connected'));
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
      body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type, device: deviceId() })
    });
    if (response.status === 403) {  // unpaired meanwhile (bin/anyassistant unpair)
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
  tell({ type: 'ping', t: performance.now() });
}

var lastWake;
var PAUSED = ['microphone', 'call', 'interrupted'];  // why it is paused (the server's reasons)
function showState(state, wakePhrase, details) {
  lastState = state;
  lastWake = wakePhrase || lastWake;
  if (state === 'alarm') {
    status(text('alarm', { label: alarmLabel }));
  } else if (state === 'paused') {  // another app uses the microphone (a call): «En pausa: Zoom usa el micrófono»
    var why = details && PAUSED.indexOf(details.why) >= 0 ? details.why : 'microphone';
    status(text(details && details.app ? 'paused_app' : 'paused_' + why, { app: details && details.app }));
  } else if (state === 'asleep') {
    status(screen.show_hint === false ? '' : text('asleep', { wake: lastWake || (settings.wake_phrase || 'Hey Jarvis') }));
  } else {
    status(screen.show_status === false && state !== 'error' ? '' : text(state));
  }
  Theme.state(state);
  photoFollows(state);
  var camera = Theme.block('camera');
  if (state === 'asleep' && camera && !camera.hidden) showCamera(false);
}

function message(m) {
  if (m.type === 'pong') rtt = Math.round(performance.now() - m.t);
  else if (m.type === 'state') showState(m.state, m.wake_phrase, m);
  else if (m.type === 'text') caption(m);
  else if (m.type === 'pause' || m.type === 'resume') holdMicrophone(m.type === 'pause');  // the server paused it
  else if (m.type === 'look') showPhoto(m.at);
  else if (m.type === 'config') loadTexts();  // the settings changed
  else if (m.type === 'camera') showCamera(m.on);
  else if (m.type === 'photo') takePhoto(m.id);
  else if (m.type === 'timers') showTimers(m.items);
  else if (m.type === 'alarm') alarmLabel = m.label || '';
  else if (m.type === 'theme') { deviceTheme(m.name); loadTexts(); }  // «use the orb theme here»
}

// Paused by the server (another program on this computer uses the microphone: the plugin
// «microphone-busy»): the microphone's track sends silence meanwhile (the browser can't know
// by itself what else uses it).
function holdMicrophone(hold) {
  if (!media) return;
  media.getAudioTracks().forEach(function (t) { t.enabled = !hold; });
}

// «Turn on the camera»: what this device's camera sees, live, like a mirror (the same
// stream it already sends, so no extra load); «turn off the camera» hides it.
// Also hidden when it goes to sleep.
function showCamera(on) {
  var box = Theme.block('camera');
  var video = box.querySelector('video');
  if (on && media && media.getVideoTracks().length) {
    video.srcObject = media;
    box.hidden = false;
  } else {
    box.hidden = true;
    video.srcObject = null;
  }
  document.body.classList.toggle('camera-on', !box.hidden);
  clearInterval(cameraPlacing);
  if (!box.hidden) {
    placeCamera();
    cameraPlacing = setInterval(placeCamera, 500);  // what it says grows and shrinks; the window too
  }
}

// The camera below the face and its words (wherever the theme puts them), centred, 4:3, in the
// space left down to the bottom; never over the eyes.
var cameraPlacing = null;
function placeCamera() {
  var box = Theme.block('camera');
  if (!box || box.hidden) return;
  var unit = Math.min(innerWidth, innerHeight) / 100;
  var end = 0;
  ['face', 'status', 'timers', 'captions'].forEach(function (name) {
    var part = Theme.block(name);
    if (part && !part.hidden && part.offsetParent !== null) end = Math.max(end, part.getBoundingClientRect().bottom);
  });
  if (!end) end = innerHeight * 0.6;
  var top = Math.min(end + 2 * unit, innerHeight * 0.8 - 3 * unit);
  var height = Math.max(innerHeight - top - 3 * unit, innerHeight * 0.2);
  height = Math.min(height, innerWidth * 0.9 * 3 / 4);
  box.style.top = top + 'px';
  box.style.height = height + 'px';
  box.style.width = height * 4 / 3 + 'px';
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

// Running timers, alarms and reminders, with a countdown (settings show_timers). Each line
// carries its kind as a class (timer, alarm, reminder): an icon, if any, is the theme's.
var alarmLabel = '';
var timerItems = [];
function showTimers(items) {
  timerItems = items || [];
  drawTimers();
}
function drawTimers() {
  var box = Theme.block('timers');
  if (!box) return;
  if (screen.show_timers === false) { box.textContent = ''; return; }
  var now = Date.now() / 1000;
  var lines = timerItems.filter(function (i) { return i.at > now - 1; }).map(function (i) {
    var when;
    if (i.kind === 'timer') {
      var left = Math.max(0, Math.round(i.at - now));
      var h = Math.floor(left / 3600), m = Math.floor(left / 60) % 60, s = left % 60;
      when = (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (s < 10 ? '0' : '') + s;
    } else {
      when = new Date(i.at * 1000).toLocaleTimeString(document.documentElement.lang, { hour: 'numeric', minute: '2-digit' });
    }
    return { kind: i.kind, text: when + (i.label ? ' · ' + i.label : '') };
  });
  box.textContent = '';
  lines.forEach(function (line) {
    var p = document.createElement('p');
    p.className = line.kind;
    p.textContent = line.text;
    box.appendChild(p);
  });
}
setInterval(drawTimers, 1000);

// What it looks at through the camera, with a scanning sweep while it thinks about it;
// it fades out once it starts answering.
function showPhoto(at) {
  var photo = Theme.block('photo');
  var img = photo.querySelector('img');
  img.onload = function () { photo.hidden = false; photo.classList.remove('done'); photo.classList.add('scanning'); };
  img.src = '/eyes.jpg?t=' + at;
}
function photoFollows(state) {
  var photo = Theme.block('photo');
  if (!photo || photo.hidden || state === 'looking' || state === 'thinking') return;
  photo.classList.remove('scanning');
  photo.classList.add('done');
  setTimeout(function () { if (photo.classList.contains('done')) photo.hidden = true; }, 1500);
}

// Answers arrive in pieces with the same id: the same paragraph is updated.
// Blocks: «heard» (what you said last), «answer» (its last answer), «captions» (both, with history).
function caption(m) {
  if (m.author === 'assistant' ? screen.show_answer === false : screen.show_heard === false) return;
  setText(m.author === 'assistant' ? 'answer' : 'heard', m.text);
  var list = Theme.block('captions');
  if (!list) return;
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
  setText('stats', 'RTT ' + rtt + ' ms · jitter ' + jitter + ' ms · lost ' + lost);
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
    Theme.voice(peak / 128);
    requestAnimationFrame(loop);
  })();
}

function fail(message) {
  lastState = 'error';
  Theme.state('error');
  status(message);
}

// ?demo: without connecting, cycles through every state to see the theme (?demo&theme=orb);
// ?demo=thinking stays in one (the themes lab shows them all at once).
var DEMO_STATES = ['asleep', 'awake', 'hearing', 'transcribing', 'looking', 'thinking', 'speaking', 'question', 'alarm', 'error'];
function demo() {
  document.getElementById('screen').hidden = false;
  var fixed = new URLSearchParams(location.search).get('demo');
  var step = 0;
  var next = function () {
    var state = DEMO_STATES.indexOf(fixed) >= 0 ? fixed : DEMO_STATES[step++ % DEMO_STATES.length];
    alarmLabel = text('demo_alarm');
    showState(state, (settings.wake_phrase || 'Hey Jarvis'));
    if (state === 'looking') showPhoto(Date.now());  // the last photo, if there is one
    setText('stats', 'demo: ' + state);
  };
  var now = Date.now() / 1000;
  showTimers([{ kind: 'timer', at: now + 299, label: '' },
              { kind: 'alarm', at: now + 8 * 3600, label: '' },
              { kind: 'reminder', at: now + 3 * 3600, label: text('demo_reminder') }]);
  caption({ text: text('demo_heard') });
  caption({ text: text('demo_answer'), author: 'assistant', id: 'demo' });
  setInterval(function () {  // a simulated voice: yours while «hearing»
    Theme.voice(Theme.current() === 'hearing' ? 0.3 + 0.3 * Math.sin(Date.now() / 150) : 0);
  }, 50);
  next();
  if (DEMO_STATES.indexOf(fixed) < 0) setInterval(next, 3000);
}
