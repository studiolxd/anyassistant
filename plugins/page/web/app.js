// The phone's client: microphone and camera to the Mac, the Mac's audio to the speaker.
// Plain JS without a bundler, for old Chrome versions (81 on Android 4.4).
// The texts (in the active language) and the settings come from the server (/config).

var pc = null;
var channel = null;
var rtt = null;
var T = {};  // texts of the active language (locale «ui», and the theme's own)
var settings = {};  // name, theme, video, screen…
var lastState = 'connecting';

// ?app: the theme in the iPhone, iPad, Mac and Android apps (every theme but Eyes, which they draw
// themselves). The app keeps the microphone, the audio, the camera and the connection: it gives this
// page what the server says, the voices' levels and its own problems (AnyAssistant.receive), and
// this page gives it the taps (toApp). No WebRTC here, no microphone, no pairing form.
var APP = new URLSearchParams(location.search).has('app');
function toApp(m) {
  try {
    if (window.webkit && webkit.messageHandlers && webkit.messageHandlers.anyassistant) webkit.messageHandlers.anyassistant.postMessage(m);
    else if (window.AnyAssistantApp) window.AnyAssistantApp.post(JSON.stringify(m));
  } catch (e) {}
}

// A message to the Mac, on the call's control channel (in an app, to the app: a tap).
function tell(m) {
  if (APP) return toApp(m);
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
  if (params.get('theme') && !params.has('demo') && !APP) deviceTheme(params.get('theme'));  // the themes page's views don't
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
  if (settings.theme && !APP) tell({ type: 'theme', name: settings.theme.name });
}

// What the screen shows (settings show_time, show_date, show_stats, clock…).
var screen = {};
function showScreen(s) {
  screen = s;
  var hide = { 'hide-time': s.show_time === false, 'hide-date': s.show_date === false, 'hide-stats': !s.show_stats };
  for (var name in hide) document.body.classList.toggle(name, hide[name]);
  Theme.clock(s.clock);
}

