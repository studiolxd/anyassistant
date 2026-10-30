// La cara de Jarvis: «ojos» (por defecto) u «orbe», con ?cara=ojos|orbe.
// El estado del servidor va a body[data-estado] y el CSS (rostros.css) hace el resto.
// El volumen del micro y el de su propia voz mueven .latido y la boca desde aquí:
// solo transformaciones, para que vaya fluido en la tablet (Chrome 81).

var Rostro = (function () {
  // Estados del servidor que se ven igual que otro.
  var VISUAL = {
    conectado: 'despierto', escuchando: 'despierto', grabando: 'oyendo',
    repitiendo: 'hablando', transcribiendo: 'pensando'
  };
  var PLANTILLAS = {
    ojos:
      '<div class="latido">' +
      '<div class="ojos"><div class="ojo izq"></div><div class="ojo der"></div></div>' +
      '<div class="interrogacion">?</div>' +
      '</div>' +
      '<div class="boca"><i></i><i></i><i></i><i></i><i></i></div>' +
      '<div class="puntos"><i></i><i></i><i></i></div>',
    orbe:
      '<div class="latido"><div class="orbe">' +
      '<div class="onda"></div><div class="onda segunda"></div>' +
      '<div class="anillo"></div><div class="nucleo"></div>' +
      '<div class="interrogacion">?</div>' +
      '</div></div>'
  };

  var tipo = new URLSearchParams(location.search).get('cara') === 'orbe' ? 'orbe' : 'ojos';
  var raiz = document.getElementById('rostro');
  raiz.className = 'rostro-' + tipo;
  raiz.innerHTML = PLANTILLAS[tipo];
  var latido = raiz.querySelector('.latido');
  var barras = raiz.querySelectorAll('.boca i');
  var visual = '';
  var actual = '';

  function estado(e) {
    actual = e;
    visual = VISUAL[e] || e;
    document.body.setAttribute('data-estado', visual);
  }

  // --- Volúmenes: el del micro llega de app.js; el de su voz se mide aquí ---
  var voz = 0;
  var habla = 0;
  var analizador = null;
  var muestras = null;
  var analizadorFunciona = false;  // en algunos Chrome el audio remoto llega mudo a WebAudio

  function ponerVoz(nivel) { voz = nivel; }

  function altavoz(stream) {
    try {
      var ctx = new AudioContext();
      analizador = ctx.createAnalyser();
      analizador.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(analizador);
      muestras = new Uint8Array(analizador.fftSize);
    } catch (e) {
      analizador = null;
    }
  }

  function nivelAltavoz() {
    if (!analizador) return 0;
    analizador.getByteTimeDomainData(muestras);
    var pico = 0;
    for (var i = 0; i < muestras.length; i++) pico = Math.max(pico, Math.abs(muestras[i] - 128));
    if (pico > 3) analizadorFunciona = true;
    return pico / 128;
  }

  var paso = 0;
  var ultimoLatido = '';
  (function bucle() {
    paso++;
    var h = nivelAltavoz();
    if (visual === 'hablando' && !analizadorFunciona) {
      h = 0.35 + 0.25 * Math.sin(paso / 4);  // sin medida real, una boca que se mueve
    }
    habla += (h - habla) * 0.4;

    var escala = 1;
    if (visual === 'oyendo' || visual === 'despierto') escala += Math.min(voz, 1) * 0.18;
    if (visual === 'hablando' && tipo === 'orbe') escala += Math.min(habla, 1) * 0.2;
    var transformacion = 'scale(' + escala.toFixed(3) + ')';
    if (transformacion !== ultimoLatido) {  // tocar el estilo solo si cambia
      latido.style.transform = transformacion;
      ultimoLatido = transformacion;
    }
    if (visual === 'hablando') {
      for (var i = 0; i < barras.length; i++) {
        var alto = 0.15 + Math.min(habla * 1.6, 1) * (0.55 + 0.45 * Math.sin(paso / 3 + i * 1.7));
        barras[i].style.transform = 'scaleY(' + alto.toFixed(2) + ')';
      }
    }
    requestAnimationFrame(bucle);
  })();

  // --- Parpadeo (solo los ojos), a intervalos irregulares ---
  function parpadear() {
    if (tipo === 'ojos' && visual !== 'dormido' && visual !== 'error') {
      raiz.classList.add('parpadeo');
      setTimeout(function () { raiz.classList.remove('parpadeo'); }, 140);
    }
    setTimeout(parpadear, 2500 + Math.random() * 4500);
  }
  setTimeout(parpadear, 3000);

  // --- Reloj para cuando está dormido ---
  var DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  var MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
    'septiembre', 'octubre', 'noviembre', 'diciembre'];
  function reloj() {
    var d = new Date();
    document.getElementById('hora').textContent =
      d.getHours() + ':' + ('0' + d.getMinutes()).slice(-2);
    document.getElementById('fecha').textContent =
      DIAS[d.getDay()] + ' ' + d.getDate() + ' de ' + MESES[d.getMonth()];
  }
  reloj();
  setInterval(reloj, 10000);

  return {
    estado: estado,
    voz: ponerVoz,
    altavoz: altavoz,
    actual: function () { return actual; }
  };
})();
