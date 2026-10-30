# TODO

## Antes del uso diario

- [ ] **Emparejamiento**: ahora cualquiera en la Wi-Fi puede conectarse y usar Jarvis
  (que ya puede enviar correos y borrar). Un código que la tablet guarda la primera
  vez y sin el que el servidor no acepta conexiones.
- [ ] **Servicio de macOS (launchd)**: que el servidor arranque solo con el Mac y se
  reinicie si falla, sin depender de una sesión de terminal.
- [ ] **Dejar de grabar**: quitar `--grabar` del arranque habitual y borrar las
  grabaciones de depuración.

## Calidad de la conversación

- [ ] **Interrumpir por voz** («Jarvis, para») mientras habla; hoy solo tocando la
  pantalla. Difícil con la cancelación de eco de la tablet.
- [ ] **Latencia** (~2–3 s, casi todo hasta la primera frase de Claude): arrancar el
  proceso antes, Haiku para respuestas cortas…
- [ ] **Palabra de activación**: vigilar falsos positivos y negativos; quizá un nombre
  en español.

## Funciones

- [ ] **Ojos (Fase 4)**: mirar por la cámara cuando se pida («¿qué ves?», «lee esto»).
- [ ] **Memoria entre conversaciones** con Claude (Hermes ya la tiene).
- [ ] **Cara**: que la pantalla sea más expresiva que un círculo de colores.
- [ ] **App nativa Android**: arranque al encender, pantalla apagada (Fase 6).

## Mantenimiento

- [ ] **Pruebas automáticas** en el repositorio (las de ahora son scripts sueltos).

## Pendiente de hacer a mano

- [ ] Reautorizar **Holded**: `claude` en la carpeta del proyecto → `/mcp` → holded.
- [ ] **Publicar la app de Google** (Google Auth Platform → Público) para que la
  autorización no caduque cada 7 días; luego `bin/gog-autorizar` otra vez.
- [ ] **IP fija para el Mac** (Wi-Fi → Detalles → Dirección privada: Fija, o reserva
  DHCP en el router).
