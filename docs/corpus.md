# El corpus de audio: medir cómo escucha

Un conjunto fijo de grabaciones públicas (unos 480 casos) con el que se mide, sin micrófono y sin
servidor en marcha, la cadena de escucha de AnyAssistant: el corte de frases del oído
(`plugins/brain-transcriber/ear.py`: el detector de voz Silero, el suelo de ruido, la opción
`silence`), los motores de reconocimiento de voz instalados (`server/stt`, con sus plugins) y el
reconocimiento de quién habla (el plugin `voices`). Sirve para ver qué cambia cuando se toca algo
de eso, y para elegir valores por defecto con muchas voces, no con la de una persona.

Ninguna grabación es de nadie de casa: todo sale de datasets públicos con licencia libre, y el
audio **no está en git**. En el repositorio solo hay la selección (`tests/corpus/cases.json`: qué
archivo de qué dataset, con su revisión y su SHA-256, el texto esperado, el hablante y qué se le
mezcla) y los últimos resultados aceptados (`tests/corpus/baseline.json`). El audio se descarga a
la caché (`.build/corpus` en el proyecto; `~/Library/Caches/AnyAssistant/corpus` instalado; o la
carpeta de `$ANYASSISTANT_CORPUS`, para compartir una copia entre varias copias del proyecto) y se
comprueba archivo por archivo.

## Qué hay dentro

| Casos | De dónde | Qué miden |
|---|---|---|
| 240 frases cortas en español (60 hablantes, 4 cada uno; MP3) | Mozilla Common Voice 17.0, división *test* | WER, corte de frases, quién habla |
| 40 frases largas en español y 25 en inglés (16 kHz, leídas) | FLEURS (Google), `es_419` y `en_us`, división *dev* | WER, corte de frases |
| 20 frases largas en español (audiolibros) | Multilingual LibriSpeech, división *test* | WER, corte de frases |
| 22 cortes de solo ruido (6 s; tres de 20 s) | MUSAN (ruidos de Freesound) y DEMAND (cocina, salón y sala de reuniones reales) | arranques en falso del detector de voz, frases «fantasma» |
| 108 frases mezcladas con ruido a 20, 10 y 5 dB de SNR | las anteriores, con 3 s de ruido antes de la voz | WER con ruido, corte de frases, quién habla con ruido |
| 20 frases «en una habitación» | las anteriores, convolucionadas con 5 respuestas al impulso (tres simuladas, dos reales: oficina y aula) | WER con reverberación, quién habla |

El texto esperado va **normalizado**: minúsculas, sin puntuación, sin acentos (la ñ se conserva),
una sola separación entre palabras (`corpus.normalise`); así se compara también lo transcrito.
Cada caso de voz lleva 0,5 s de silencio delante y 1,5 s detrás (más que cualquier `silence`
probado), para que la frase pueda empezar y acabar como en una habitación. En los mezclados, el
ruido empieza 3 s antes de la voz, para que el suelo de ruido del oído se asiente como en una
habitación de verdad; la SNR se calcula con el nivel de la voz (la mitad más alta de sus tramos de
20 ms) frente al RMS del ruido.

Cómo se hizo la selección (semilla fija, `tests/corpus/select.py`): de Common Voice, 60 hablantes
con cuatro clips válidos de 1,5 a 12 s; de FLEURS y MLS, las primeras frases de hasta 12 s (el
oído corta a los 15); los ruidos y las respuestas al impulso, a mano. No hace falta ejecutarlo
para usar el corpus; está para reproducirlo o ampliarlo.

## Descargar

```sh
bin/anyassistant corpus fetch      # descarga unos 85 MB; la caché ocupa unos 250 MB con los casos construidos
bin/anyassistant corpus status     # qué hay en la caché y en el manifiesto
bin/anyassistant corpus fetch --check   # vuelve a comprobar los hashes de lo descargado
```

Solo se descarga lo que nombra el manifiesto, nunca un dataset entero: los archivos de un `tar`
por su rango de bytes, el grupo de filas de un Parquet, un miembro de un `zip` (peticiones HTTP
`Range`; los servidores de Hugging Face, OpenSLR y Zenodo las admiten), y los `tar.gz` de FLEURS
en *streaming* hasta encontrar el último archivo que hace falta. Cada archivo se comprueba con el
SHA-256 del manifiesto antes de usarse; uno que no coincida es un error que lo nombra. Las fuentes
de Hugging Face van fijadas a un *commit*. Hace falta `pyarrow` (viene con `uv sync`).

**Common Voice**: desde octubre de 2025 la descarga oficial exige una cuenta en Mozilla Data
Collective. El manifiesto usa una copia de la versión 17.0 publicada en Hugging Face
(`fsicoli/common_voice_17_0`, fijada a un *commit*): la licencia CC0 lo permite. Si prefieres la
descarga oficial, o la copia deja de estar: baja el español de Common Voice 17.0 de
<https://datacollective.mozilla.org/> (o <https://commonvoice.mozilla.org/>) aceptando sus
condiciones, descomprímelo y pasa la carpeta con `clips/`:

