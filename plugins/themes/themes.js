// The themes: every state of a theme at once (each view is the page in ?demo=<state>),
// reloading them when the theme's files change. Open it on the Mac while you design one.

var STATES = ['asleep', 'awake', 'hearing', 'transcribing', 'thinking', 'looking', 'speaking', 'question', 'alarm', 'error'];
var select = document.getElementById('theme');
var version = null;

function views(name) {
  var main = document.getElementById('states');
  main.innerHTML = '';
  STATES.forEach(function (state) {
    var figure = document.createElement('figure');
    var frame = document.createElement('div');
    frame.className = 'frame';
    var iframe = document.createElement('iframe');
    iframe.src = '/?demo=' + state + '&theme=' + encodeURIComponent(name);
    frame.appendChild(iframe);
    // A cover over the view (the page inside would take the tap): it opens it full screen.
    var cover = document.createElement('div');
    cover.className = 'cover';
    cover.onclick = function () { open(STATES.indexOf(state)); };
    frame.appendChild(cover);
    var caption = document.createElement('figcaption');
    caption.textContent = state;
    figure.appendChild(frame);
    figure.appendChild(caption);
    main.appendChild(figure);
  });
}

function config(name) {
  return fetch('/config?theme=' + encodeURIComponent(name)).then(function (r) { return r.json(); });
}

config(new URLSearchParams(location.search).get('theme') || '').then(function (data) {
  data.themes.forEach(function (theme) {
    var option = document.createElement('option');
    option.value = theme.name;
    option.textContent = theme.title + ' (' + theme.name + ')';
    select.appendChild(option);
  });
  select.value = data.theme.name;
  show(data);
});

function show(data) {
  version = data.theme.version;
  var about = data.themes.filter(function (s) { return s.name === data.theme.name; })[0];
  document.getElementById('about').textContent = about ? about.description : '';
  history.replaceState(null, '', '/themes?theme=' + encodeURIComponent(data.theme.name));
  views(data.theme.name);
}

select.onchange = function () { config(select.value).then(show); };

// When a file of the theme changes, the views reload.
setInterval(function () {
  config(select.value).then(function (data) {
    if (data.theme.version === version) return;
    show(data);
    var note = document.getElementById('reloaded');
    note.textContent = 'reloaded ' + new Date().toLocaleTimeString();
    setTimeout(function () { note.textContent = ''; }, 3000);
  });
}, 1500);

// One state full screen, as on the device (this screen's own size and orientation):
// ✕ or Esc goes back to all of them; ‹ › or the arrows go through the states.
var full = document.getElementById('full');
var current = 0;

function open(index) {
  current = (index + STATES.length) % STATES.length;
  document.getElementById('full-view').src = '/?demo=' + STATES[current] + '&theme=' + encodeURIComponent(select.value);
  document.getElementById('full-state').textContent = STATES[current];
  full.hidden = false;
}

function close() {
  full.hidden = true;
  document.getElementById('full-view').src = 'about:blank';
}

document.getElementById('full-close').onclick = close;
document.getElementById('full-previous').onclick = function () { open(current - 1); };
document.getElementById('full-next').onclick = function () { open(current + 1); };
document.addEventListener('keydown', function (ev) {
  if (full.hidden) return;
  if (ev.key === 'Escape') close();
  else if (ev.key === 'ArrowLeft') open(current - 1);
  else if (ev.key === 'ArrowRight') open(current + 1);
});