// Loads the texts and then shows the theme asleep, «Pulsa para empezar»: a tap anywhere starts it
// (the browser needs one for the microphone and the sound). Or the demo, or the pairing form.
var waitingTap = false;
loadTexts().then(function () {
  if (APP) return appMode();
  if (settings.paired === false) return askForCode();  // the pairing plugin's
  if (new URLSearchParams(location.search).has('demo')) return demo();
  document.getElementById('screen').hidden = false;
  Theme.state('asleep');
  status(text('tap_to_start'));
  waitingTap = true;
  document.getElementById('screen').classList.add('waiting');
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

function start() {
  status(text('connecting'));
  begin();  // full screen once it may use the microphone and camera: in full screen, Safari
            // on the iPad doesn't show the permission prompt, and it stays «connecting»
  try {  // still in the tap (its video may play); whatever it does, it never stops the page
    keepAwake();
  } catch (e) {
    tellLater('keeping the screen on: it failed (' + e + ')');
  }
};

// A line for the server's log once the data channel is open (it opens after the tap).
function tellLater(text) {
  if (channel && channel.readyState === 'open') return tell({ type: 'log', text: text });
  setTimeout(function () { tellLater(text); }, 2000);
}

// Tapping the face: goes back to full screen and, if it is speaking, stops it. A drag
// (scrolling the captions) isn't a tap.
document.getElementById('screen').onclick = function () {
  if (waitingTap) {  // the first tap: it starts
    waitingTap = false;
    this.classList.remove('waiting');
    start();
    return;
  }
  if (Words.dragged() || held) { held = false; return; }
  if (!document.fullscreenElement && !APP) fullScreen();
  tell({ type: 'tap' });
};

// In an app: holding the face opens its settings (as on its own Eyes), not a tap.
var held = false;
(function () {
  if (!APP) return;
  var timer = null;
  var from = null;
  var page = document.getElementById('screen');
  var cancel = function () { clearTimeout(timer); timer = null; };
  var down = function (x, y) {
    held = false;
    from = { x: x, y: y };
    cancel();
    timer = setTimeout(function () { timer = null; held = true; toApp({ type: 'settings' }); }, 800);
  };
  var move = function (x, y) { if (from && Math.abs(x - from.x) + Math.abs(y - from.y) > 10) cancel(); };  // a drag
  page.addEventListener('touchstart', function (ev) { down(ev.touches[0].clientX, ev.touches[0].clientY); }, { passive: true });
  page.addEventListener('mousedown', function (ev) { down(ev.clientX, ev.clientY); });
  page.addEventListener('touchmove', function (ev) { move(ev.touches[0].clientX, ev.touches[0].clientY); }, { passive: true });
  page.addEventListener('mousemove', function (ev) { move(ev.clientX, ev.clientY); });
  page.addEventListener('touchend', cancel);
  page.addEventListener('mouseup', cancel);
  page.addEventListener('contextmenu', function (ev) { ev.preventDefault(); });
})();

// The app's page: the screen at once; what the app says comes through AnyAssistant.receive, once
// it knows this page is ready (it then gives it what is on its face already).
function appMode() {
  document.body.classList.add('app');
  document.getElementById('screen').hidden = false;
  toApp({ type: 'ready' });
}
var AnyAssistant = {
  receive: function (m) {
    if (m.type === 'levels') {
      Theme.voice(m.voice || 0);
      Theme.speech(m.speech || 0);
    } else if (m.type === 'problem') {
      problem(m.text);
    } else {
      message(m);
    }
  }
};

// The app's own trouble (the server isn't answering, it has to be paired again, no microphone):
// the face in error, saying it, until it clears; then the state as it was.
var problemText = '';
function problem(value) {
  problemText = value || '';
  showState(lastState, lastWake, lastDetails);
}

function fullScreen() {
  var el = document.documentElement;
  if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
}

// The screen stays on: NoSleep.js (nosleep.js, MIT): the Wake Lock API, or, where there is
// none (Chrome before 84, as on Android 4.4), a short silent video playing in a loop, the one it
// carries (tested on many old devices). Started by a tap (the start button). What it uses, and
// whether its video plays, goes to the server's log.
function keepAwake() {
  if (typeof NoSleep === 'undefined') return;
  var noSleep = new NoSleep();
  var video = noSleep.noSleepVideo || null;
  var note = function (text) { tellLater('keeping the screen on: ' + text); };
  var enable = function () {
    noSleep.enable().then(function () { note(video ? 'the video plays' : 'wake lock'); },
                          function (e) { note('it can\'t (' + e + ')'); });
  };
  enable();
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && video && video.paused) enable();
  });
  setInterval(function () {  // whether its video still plays, every minute; paused, again
    if (!video) return;
    note('the video ' + (video.paused ? 'is paused' : 'plays') + ' at ' + video.currentTime.toFixed(1));
    if (video.paused) enable();
  }, 60000);
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
var lastDetails;
var PAUSED = ['microphone', 'call', 'interrupted'];  // why it is paused (the server's reasons)
function showState(state, wakePhrase, details) {
  lastState = state;
  lastWake = wakePhrase || lastWake;
  lastDetails = details;
  if (problemText) {
    status(problemText);
    state = 'error';
  } else if (state === 'alarm') {
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
  else if (m.type === 'speaking') Words.speaking(m);
  else if (m.type === 'pause' || m.type === 'resume') holdMicrophone(m.type === 'pause');  // the server paused it
  else if (m.type === 'look') showPhoto(m.at);
  else if (m.type === 'config') loadTexts();  // the settings changed
  else if (m.type === 'camera') showCamera(m.on);
  else if (m.type === 'photo') takePhoto(m.id);
  else if (m.type === 'timers') showTimers(m.items);
  else if (m.type === 'alarm') alarmLabel = m.label || '';
  else if (m.type === 'theme') { deviceTheme(m.name); loadTexts(); }  // «use another theme here»
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
// In an app, the window is only its place: the app shows its own camera there (cameraPlaced).
function showCamera(on) {
  var box = Theme.block('camera');
  var video = box.querySelector('video');
  if (on && APP) {
    box.hidden = false;
  } else if (on && media && media.getVideoTracks().length) {
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
  } else {
    cameraPlaced(null);
  }
}

// Where the camera's window is, for the app (only when it changes).
var cameraWhere = '';
function cameraPlaced(box) {
  if (!APP) return;
  var r = box && box.getBoundingClientRect();
  var m = r ? { type: 'camera', on: true, x: r.left, y: r.top, width: r.width, height: r.height } : { type: 'camera', on: false };
  var key = JSON.stringify(m);
  if (key === cameraWhere) return;
  cameraWhere = key;
  toApp(m);
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
  cameraPlaced(box);
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
// Each scrolls in its own area (Words): what you said shows from its end; an answer, from its
// start, and then follows the voice.
function caption(m) {
  var assistant = m.author === 'assistant';
  if (assistant ? screen.show_answer === false : screen.show_heard === false) return;
  var single = Theme.block(assistant ? 'answer' : 'heard');
  if (single) {
    var fresh = !assistant || single.getAttribute('data-id') !== String(m.id);
    single.textContent = m.text;
    single.setAttribute('data-id', m.id === undefined ? '' : m.id);
    Words.show(single, single, assistant ? m.id : null, fresh);
  }
  var list = Theme.block('captions');
  if (!list) return;
  var p = m.id && document.getElementById('answer-' + m.id);
  if (p) {
    p.textContent = m.text;
    Words.show(list, p, m.id, false);
    return;
  }
  p = document.createElement('p');
  p.textContent = m.text;
  if (m.id) p.id = 'answer-' + m.id;
  if (assistant) p.className = 'assistant';
  list.appendChild(p);
  var history = screen.history === undefined ? 2 : screen.history;
  while (list.children.length > history + 1) list.removeChild(list.firstChild);
  Words.show(list, p, assistant ? m.id : null, true);
}

// The words' areas (blocks captions, heard, answer): each scrolls inside the height its theme
// gives it (system.css), without a scrollbar: a finger, the wheel or the trackpad. Following:
// what you said, its end; an answer, its start until the voice says it, then the sentence it is
// saying («speaking» from the server, when it starts playing here): a teleprompter. Scrolled by
// hand, it stops following until you scroll back to the end or new words arrive. A fade at the
// top or the bottom (classes more-above, more-below) where there is more.
var Words = (function () {
  var said = {};  // answer id: [start, end] of the sentence being said
  var down = null;  // where a press started, to tell a tap from a drag
  var moved = false;

  function area(el) {
    return el && el.closest ? el.closest('[data-block="captions"], [data-block="heard"], [data-block="answer"]') : null;
  }
  function scrolls(box) { return box.scrollHeight > box.clientHeight + 1; }
  function end(box) { return Math.max(0, box.scrollHeight - box.clientHeight); }

  function fades(box) {
    box.classList.toggle('more-above', box.scrollTop > 1);
    box.classList.toggle('more-below', box.scrollTop < end(box) - 1);
  }

  // Where the area should be: its end, the start of a paragraph, or the sentence being said
  // (with a line of what came before above it, under the fade).
  function aim(box) {
    var to = box._aim;
    if (!to) return box.scrollTop;
    if (to.end) return end(box);
    var base = box.getBoundingClientRect().top - box.scrollTop;  // the top of the area's content, on screen
    var y = to.p === box ? 0 : to.p.getBoundingClientRect().top - base;
    var range = said[to.id];
    var text = to.p.firstChild;
    if (range && text && text.nodeType === 3 && range[0] < text.length) {
      var r = document.createRange();
      r.setStart(text, range[0]);
      r.setEnd(text, Math.min(range[1], text.length));
      var rects = r.getClientRects();
      var style = getComputedStyle(to.p);
      var line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.25 || 20;
      if (rects.length) y = Math.max(y, rects[0].top - base - line);
    }
    return Math.max(0, Math.min(end(box), y));
  }

  // Smoothly there (its own animation: old Safari and Chrome 81 have no smooth scrollTo).
  function glide(box) {
    var from = box.scrollTop, to = aim(box);
    cancelAnimationFrame(box._glide);
    if (Math.abs(to - from) < 1) { fades(box); return; }
    var started = null;
    box._gliding = true;
    var step = function (now) {
      if (started === null) started = now;
      var f = Math.min(1, (now - started) / 450);
      box.scrollTop = from + (to - from) * (f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2);
      if (f < 1) box._glide = requestAnimationFrame(step);
      else box._gliding = false;
      fades(box);
    };
    box._glide = requestAnimationFrame(step);
  }

  // New or changed words in an area: p (the paragraph, or the block itself), id (an answer's,
  // null for what you said), fresh (new words: following again).
  function show(box, p, id, fresh) {
    if (fresh) box._follow = true;
    if (fresh || (box._aim && box._aim.p === p)) box._aim = id === null || id === undefined ? { end: true } : { p: p, id: id };
    if (box._follow !== false) glide(box);
    else fades(box);
  }

  function speaking(m) {
    said[m.id] = [m.start, m.end];
    var single = Theme.block('answer');
    if (single && single.getAttribute('data-id') === String(m.id)) show(single, single, m.id, false);
    var p = document.getElementById('answer-' + m.id);
    if (p) show(Theme.block('captions'), p, m.id, false);
  }

  // By hand (a finger, the wheel): it stops following; back at the end, it follows again.
  function byHand(ev) {
    var box = area(ev.target);
    if (!box || !scrolls(box)) return;
    box._follow = false;
    cancelAnimationFrame(box._glide);
    box._gliding = false;
  }
  var page = document.getElementById('screen');
  page.addEventListener('wheel', byHand, { passive: true });
  page.addEventListener('scroll', function (ev) {  // scroll doesn't bubble: caught on its way down
    var box = area(ev.target);
    if (!box) return;
    fades(box);
    if (box._follow === false && !box._gliding && box.scrollTop >= end(box) - 2) {
      box._follow = true;
      glide(box);
    }
  }, true);

  // A press that moves isn't a tap (scrolling the captions with a finger, or a mouse drag).
  function press(x, y) { down = { x: x, y: y }; moved = false; }
  function move(x, y) { if (down && Math.abs(x - down.x) + Math.abs(y - down.y) > 10) moved = true; }
  page.addEventListener('touchstart', function (ev) { press(ev.touches[0].clientX, ev.touches[0].clientY); }, { passive: true });
  page.addEventListener('touchmove', function (ev) {
    move(ev.touches[0].clientX, ev.touches[0].clientY);
    if (moved) byHand(ev);
  }, { passive: true });
  page.addEventListener('mousedown', function (ev) { press(ev.clientX, ev.clientY); });
  page.addEventListener('mousemove', function (ev) { if (ev.buttons) move(ev.clientX, ev.clientY); });

  // The layout changes (the theme's CSS arrives, the window's size, timers that come and go):
  // each area back to where it should be.
  function again() {
    ['captions', 'heard', 'answer'].forEach(function (name) {
      var box = Theme.block(name);
      if (box && !box._gliding) { if (box._follow !== false) glide(box); else fades(box); }
    });
  }
  addEventListener('resize', again);
  document.getElementById('theme-css').addEventListener('load', again);
  setInterval(again, 1000);

  return {
    show: show,
    speaking: speaking,
    dragged: function () { var was = moved; moved = false; down = null; return was; }
  };
})();

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

// ?demo: without connecting, cycles through every state to see the theme (?demo&theme=eyes);
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
  demoVoice(text('demo_answer'));
  setInterval(function () {  // a simulated voice: yours while «hearing»
    Theme.voice(Theme.current() === 'hearing' ? 0.3 + 0.3 * Math.sin(Date.now() / 150) : 0);
  }, 50);
  next();
  if (DEMO_STATES.indexOf(fixed) < 0) setInterval(next, 3000);
}

// The demo's voice: says the answer's sentences one after another (as «speaking» from the
// server would), so the captions can be seen following it; then again from the start.
function demoVoice(answer) {
  var sentences = [];
  var found = /[^.!?…;:\n]+(?:[.!?…;:]+|$)/g;
  var m;
  while ((m = found.exec(answer))) {
    var start = m.index + m[0].length - m[0].replace(/^\s+/, '').length;
    if (m[0].trim()) sentences.push([start, m.index + m[0].replace(/\s+$/, '').length]);
  }
  var i = 0;
  var say = function () {
    var s = sentences[i++ % sentences.length];
    if (s) Words.speaking({ id: 'demo', start: s[0], end: s[1] });
  };
  say();
  setInterval(say, 2500);
}
