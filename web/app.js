// Cliente del móvil: micro y cámara al Mac, audio del Mac al altavoz.
// JS sin bundler para el Chrome de Android 7 (≤ 119).

var pc = null;
var canal = null;
var ojo = document.getElementById('ojo');
var estado = document.getElementById('estado');
var datos = document.getElementById('datos');
var rtt = null;

document.getElementById('empezar').onclick = function () {
  this.hidden = true;
  document.getElementById('cara').hidden = false;
  pantallaCompleta();
  mantenerDespierto();
  iniciar();
};

// Si se sale de pantalla completa, tocar la cara la recupera.
document.getElementById('cara').onclick = function () {
  if (!document.fullscreenElement) pantallaCompleta();
};

function pantallaCompleta() {
  var el = document.documentElement;
  if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
}

function mantenerDespierto() {
  if (!('wakeLock' in navigator)) return;
  var pedir = function () {
    navigator.wakeLock.request('screen').catch(function () {});
  };
  pedir();
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') pedir();
  });
}

// ?video=normal|bajo|no; por defecto, bajo en aparatos con ≤ 1 GB de RAM.
var VIDEO = {
  normal: { facingMode: 'user', width: 640, height: 480, frameRate: 15 },
  bajo: { facingMode: 'user', width: 320, height: 240, frameRate: 10 },
  no: false
};

function calidadVideo() {
  var pedida = new URLSearchParams(location.search).get('video');
  if (pedida in VIDEO) return pedida;
  return (navigator.deviceMemory || 2) <= 1 ? 'bajo' : 'normal';
}

var medios = null;
var reintento = null;

// Una sola pestaña conectada: al empezar en una, las demás se apagan.
var pestanas = 'BroadcastChannel' in window ? new BroadcastChannel('nexus-voz') : null;
var apagada = false;
if (pestanas) pestanas.onmessage = function (ev) {
  if (ev.data !== 'empiezo' || !medios) return;
  apagada = true;
  clearTimeout(reintento);
  if (pc) pc.close();
  medios.getTracks().forEach(function (t) { t.stop(); });
  fallo('Abierta en otra pestaña');
};

async function iniciar() {
  if (pestanas) pestanas.postMessage('empiezo');
  try {
    medios = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: VIDEO[calidadVideo()]
    });
  } catch (e) {
    fallo('Sin micro/cámara: ' + e.name + '. ¿Activaste el flag de Chrome?');
    return;
  }
  vumetro(medios);
  setInterval(ping, 1000);
  setInterval(estadisticas, 2000);
  conectar();
}

// Si el servidor se reinicia o se cae la Wi-Fi, se reconecta sin recargar la página.
function reconectar() {
  if (reintento || apagada) return;
  fallo('Conexión perdida, reintentando…');
  reintento = setTimeout(function () { reintento = null; conectar(); }, 2000);
}

async function conectar() {
  if (pc) pc.close();
  pc = new RTCPeerConnection({ iceServers: [] });
  var este = pc;
  medios.getAudioTracks().forEach(function (t) { pc.addTrack(t, medios); });
  medios.getVideoTracks().forEach(function (t) {
    pc.addTransceiver(t, { direction: 'sendonly', streams: [medios] });
  });

  canal = pc.createDataChannel('control');
  canal.onmessage = function (ev) { mensaje(JSON.parse(ev.data)); };

  pc.ontrack = function (ev) {
    document.getElementById('altavoz').srcObject = ev.streams[0] || new MediaStream([ev.track]);
  };
  pc.onconnectionstatechange = function () {
    if (este !== pc) return;
    if (pc.connectionState === 'connected' && ojo.className === 'error') {
      ojo.className = 'conectado';
      estado.textContent = 'Conectado';
    } else if (pc.connectionState === 'failed') {
      reconectar();
    } else if (pc.connectionState === 'disconnected') {
      // Suele recuperarse solo en unos segundos; solo se reconecta si no.
      setTimeout(function () {
        if (este === pc && pc.connectionState === 'disconnected') reconectar();
      }, 5000);
    }
  };

  try {
    await pc.setLocalDescription(await pc.createOffer());
    await esperarIce(pc);
    var corte = new AbortController();
    setTimeout(function () { corte.abort(); }, 15000);
    var resp = await fetch('/offer', {
      method: 'POST',
      signal: corte.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type })
    });
    await pc.setRemoteDescription(await resp.json());
  } catch (e) {
    if (este === pc) reconectar();
  }
}

// En la red local no hace falta trickle ICE: se espera a tener todos los candidatos.
function esperarIce(pc) {
  return new Promise(function (resolver) {
    if (pc.iceGatheringState === 'complete') return resolver();
    pc.addEventListener('icegatheringstatechange', function () {
      if (pc.iceGatheringState === 'complete') resolver();
    });
    setTimeout(resolver, 2000);
  });
}

function ping() {
  if (canal && canal.readyState === 'open') canal.send(JSON.stringify({ tipo: 'ping', t: performance.now() }));
}

var TEXTOS = {
  escuchando: 'Te escucho',
  despierto: 'Te escucho',
  grabando: 'Grabando…',
  repitiendo: 'Repitiendo',
  oyendo: 'Oyendo…',
  transcribiendo: 'Transcribiendo…'
};

function mensaje(m) {
  if (m.tipo === 'pong') rtt = Math.round(performance.now() - m.t);
  else if (m.tipo === 'estado') {
    estado.textContent = m.estado === 'dormido' ? 'Di «' + m.frase + '»'
      : TEXTOS[m.estado] || m.estado;
    ojo.className = 'conectado ' + m.estado;
  } else if (m.tipo === 'texto') {
    subtitulo(m.texto, m.tiempos);
  }
}

function subtitulo(texto, tiempos) {
  var lista = document.getElementById('subtitulos');
  var p = document.createElement('p');
  p.textContent = texto;
  if (tiempos) p.title = tiempos.stt_ms + ' ms';
  lista.appendChild(p);
  while (lista.children.length > 3) lista.removeChild(lista.firstChild);
}

async function estadisticas() {
  if (!pc) return;
  var informe = await pc.getStats();
  var jitter = null, perdidos = null;
  informe.forEach(function (s) {
    if (s.type === 'inbound-rtp' && s.kind === 'audio') {
      jitter = Math.round(s.jitter * 1000);
      perdidos = s.packetsLost;
    }
  });
  datos.textContent = 'RTT ' + rtt + ' ms · jitter ' + jitter + ' ms · perdidos ' + perdidos;
}

// El ojo late con el volumen del micro.
function vumetro(medios) {
  var ctx = new AudioContext();
  var analizador = ctx.createAnalyser();
  analizador.fftSize = 512;
  ctx.createMediaStreamSource(medios).connect(analizador);
  var buf = new Uint8Array(analizador.fftSize);
  (function bucle() {
    analizador.getByteTimeDomainData(buf);
    var pico = 0;
    for (var i = 0; i < buf.length; i++) pico = Math.max(pico, Math.abs(buf[i] - 128));
    ojo.style.transform = 'scale(' + (1 + pico / 128) + ')';
    requestAnimationFrame(bucle);
  })();
}

function fallo(texto) {
  ojo.className = 'error';
  estado.textContent = texto;
}
