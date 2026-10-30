"""google: Gmail, Calendar y Drive en solo lectura, para que Jarvis los consulte.

    bin/google autorizar                         abre el navegador una vez
    bin/google gmail buscar "is:unread" [-n 10]  correos (búsqueda de Gmail)
    bin/google gmail contar "is:unread"          cuántos hay
    bin/google gmail leer <id>                   un correo entero
    bin/google calendario eventos [--desde hoy] [--dias 7] [--buscar texto]
    bin/google calendario calendarios
    bin/google drive buscar "texto" [-n 10]
    bin/google drive recientes [-n 10]
    bin/google drive leer <id>                   Docs como texto, Hojas como CSV

Usa las APIs normales de Google con un cliente OAuth propio (google-cliente.json,
de Google Cloud, tipo «Aplicación de escritorio») y solo permisos de lectura:
aunque se intentara, Google no dejaría escribir. El token se guarda en
google-token.json. Los dos, en la raíz del proyecto y fuera de git.
"""

import argparse
import base64
import datetime as dt
import html
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CLIENTE = RAIZ / "google-cliente.json"
TOKEN = RAIZ / "google-token.json"
PERMISOS = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
MAXIMO_TEXTO = 6000  # caracteres al leer un correo o un archivo


def error(mensaje: str):
    print(mensaje, file=sys.stderr)
    sys.exit(1)


# --- Credenciales ------------------------------------------------------------

def autorizar(_args):
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENTE.exists():
        error(f"Falta {CLIENTE.name}: descarga el JSON del cliente OAuth de Google Cloud.")
    credenciales = InstalledAppFlow.from_client_secrets_file(str(CLIENTE), PERMISOS).run_local_server(port=0)
    TOKEN.write_text(credenciales.to_json())
    print("Autorizado.")


def credenciales():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN.exists():
        error("Google no está autorizado: hay que ejecutar «bin/google autorizar».")
    creds = Credentials.from_authorized_user_file(str(TOKEN), PERMISOS)
    if not creds.valid:
        if not creds.refresh_token:
            error("La autorización de Google ha caducado: hay que ejecutar «bin/google autorizar».")
        try:
            creds.refresh(Request())
        except Exception:
            error("La autorización de Google ha caducado: hay que ejecutar «bin/google autorizar».")
        TOKEN.write_text(creds.to_json())
    return creds


def servicio(nombre: str, version: str):
    from googleapiclient.discovery import build

    return build(nombre, version, credentials=credenciales(), cache_discovery=False)


def recortar(texto: str) -> str:
    texto = re.sub(r"\n{3,}", "\n\n", texto.strip())
    if len(texto) > MAXIMO_TEXTO:
        return texto[:MAXIMO_TEXTO] + f"\n[… recortado: {len(texto)} caracteres en total]"
    return texto


DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def corta(momento: dt.date | dt.datetime) -> str:
    """«vie 31/10 09:30» (o «vie 31/10» si es un día): sin depender del idioma del sistema."""
    texto = f"{DIAS[momento.weekday()]} {momento.day:02d}/{momento.month:02d}"
    return f"{texto} {momento:%H:%M}" if isinstance(momento, dt.datetime) else texto


def fecha_local(valor: str) -> str:
    """ISO de Google → «vie 31/10 09:30» en la hora local."""
    return corta(dt.datetime.fromisoformat(valor.replace("Z", "+00:00")).astimezone())


# --- Gmail -------------------------------------------------------------------

def gmail_buscar(args):
    gmail = servicio("gmail", "v1")
    ids = gmail.users().messages().list(userId="me", q=args.consulta, maxResults=args.n).execute()
    mensajes = ids.get("messages", [])
    if not mensajes:
        print("Ningún correo.")
        return
    for m in mensajes:
        datos = gmail.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        cab = {h["name"]: h["value"] for h in datos["payload"].get("headers", [])}
        fecha = corta(dt.datetime.fromtimestamp(int(datos["internalDate"]) / 1000))
        print(f"[{m['id']}] {fecha} · {cab.get('From', '?')} · {cab.get('Subject', '(sin asunto)')}")
        print(f"    {html.unescape(datos.get('snippet', ''))[:160]}")


def gmail_contar(args):
    gmail = servicio("gmail", "v1")
    total, pagina = 0, None
    while True:
        r = gmail.users().messages().list(
            userId="me", q=args.consulta, maxResults=500, pageToken=pagina
        ).execute()
        total += len(r.get("messages", []))
        pagina = r.get("nextPageToken")
        if not pagina or total >= 2000:
            break
    print(f"{total}{' o más' if pagina else ''} correos.")


def _cuerpo(parte) -> str:
    """El texto de un correo: text/plain si hay; si no, el HTML sin etiquetas."""
    planos, htmls = [], []

    def recorrer(p):
        datos = p.get("body", {}).get("data")
        if datos and p.get("mimeType") == "text/plain":
            planos.append(base64.urlsafe_b64decode(datos).decode("utf-8", "replace"))
        elif datos and p.get("mimeType") == "text/html":
            htmls.append(base64.urlsafe_b64decode(datos).decode("utf-8", "replace"))
        for hija in p.get("parts", []):
            recorrer(hija)

    recorrer(parte)
    if planos:
        return "\n".join(planos)
    sin_etiquetas = re.sub(r"<(style|script)[^>]*>.*?</\1>|<[^>]+>", " ", "\n".join(htmls), flags=re.S)
    return html.unescape(re.sub(r"[ \t]+", " ", sin_etiquetas))


