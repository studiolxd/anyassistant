"""Servidor: sirve la web del móvil y hace la señalización WebRTC.

    uv run server/main.py                    # asistente: Parakeet + Claude (CLI) + AVSpeech
    uv run server/main.py --llm apple        # con el modelo de Apple, en local
    uv run server/main.py --voz Eddy         # otra voz de macOS; --tts ninguno, sin voz
    uv run server/main.py --silencio 0.45    # cierra antes las frases (más rápido)
    uv run server/main.py --modo transcribir # solo transcribe
    uv run server/main.py --llm otro-plugin  # cualquier módulo de server/llm/
    uv run server/main.py --modo loro        # repite lo que oye (prueba de audio)
    uv run server/main.py --stt otro-plugin  # cualquier módulo de server/stt/
    uv run server/main.py --despertar ninguno  # sin palabra de activación
"""

import argparse
import asyncio
import logging
import uuid
from pathlib import Path

from aiohttp import web

import despertar
import llm
import stt
import tts
from cerebro import asistente, transcriptor
from cerebro.loro import Loro
from transporte import Sesion

WEB = Path(__file__).resolve().parent.parent / "web"
sesiones: dict[str, Sesion] = {}
fabrica_cerebro = Loro  # lo fija main() según --modo
cerrar_al_salir = []  # corrutinas a esperar al parar (procesos de los plugins)


async def offer(request: web.Request) -> web.Response:
    datos = await request.json()
    sesion = Sesion(uuid.uuid4().hex[:6], fabrica_cerebro)
    # Un solo móvil: la conexión nueva sustituye a las anteriores.
    for vieja in list(sesiones.values()):
        await vieja.cerrar()
    sesiones.clear()
    sesiones[sesion.id] = sesion
    respuesta = await sesion.responder(datos["sdp"], datos["type"])
    return web.json_response({"sdp": respuesta.sdp, "type": respuesta.type})


def sesion_actual() -> Sesion | None:
    return next(iter(sesiones.values()), None)


async def video_mjpeg(request: web.Request) -> web.StreamResponse:
    """Lo que ve la cámara, para mirarlo desde el navegador del Mac."""
    resp = web.StreamResponse(
        headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"}
    )
    await resp.prepare(request)
    while True:
        sesion = sesion_actual()
        imagen = sesion.jpeg() if sesion else None
        if imagen:
            await resp.write(
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + imagen + b"\r\n"
            )
        await asyncio.sleep(1 / 10)


async def estado(request: web.Request) -> web.Response:
    sesion = sesion_actual()
    return web.json_response(
        {
            "conectado": bool(sesion and sesion.pc.connectionState == "connected"),
            "frames": sesion.frames if sesion else 0,
        }
    )


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB / "index.html")


async def monitor(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB / "monitor.html")


@web.middleware
async def sin_cache(request: web.Request, handler):
    # Prototipo: que el móvil coja siempre la última versión de la web.
    # Y sin keep-alive: al reiniciar el servidor, Chrome 81 se quedaba colgado
    # reutilizando una conexión muerta en vez de abrir otra.
    resp = await handler(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.force_close()
    return resp


async def al_cerrar(app: web.Application):
    for sesion in sesiones.values():
        await sesion.cerrar()
    for cerrar in cerrar_al_salir:
        await cerrar()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--modo", choices=["loro", "transcribir", "asistente"], default="asistente")
    parser.add_argument("--stt", default="parakeet", help=f"plugin: {', '.join(stt.disponibles())}")
    parser.add_argument("--stt-modelo", default=None)
    parser.add_argument("--llm", default="claude", help=f"plugin: {', '.join(llm.disponibles())}")
    parser.add_argument("--llm-modelo", default=None)
    parser.add_argument("--tts", default="avspeech", help=f"voz: {', '.join(tts.disponibles())} o ninguno")
    parser.add_argument("--voz", default=None, help="voz del plugin (macos: Mónica, Eddy…)")
    parser.add_argument("--velocidad", type=int, default=None, help="palabras por minuto")
    parser.add_argument("--eco", type=float, default=1.2, help="segundos sin escuchar tras hablar")
    parser.add_argument("--idioma", default="es")
    parser.add_argument(
        "--despertar",
        default="whisper",
        help=f"palabra de activación: {', '.join(despertar.disponibles())} o ninguno",
    )
    parser.add_argument("--palabra", default=None, help="modelo de la palabra (hey_jarvis, alexa…)")
    parser.add_argument("--umbral", type=float, default=None, help="cada plugin tiene el suyo por defecto")
    parser.add_argument("--grabar", default=None, help="guarda en un WAV todo lo que llega (depurar)")
    parser.add_argument("--silencio", type=float, default=0.6, help="segundos de silencio que cierran una frase")
    parser.add_argument("--inactividad", type=float, default=120, help="segundos sin hablar para dormirse")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("aioice").setLevel(logging.WARNING)

    global fabrica_cerebro
    oido = {"grabar": args.grabar, "silencio": args.silencio, "inactividad": args.inactividad}
    if args.modo in ("transcribir", "asistente"):
        motor = stt.crear(args.stt, idioma=args.idioma, modelo=args.stt_modelo)
        logging.info("cargando STT %s (%s)…", motor.nombre, motor.modelo)
        motor.calentar()
        despertador = None
        if args.despertar != "ninguno":
            opciones = {"palabra": args.palabra}
            if args.umbral is not None:
                opciones["umbral"] = args.umbral
            logging.info("palabra de activación: %s", despertar.crear(args.despertar, **opciones).frase)
            despertador = lambda: despertar.crear(args.despertar, **opciones)
        if args.modo == "asistente":
            modelo = llm.crear(args.llm, modelo=args.llm_modelo)
            logging.info("LLM: %s (%s)", modelo.nombre, modelo.modelo)
            voz = None
            if args.tts != "ninguno":
                voz = tts.crear(args.tts, voz=args.voz, velocidad=args.velocidad)
                logging.info("voz: %s (%s)", voz.nombre, voz.voz)
                voz.calentar()

                async def cerrar_voz():
                    voz.cerrar()

                cerrar_al_salir.append(cerrar_voz)
            fabrica_cerebro = asistente.crear(motor, modelo, voz, despertador, oido, args.eco)
            cerrar_al_salir.append(modelo.cerrar)
        else:
            fabrica_cerebro = transcriptor.crear(motor, despertador, oido)
    else:
        fabrica_cerebro = Loro

    app = web.Application(middlewares=[sin_cache])
    app.router.add_get("/", index)
    app.router.add_get("/monitor", monitor)
    app.router.add_post("/offer", offer)
    app.router.add_get("/video.mjpg", video_mjpeg)
    app.router.add_get("/estado", estado)
    app.router.add_static("/web/", WEB)
    app.on_shutdown.append(al_cerrar)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