```sh
bin/anyassistant corpus fetch --common-voice ~/Downloads/cv-corpus-17.0-2024-03-15/es
```

Los archivos de una copia oficial pueden no ser byte a byte los del manifiesto (otra codificación
del MP3); entonces avisa de cada uno y los usa igual, y lo dice en el resumen.

## Ejecutar y comparar

```sh
bin/anyassistant corpus run                       # todo; compara con baseline.json
bin/anyassistant corpus run --limit 5             # los 5 primeros casos de cada tipo (5 hablantes de Common Voice)
bin/anyassistant corpus run --engine mlx-whisper  # solo ese motor (por defecto, los instalados)
bin/anyassistant corpus run --silence 0.6         # solo ese valor de «silence» (por defecto 0,4, 0,6, 0,8 y 1,0)
bin/anyassistant corpus run --json resultados.json   # guarda los resultados por caso
```

Cada caso pasa por un `Ear` como lo mandaría un dispositivo (PCM a 48 kHz en trozos de 20 ms), con
los ajustes por defecto del servidor (no los de tu `settings.json`), y lo que el oído corta va al
motor, como cuando escucha el asistente. Se mide:

- **Transcripción**: el WER (errores de palabra, en % de las palabras esperadas) de lo que salió
  del oído, por motor: voz limpia por idioma y por fuente, con ruido por SNR, en habitación; y el
  porcentaje de frases exactas. Y las frases **fantasma**: casos de solo ruido que salieron como
  texto (lo que llegaría al modelo de lenguaje).
- **Fin de frase**: con cada valor de `silence`, cuántas frases hizo el oído de cada caso de una
  frase: una (bien), más (la partió), ninguna (la perdió).
- **Voz con ruido**: arranques en falso en los casos de solo ruido (una frase mandada al motor),
  por valor de `silence`, en total y por minuto de ruido.
- **Quién habla**: cada hablante de Common Voice se aprende con su primer y tercer clip (el
  `learn` del plugin) y se juzga con el segundo y el cuarto (`judge`), limpios, con ruido y en
  habitación. Por cada prueba: su puntuación con su propia huella y con las de los otros 59
  (impostores). De ahí: aceptados, dudosos y descartados a `voice_match` (0,5) y a su cota inferior
  (0,3), confundidos con otra persona, y el EER (donde se igualan falsos aceptados y falsos
  rechazos) con su umbral: una referencia para el valor por defecto.

Con el baseline, `run` compara **lo mismo con lo mismo**: si corres con `--limit` o sin algún motor,
el baseline se restringe a esos casos (y, en las voces, a esos hablantes) antes de resumirlo. Con
pocos casos una sola palabra mueve el WER de un grupo varios puntos, y Whisper no es del todo
determinista: el subconjunto sirve para ver que todo funciona; la referencia es la ejecución entera. Imprime cada métrica que se movió, los
casos que cambiaron de lado (una frase antes bien y ahora mal, con los dos textos; una frase
partida; un hablante antes aceptado y ahora dudoso), y falla si algo empeora más que la
tolerancia (`run.TOLERANCE`: 2 puntos de WER, 3 de frases exactas o de frases enteras, 2
arranques en falso o frases fantasma más, 2 puntos de aceptados, 1 de impostores aceptados, de
confundidos o de EER).

La prueba de pytest hace lo mismo, y está **desactivada por defecto** (la ejecución normal sigue
siendo rápida y sin red: `addopts` quita `corpus` como quita `e2e`):

```sh
.venv/bin/python -m pytest -m corpus -q                    # todo (unos 20 minutos en un Mac con Parakeet y Whisper)
CORPUS_LIMIT=5 .venv/bin/python -m pytest -m corpus -q     # un subconjunto
```

Si el corpus no está en la caché, se salta y dice cómo descargarlo. Las pruebas rápidas de
`tests/test_corpus.py` (normalización, WER, mezcla, manifiesto, comparación) sí corren siempre.

## Los primeros números (2 de noviembre de 2026, Mac con Apple Silicon)

Parakeet MLX 0.5.3 y Whisper MLX 0.4.3 (large-v3-turbo), Silero VAD 6.2.3; unos 20 minutos.

| | Parakeet | Whisper |
|---|---|---|
| WER voz limpia, español (300 frases) | 3,3 % (74 % exactas) | 3,7 % (74 %) |
| WER voz limpia, inglés (25) | 4,3 % | 4,1 % |
| WER con ruido a 20 / 10 / 5 dB | 5,0 / 17,7 / 22,0 % | 7,5 / 18,5 / 21,6 % |
| WER en habitación (20) | 2,6 % | 4,1 % |
| Frases fantasma de 22 cortes de ruido | 2 | 3 |