def gmail_leer(args):
    gmail = servicio("gmail", "v1")
    datos = gmail.users().messages().get(userId="me", id=args.id, format="full").execute()
    cab = {h["name"]: h["value"] for h in datos["payload"].get("headers", [])}
    for nombre in ("From", "To", "Date", "Subject"):
        print(f"{nombre}: {cab.get(nombre, '')}")
    print()
    print(recortar(_cuerpo(datos["payload"])))


# --- Calendar ----------------------------------------------------------------

def _dia(valor: str) -> dt.date:
    hoy = dt.date.today()
    return {"hoy": hoy, "mañana": hoy + dt.timedelta(days=1), "ayer": hoy - dt.timedelta(days=1)}.get(
        valor
    ) or dt.date.fromisoformat(valor)


def calendario_eventos(args):
    cal = servicio("calendar", "v3")
    inicio = dt.datetime.combine(_dia(args.desde), dt.time()).astimezone()
    fin = inicio + dt.timedelta(days=args.dias)
    calendarios = [
        c for c in cal.calendarList().list().execute().get("items", []) if c.get("selected", True)
    ]
    eventos = []
    for c in calendarios:
        r = cal.events().list(
            calendarId=c["id"], timeMin=inicio.isoformat(), timeMax=fin.isoformat(),
            singleEvents=True, orderBy="startTime", q=args.buscar, maxResults=100,
        ).execute()
        for e in r.get("items", []):
            empieza = e["start"].get("dateTime") or e["start"].get("date")
            eventos.append((empieza, c.get("summary", ""), e))
    if not eventos:
        print("Ningún evento.")
        return
    for empieza, calendario, e in sorted(eventos, key=lambda x: x[0]):
        cuando = (
            fecha_local(empieza) if "T" in empieza
            else corta(dt.date.fromisoformat(empieza)) + " (todo el día)"
        )
        lugar = f" · {e['location']}" if e.get("location") else ""
        print(f"{cuando} · {e.get('summary', '(sin título)')}{lugar} [{calendario}]")


def calendario_calendarios(_args):
    cal = servicio("calendar", "v3")
    for c in cal.calendarList().list().execute().get("items", []):
        print(f"{c.get('summary')}{' (principal)' if c.get('primary') else ''}")


# --- Drive -------------------------------------------------------------------

CAMPOS = "files(id,name,mimeType,modifiedTime)"
EXPORTAR = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def _listar(archivos):
    if not archivos:
        print("Ningún archivo.")
    for a in archivos:
        tipo = a["mimeType"].rsplit(".", 1)[-1].rsplit("/", 1)[-1]
        print(f"[{a['id']}] {fecha_local(a['modifiedTime'])} · {a['name']} ({tipo})")


def drive_buscar(args):
    drive = servicio("drive", "v3")
    texto = args.texto.replace("\\", "\\\\").replace("'", "\\'")
    q = f"(name contains '{texto}' or fullText contains '{texto}') and trashed = false"
    _listar(drive.files().list(q=q, pageSize=args.n, fields=CAMPOS).execute().get("files", []))


def drive_recientes(args):
    drive = servicio("drive", "v3")
    _listar(drive.files().list(
        q="trashed = false", orderBy="modifiedTime desc", pageSize=args.n, fields=CAMPOS
    ).execute().get("files", []))


def drive_leer(args):
    drive = servicio("drive", "v3")
    archivo = drive.files().get(fileId=args.id, fields="name,mimeType").execute()
    tipo = archivo["mimeType"]
    if tipo in EXPORTAR:
        datos = drive.files().export(fileId=args.id, mimeType=EXPORTAR[tipo]).execute()
    elif tipo.startswith("text/") or tipo in ("application/json", "text/csv"):
        datos = drive.files().get_media(fileId=args.id).execute()
    else:
        error(f"«{archivo['name']}» es {tipo}: solo sé leer documentos, hojas, presentaciones y texto.")
    print(f"{archivo['name']}\n")
    print(recortar(datos.decode("utf-8", "replace")))


# --- Órdenes -----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="google", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="servicio", required=True)
    sub.add_parser("autorizar").set_defaults(funcion=autorizar)
    sub.add_parser("ayuda").set_defaults(funcion=lambda _: print(__doc__.strip()))

    gmail = sub.add_parser("gmail").add_subparsers(dest="orden", required=True)
    p = gmail.add_parser("buscar")
    p.add_argument("consulta")
    p.add_argument("-n", type=int, default=10)
    p.set_defaults(funcion=gmail_buscar)
    p = gmail.add_parser("contar")
    p.add_argument("consulta")
    p.set_defaults(funcion=gmail_contar)
    p = gmail.add_parser("leer")
    p.add_argument("id")
    p.set_defaults(funcion=gmail_leer)

    cal = sub.add_parser("calendario").add_subparsers(dest="orden", required=True)
    p = cal.add_parser("eventos")
    p.add_argument("--desde", default="hoy", help="hoy, mañana, ayer o AAAA-MM-DD")
    p.add_argument("--dias", type=int, default=7)
    p.add_argument("--buscar", default=None)
    p.set_defaults(funcion=calendario_eventos)
    cal.add_parser("calendarios").set_defaults(funcion=calendario_calendarios)

    drive = sub.add_parser("drive").add_subparsers(dest="orden", required=True)
    p = drive.add_parser("buscar")
    p.add_argument("texto")
    p.add_argument("-n", type=int, default=10)
    p.set_defaults(funcion=drive_buscar)
    p = drive.add_parser("recientes")
    p.add_argument("-n", type=int, default=10)
    p.set_defaults(funcion=drive_recientes)
    p = drive.add_parser("leer")
    p.add_argument("id")
    p.set_defaults(funcion=drive_leer)

    args = parser.parse_args()
    try:
        args.funcion(args)
    except SystemExit:
        raise
    except Exception as e:
        error(f"Error de Google: {e}")


if __name__ == "__main__":
    main()
