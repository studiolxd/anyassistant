// The assistant's face: «eyes» or «orb», from the settings (face) or ?face=eyes|orb, which wins.
// The server's state goes to body[data-state] and the CSS (faces.css) does the rest.
// The microphone's volume and its own voice's move .pulse and the mouth from here:
// transforms only, so it runs smoothly on the tablet (Chrome 81).

var Face = (function () {
  // Server states that look like another one.
  var LOOKS_LIKE = {
    connected: 'awake', listening: 'awake', recording: 'hearing',
    repeating: 'speaking', transcribing: 'thinking'
  };
  var TEMPLATES = {
    eyes:
      '<div class="pulse">' +
      '<div class="eyes"><div class="eye left"></div><div class="eye right"></div></div>' +
      '<div class="question-mark">?</div>' +
      '</div>' +
      '<div class="mouth"><i></i><i></i><i></i><i></i><i></i></div>' +
      '<div class="dots"><i></i><i></i><i></i></div>',
    orb:
      '<div class="pulse"><div class="orb">' +
      '<div class="wave"></div><div class="wave second"></div>' +
      '<div class="ring"></div><div class="core"></div>' +
      '<div class="question-mark">?</div>' +
      '</div></div>'
  };

  var asked = new URLSearchParams(location.search).get('face');
  var kind, pulse, bars;
  var root = document.getElementById('face');

  function setKind(k) {
    k = asked in TEMPLATES ? asked : k in TEMPLATES ? k : 'eyes';
    if (k === kind) return;
    kind = k;
    root.className = 'face-' + kind;
    root.innerHTML = TEMPLATES[kind];
    pulse = root.querySelector('.pulse');
    bars = root.querySelectorAll('.mouth i');
  }
  setKind('eyes');
  var look = '';
  var current = '';

  function state(s) {
    current = s;
    look = LOOKS_LIKE[s] || s;
    document.body.setAttribute('data-state', look);
  }

  // --- Volumes: the microphone's comes from app.js; its own voice's is measured here ---
  var voice = 0;
  var speech = 0;
  var analyser = null;
  var samples = null;
  var analyserWorks = false;  // on some Chrome versions remote audio reaches WebAudio silent

  function setVoice(level) { voice = level; }

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
  var lastTransform = '';
  (function loop() {
    step++;
    var level = speakerLevel();
    if (look === 'speaking' && !analyserWorks) {
      level = 0.35 + 0.25 * Math.sin(step / 4);  // without a real level, a mouth that moves anyway
    }
    speech += (level - speech) * 0.4;

    var scale = 1;
    if (look === 'hearing' || look === 'awake') scale += Math.min(voice, 1) * 0.18;
    if (look === 'speaking' && kind === 'orb') scale += Math.min(speech, 1) * 0.2;
    var transform = 'scale(' + scale.toFixed(3) + ')';
    if (transform !== lastTransform) {  // only touch the style when it changes
      pulse.style.transform = transform;
      lastTransform = transform;
    }
    if (look === 'speaking') {
      for (var i = 0; i < bars.length; i++) {
        var height = 0.15 + Math.min(speech * 1.6, 1) * (0.55 + 0.45 * Math.sin(step / 3 + i * 1.7));
        bars[i].style.transform = 'scaleY(' + height.toFixed(2) + ')';
      }
    }
    requestAnimationFrame(loop);
  })();

  // --- Blinking (eyes only), at irregular intervals ---
  function blink() {
    if (kind === 'eyes' && look !== 'asleep' && look !== 'error') {
      root.classList.add('blink');
      setTimeout(function () { root.classList.remove('blink'); }, 140);
    }
    setTimeout(blink, 2500 + Math.random() * 4500);
  }
  setTimeout(blink, 3000);

  // --- Clock for when it is asleep, in the active language ---
  var lang = 'en';
  var hour12;  // settings «clock»: 12, 24 or (undefined) the language's
  function clock() {
    var now = new Date();
    document.getElementById('time').textContent =
      now.toLocaleTimeString(lang, { hour: 'numeric', minute: '2-digit', hour12: hour12 });
    document.getElementById('date').textContent =
      now.toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'long' });
  }
  setInterval(clock, 10000);

  return {
    state: state,
    voice: setVoice,
    speaker: speaker,
    current: function () { return current; },
    kind: setKind,
    language: function (code) { lang = code; clock(); },
    clock: function (format) { hour12 = format === '12' ? true : format === '24' ? false : undefined; clock(); }
  };
})();
