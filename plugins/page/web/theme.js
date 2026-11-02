// The theme: the screen's look (themes/<name>: theme.html and theme.css), applied from /config.
// Jarvis fills the blocks ([data-block="status"], "clock", "captions"…) and gives the
// theme, for its CSS, without any JavaScript of its own:
//   body[data-state]  the state as it comes (asleep, awake, hearing, thinking, looking,
//                     speaking, question, alarm, error…)
//   body[data-look]   the same, with the ones that look alike grouped (listening → awake…)
//   body.blink        now and then, for a moment
//   --voice, --speech, --bar-1…5   on the face block, live (0–1): your voice, its own,
//                     and its own as five moving bars (a mouth)
// Transforms and opacity only, if possible: the tablet is modest (Chrome 81).

var Theme = (function () {
  var LOOKS_LIKE = {
    connected: 'awake', listening: 'awake', recording: 'hearing',
    repeating: 'speaking', transcribing: 'thinking', connecting: 'awake'
  };
  var screen = document.getElementById('screen');
  var stylesheet = document.getElementById('theme-css');
  var applied = '';
  var current = '';
  var look = '';
  var texts = {};

  function block(name) { return screen.querySelector('[data-block="' + name + '"]'); }

  // Puts the theme on the screen; true if it changed (the page then redraws its blocks).
  function apply(theme) {
    var key = theme.name + ':' + theme.version + ':' + JSON.stringify(theme.options) + JSON.stringify(theme.texts);
    if (key === applied) return false;
    applied = key;
    stylesheet.href = theme.css + '?v=' + theme.version;
    screen.innerHTML = theme.html;
    for (var name in theme.options) document.documentElement.style.setProperty('--' + name, theme.options[name]);
    texts = theme.texts || {};
    var labelled = screen.querySelectorAll('[data-text]');
    for (var i = 0; i < labelled.length; i++) labelled[i].textContent = texts[labelled[i].getAttribute('data-text')] || '';
    build();
    clock();
    return true;
  }

  // What the blocks need inside: the clock's two parts, the camera's video, the photo.
  // Without camera or photo blocks in the theme, Jarvis adds its own: they must work.
  function build() {
    ['camera', 'photo'].forEach(function (name) {
      if (block(name)) return;
      var box = document.createElement('div');
      box.setAttribute('data-block', name);
      box.className = 'system-window';
      screen.appendChild(box);
    });
    var clockBlock = block('clock');
    if (clockBlock && !clockBlock.children.length) clockBlock.innerHTML = '<p data-part="time"></p><p data-part="date"></p>';
    var camera = block('camera');
    camera.hidden = true;
    camera.innerHTML = '';
    var video = document.createElement('video');
    video.autoplay = true;
    video.muted = true;
    video.setAttribute('playsinline', '');
    camera.appendChild(video);
    var photo = block('photo');
    photo.hidden = true;
    photo.innerHTML = '<img alt=""><div class="scan"></div>';
  }

  function state(s) {
    current = s;
    look = LOOKS_LIKE[s] || s;
    document.body.setAttribute('data-state', s);
    document.body.setAttribute('data-look', look);
  }

  // --- Volumes: the microphone's comes from app.js; its own voice's is measured here ---
  var voice = 0;
  var speech = 0;
  var analyser = null;
  var samples = null;
  var analyserWorks = false;  // on some Chrome versions remote audio reaches WebAudio silent

  function speaker(stream) {
    try {
      var context = new AudioContext();
      analyser = context.createAnalyser();
      analyser.fftSize = 256;
      context.createMediaStreamSource(stream).connect(analyser);
      samples = new Uint8Array(analyser.fftSize);
    } catch (e) {
      analyser = null;
    }
  }

  function speakerLevel() {
    if (!analyser) return 0;
    analyser.getByteTimeDomainData(samples);
    var peak = 0;
    for (var i = 0; i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i] - 128));
    if (peak > 3) analyserWorks = true;
    return peak / 128;
  }

  var step = 0;
  var last = {};
  function setVar(target, name, value) {  // only when it changes: each change restyles
    var text = value.toFixed(2);
    if (last[name] === text) return;
    last[name] = text;
    target.style.setProperty(name, text);
  }
  (function loop() {
    step++;
    var level = speakerLevel();
    if (look === 'speaking' && !analyserWorks) level = 0.35 + 0.25 * Math.sin(step / 4);  // a mouth that moves anyway
    if (look !== 'speaking') level = 0;
    speech += (level - speech) * 0.4;
    var target = block('face') || screen;
    setVar(target, '--voice', Math.min(voice, 1));
    setVar(target, '--speech', Math.min(speech, 1));
    for (var i = 0; i < 5; i++) {
      var bar = 0.15 + Math.min(speech * 1.6, 1) * (0.55 + 0.45 * Math.sin(step / 3 + i * 1.7));
      setVar(target, '--bar-' + (i + 1), look === 'speaking' ? bar : 0.15);
    }
    requestAnimationFrame(loop);
  })();

  // --- Blinking, at irregular intervals (the theme decides what blinking looks like) ---
  function blink() {
    if (look !== 'asleep' && look !== 'error') {
      document.body.classList.add('blink');
      setTimeout(function () { document.body.classList.remove('blink'); }, 140);
    }
    setTimeout(blink, 2500 + Math.random() * 4500);
  }
  setTimeout(blink, 3000);

  // --- The clock, in the active language (blocks clock, time, date) ---
  var lang = 'en';
  var hour12;  // settings «clock»: 12, 24 or (undefined) the language's
  function clock() {
    var now = new Date();
    var time = now.toLocaleTimeString(lang, { hour: 'numeric', minute: '2-digit', hour12: hour12 });
    var date = now.toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'long' });
    var parts = screen.querySelectorAll('[data-part="time"], [data-block="time"]');
    for (var i = 0; i < parts.length; i++) parts[i].textContent = time;
    parts = screen.querySelectorAll('[data-part="date"], [data-block="date"]');
    for (i = 0; i < parts.length; i++) parts[i].textContent = date;
  }
  setInterval(clock, 10000);

  return {
    apply: apply,
    block: block,
    state: state,
    voice: function (level) { voice = level; },
    speaker: speaker,
    current: function () { return current; },
    language: function (code) { lang = code; clock(); },
    clock: function (format) { hour12 = format === '12' ? true : format === '24' ? false : undefined; clock(); }
  };
})();
