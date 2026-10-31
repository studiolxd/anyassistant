// The skins lab: every state of a skin at once (each view is the page in ?demo=<state>),
// reloading them when the skin's files change. Open it on the Mac while you design one.

var STATES = ['asleep', 'awake', 'hearing', 'thinking', 'looking', 'speaking', 'question', 'alarm', 'error'];
var select = document.getElementById('skin');
var version = null;

function views(name) {
  var main = document.getElementById('states');
  main.innerHTML = '';
  STATES.forEach(function (state) {
    var figure = document.createElement('figure');
    var frame = document.createElement('div');
    frame.className = 'frame';
    var iframe = document.createElement('iframe');
    iframe.src = '/?demo=' + state + '&skin=' + encodeURIComponent(name);
    frame.appendChild(iframe);
    var caption = document.createElement('figcaption');
    caption.textContent = state;
    figure.appendChild(frame);
    figure.appendChild(caption);
    main.appendChild(figure);
  });
}

function config(name) {
  return fetch('/config?skin=' + encodeURIComponent(name)).then(function (r) { return r.json(); });
}

config(new URLSearchParams(location.search).get('skin') || '').then(function (data) {
  data.skins.forEach(function (skin) {
    var option = document.createElement('option');
    option.value = skin.name;
    option.textContent = skin.title + ' (' + skin.name + ')';
    select.appendChild(option);
  });
  select.value = data.skin.name;
  show(data);
});

function show(data) {
  version = data.skin.version;
  var about = data.skins.filter(function (s) { return s.name === data.skin.name; })[0];
  document.getElementById('about').textContent = about ? about.description : '';
  history.replaceState(null, '', '/lab?skin=' + encodeURIComponent(data.skin.name));
  views(data.skin.name);
}

select.onchange = function () { config(select.value).then(show); };

// When a file of the skin changes, the views reload.
setInterval(function () {
  config(select.value).then(function (data) {
    if (data.skin.version === version) return;
    show(data);
    var note = document.getElementById('reloaded');
    note.textContent = 'reloaded ' + new Date().toLocaleTimeString();
    setTimeout(function () { note.textContent = ''; }, 3000);
  });
}, 1500);