Las frases fantasma salen casi todas del ruido de «sala de reuniones» de DEMAND, que **contiene
voces** (gente hablando de fondo): el oído las corta y el motor las transcribe («So the database
that we are recording is…»); es el caso de la tele o una conversación al lado. Lo mismo explica las
frases «perdidas» en los casos mezclados: con esa charla a 5 o 10 dB el detector no encuentra
silencio para cerrar la frase. Y una muestra de a qué se parece el error: Parakeet se fue al
inglés en un clip («It don't call it seen no better») sin que el detector de idioma lo cogiese.

Fin de frase, sobre 453 casos de una frase: con `silence` 0,4 s el 84,5 % salen enteras (14,6 %
partidas); con **0,6 s (el valor por defecto), el 92,1 %** (6,4 % partidas, 1,5 % perdidas); con
0,8 s, el 93,2 %; con 1,0 s, el 96,0 %. Las partidas con 0,6 son sobre todo de audiolibros (MLS:
12 de 20, con pausas de lectura) y 9 de 240 de Common Voice. Arranques en falso en 22 cortes de
ruido: 7 con 0,4 s, 5 con 0,6 o más. Los números apoyan dejar 0,6 (una décima más de latencia
por cada 0,1 s) y no bajarlo; subir a 0,8 ganaría un punto de frases enteras.

Quién habla, 60 hablantes, 120 pruebas limpias y 7 080 puntuaciones de impostor: con `voice_match`
0,5 se acepta el 99,2 % de las frases del propio hablante y el 0,23 % de las de impostores (en el
10,8 % de las pruebas algún impostor de los 59 pasaría); el EER es del 0,8 % en 0,45. Con la cota
inferior 0,30 se descarta de entrada el 91,2 % de los desconocidos y ningún hablante propio
(limpio); con ruido a 5 dB, el 8,3 % de los propios caen por debajo. Con 0,55 los impostores
aceptados bajarían al 0,07 % perdiendo 1,7 puntos de propios. Los números apoyan dejar 0,5 y 0,30.
No se ha cambiado ningún valor por defecto.

## Cambiar el baseline

Cuando un cambio es deseado (un motor nuevo, otro umbral, otra versión de un modelo) y las cifras
nuevas son las buenas:

```sh
bin/anyassistant corpus baseline     # mide todo (sin --limit) y escribe tests/corpus/baseline.json
```

Y se sube con el cambio. El baseline guarda los resultados por caso (texto transcrito, frases,
puntuaciones) y el resumen, con la máquina y las versiones de los paquetes de voz con que se hizo:
los números dependen del motor y de su modelo, así que un baseline hecho en un Mac (Parakeet MLX,
Whisper MLX) solo compara esos motores; en Linux o Windows (faster-whisper, Parakeet ONNX) los
motores sin baseline se miden y se anotan, sin fallar, hasta que alguien escriba uno con ellos.

## Licencias

| Fuente | Licencia | Dónde |
|---|---|---|
| Mozilla Common Voice 17.0 (español) | CC0 1.0 | <https://commonvoice.mozilla.org/>; copia usada: `fsicoli/common_voice_17_0` en Hugging Face |
| FLEURS (Google) | CC BY 4.0 | <https://huggingface.co/datasets/google/fleurs> |
| Multilingual LibriSpeech (Meta) | CC BY 4.0 | <https://www.openslr.org/94/>; en Parquet: `facebook/multilingual_librispeech` |
| MUSAN (Snyder, Chen y Povey), parte de ruidos | CC BY 4.0 | <https://www.openslr.org/17/>; copia en Parquet: `corypaik/musan` |
| DEMAND (Thiemann, Ito y Vincent) | CC BY 4.0 según Zenodo (la página de los autores dice CC BY-SA) | <https://zenodo.org/records/1227121> |
| RIRS_NOISES, OpenSLR SLR28 (Ko et al.; incluye respuestas reales de AIR y RWCP) | Apache 2.0 | <https://www.openslr.org/28/> |

Todas permiten este uso (medir, en privado, sin redistribuir el audio). El manifiesto repite la
licencia y la dirección de cada fuente (`sources`), con la revisión exacta. Si alguna vez se
publicaran resultados con fragmentos de audio, las CC BY exigen citar la fuente.

## Qué no cubre

- **La palabra de activación**: cada casa le pone su nombre al asistente, así que no hay casos de
  *wake word*; tampoco palabras parecidas, que son cosa del detector de la palabra y no del de voz.
- **El micrófono real y la cancelación de eco** de cada dispositivo, el transporte (Opus, pérdidas)
  y lo que el asistente hace después (eco de su propia voz, comandos, el modelo de lenguaje): el
  corpus entra en el oído ya como PCM limpio a 48 kHz.
- **Voces de casa**: nadie de los que usan el asistente está en el corpus, a propósito. Las cifras
  de quién habla salen de hablantes de Common Voice (clips cortos, micrófonos variados), que es un
  caso más difícil que una voz aprendida con el mismo micrófono con el que se usa: son una
  referencia relativa (si un cambio las empeora) y una pista para el umbral, no una garantía.
- **Español de España** en Common Voice: la mayoría de los clips sin acento declarado son de
  América (el *test* de la 17.0 es así); FLEURS es `es_419`. Las frases de MLS son de audiolibros
  de dominio público, con un vocabulario antiguo.
- **Música y televisión** como ruido (MUSAN tiene una parte de música, de 4 GB; no se ha incluido).
- **Conversaciones**: cada caso es una frase; no hay turnos ni dos voces a la vez.
