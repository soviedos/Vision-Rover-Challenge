"""Verifica el árbitro: el mapa de transiciones y el cronómetro oficial.

    python -m vision.tools.verificar_ronda

Por qué con un reloj inyectado y no durmiendo
---------------------------------------------
Una ronda dura diez minutos y la preparación uno. Verificar el cierre por tiempo
agotado durmiendo esos minutos haría que nadie corriera nunca esta herramienta, y
una verificación que no se corre no verifica nada. `Arbitro` acepta el reloj como
argumento justamente para esto: acá se le pasa uno falso que avanza cuando se le
dice, y las transiciones se prueban en el instante exacto del límite en vez de
"cerca".

Qué se comprueba, y por qué cada caso
-------------------------------------
Las transiciones que NO se pueden hacer importan tanto como las que sí:

- que `start` **no exista** como comando es la regla que sostiene que todos los
  equipos preparen con el mismo tiempo;
- que `ready` **se rechace desde READY** impide estirar la preparación
  apretando una tecla;
- que arrancar en `RUNNING` **lance**, porque una ronda sin preparación ni
  cronómetro desde cero parece válida y no lo es;
- que el cierre por reto cumplido **no dispare** si los cubos ya estaban puestos
  al arrancar, que es lo que pasa cuando nadie los sacó de la ronda anterior;
- que el tiempo del reto sea el de la **entrada** del último cubo y no el de la
  confirmación de la permanencia, que llega un segundo más tarde.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

try:  # como paquete
    from ..configuracion import Ronda, cargar_config
    from ..sistema import (
        MOTIVO_ABORTADA, MOTIVO_OPERADOR, MOTIVO_RETO, MOTIVO_TIEMPO, Arbitro, _TRANSICIONES,
    )
except ImportError:  # como script suelto
    from vision.configuracion import Ronda, cargar_config  # type: ignore[no-redef]
    from vision.sistema import (  # type: ignore[no-redef]
        MOTIVO_ABORTADA, MOTIVO_OPERADOR, MOTIVO_RETO, MOTIVO_TIEMPO, Arbitro, _TRANSICIONES,
    )

PREPARACION_MS = 60_000
DURACION_MS = 600_000


class RelojFalso:
    """Un reloj monótono que solo avanza cuando se lo pide."""

    def __init__(self, t0: float = 1000.0):
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def avanzar(self, ms: float) -> None:
        self.t += ms / 1000.0


def _config():
    cfg = cargar_config()
    return dataclasses.replace(
        cfg, ronda=Ronda(preparacion_ms=PREPARACION_MS, duracion_ms=DURACION_MS))


def _arbitro(cfg, inicial="IDLE"):
    reloj = RelojFalso()
    return Arbitro(cfg, inicial, reloj=reloj), reloj


def verificar_transiciones(cfg) -> bool:
    print("=" * 78)
    print("TRANSICIONES: quién puede mover la ronda, y quién no")
    print("=" * 78)
    print("  {:<52} {:>10} {:>10}  {}".format("situación", "queda en", "se esperaba", "estado"))
    print("  " + "-" * 88)

    casos = []

    # --- las que hace una persona ---------------------------------------
    a, _ = _arbitro(cfg)
    a.intentar("ready")
    casos.append(("IDLE + ready", a.fase, "READY"))

    a, _ = _arbitro(cfg, "READY")
    a.intentar("ready")
    casos.append(("READY + ready (reiniciar la preparación)", a.fase, "READY"))

    a, _ = _arbitro(cfg, "READY")
    a.intentar("abort")
    casos.append(("READY + abort", a.fase, "IDLE"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    casos.append(("RUNNING + stop", a.fase, "FINISHED"))

    a, _ = _arbitro(cfg)
    a.intentar("stop")
    casos.append(("IDLE + stop (sin ronda en juego)", a.fase, "IDLE"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    a.intentar("ready")
    casos.append(("FINISHED + ready (ronda siguiente)", a.fase, "READY"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    a.intentar("abort")
    casos.append(("FINISHED + abort (resetear la cancha)", a.fase, "IDLE"))

    # --- las que hace el reloj ------------------------------------------
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS - 1)
    a.tictac()
    casos.append(("READY, un milisegundo ANTES del límite", a.fase, "READY"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    casos.append(("READY, justo en el límite", a.fase, "RUNNING"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS - 1)
    a.tictac()
    casos.append(("RUNNING, un milisegundo ANTES del límite", a.fase, "RUNNING"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS)
    a.tictac()
    casos.append(("RUNNING, justo en el límite", a.fase, "FINISHED"))

    todo_bien = True
    for nombre, obtenido, esperado in casos:
        paso = obtenido == esperado
        todo_bien = todo_bien and paso
        print("  {:<52} {:>10} {:>10}  {}".format(
            nombre, obtenido, esperado, "OK" if paso else "FALLA"))

    # --- lo que NO tiene que existir -------------------------------------
    print()
    sin_start = "start" not in _TRANSICIONES
    print("  {:<52} {:>10} {:>10}  {}".format(
        "'start' NO es un comando", "ausente" if sin_start else "existe", "ausente",
        "OK" if sin_start else "FALLA"))
    todo_bien = todo_bien and sin_start

    try:
        Arbitro(cfg, "RUNNING")
        arranca_en_running = True
    except ValueError:
        arranca_en_running = False
    print("  {:<52} {:>10} {:>10}  {}".format(
        "arrancar en RUNNING", "lanza" if not arranca_en_running else "acepta", "lanza",
        "OK" if not arranca_en_running else "FALLA"))
    todo_bien = todo_bien and not arranca_en_running

    # --- los motivos del cierre ------------------------------------------
    print()
    print("  {:<52} {:>24}  {}".format("motivo del cierre", "se esperaba", "estado"))
    print("  " + "-" * 88)
    motivos = []

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS)
    a.tictac()
    motivos.append(("se agotó la ronda", a.motivo, MOTIVO_TIEMPO))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    motivos.append(("la cerró el operador", a.motivo, MOTIVO_OPERADOR))

    a, _ = _arbitro(cfg, "READY")
    a.intentar("abort")
    motivos.append(("abortada en preparación", a.motivo, MOTIVO_ABORTADA))

    for nombre, obtenido, esperado in motivos:
        paso = obtenido == esperado
        todo_bien = todo_bien and paso
        print("  {:<52} {:>24}  {}".format(
            nombre, esperado, "OK" if paso else "FALLA: {}".format(obtenido)))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def verificar_reloj(cfg) -> bool:
    print("=" * 78)
    print("CRONÓMETRO: los tres valores que viajan en el mensaje")
    print("=" * 78)
    print("  {:<44} {:>11} {:>11} {:>11}  {}".format(
        "situación", "transcurr.", "restante", "total", "estado"))
    print("  " + "-" * 92)

    casos = []

    a, _ = _arbitro(cfg)
    casos.append(("IDLE: no se cuenta nada", a.reloj(), (0, 0, 0)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(20_000)
    casos.append(("READY a los 20 s", a.reloj(), (20_000, 40_000, PREPARACION_MS)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    casos.append(("RUNNING recién empezada", a.reloj(), (0, DURACION_MS, DURACION_MS)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(90_000)
    casos.append(("RUNNING al minuto y medio", a.reloj(),
                  (90_000, DURACION_MS - 90_000, DURACION_MS)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS)
    a.tictac()
    reloj.avanzar(30_000)  # el reloj sigue, el cronómetro NO
    casos.append(("FINISHED por tiempo, 30 s después", a.reloj(),
                  (DURACION_MS, 0, DURACION_MS)))

    # El caso que SIEMPRE ocurre en la realidad y que la primera versión de esta
    # herramienta no probaba: `tictac` no se entera en el instante exacto del
    # vencimiento, sino en el cuadro siguiente. El transcurrido real se pasa, y
    # sin recortar al total el mensaje viola el invariante que el contrato
    # valida. Se descubrió en el simulador: 5019 ms sobre una ronda de 5000.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS + 19)
    a.tictac()
    reloj.avanzar(DURACION_MS + 347)   # el bucle se entera 347 ms tarde
    a.tictac()
    casos.append(("FINISHED habiéndose PASADO 347 ms", a.reloj(),
                  (DURACION_MS, 0, DURACION_MS)))

    # Lo mismo cerrando a mano, donde el recorte no tiene que hacer nada.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(72_500)
    a.intentar("stop")
    casos.append(("FINISHED por el operador a los 72,5 s", a.reloj(),
                  (72_500, DURACION_MS - 72_500, DURACION_MS)))

    todo_bien = True
    for nombre, r, esperado in casos:
        obtenido = (r.transcurrido_ms, r.restante_ms, r.total_ms)
        paso = obtenido == esperado
        todo_bien = todo_bien and paso
        print("  {:<44} {:>11} {:>11} {:>11}  {}".format(
            nombre, r.transcurrido_ms, r.restante_ms, r.total_ms,
            "OK" if paso else "FALLA, se esperaba {}".format(esperado)))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def verificar_reto_cumplido(cfg) -> bool:
    """El cierre por reto cumplido: cuándo dispara y con qué tiempo."""
    print("=" * 78)
    print("RETO CUMPLIDO: el cierre automático y el instante que se registra")
    print("=" * 78)

    todo_bien = True

    # Caso 1: los tres cubos YA estaban puestos al arrancar.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(5_000)
    a.observar_reto(True, reloj())          # completo desde el primer cuadro
    reloj.avanzar(5_000)
    a.observar_reto(True, reloj())
    paso = a.fase == "RUNNING"
    todo_bien = todo_bien and paso
    print("  {:<58} {:>8}  {}".format(
        "arranca con los tres cubos ya adentro: NO cierra", a.fase, "OK" if paso else "FALLA"))

    # Caso 2: incompleto y después completo. El tiempo es el de la ENTRADA.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(120_000)
    a.observar_reto(False, None)            # todavía faltan cubos
    reloj.avanzar(60_000)
    entrada = reloj()                       # entra el último cubo: 180 s de ronda
    reloj.avanzar(1_000)                    # se cumple la permanencia un segundo después
    a.observar_reto(True, entrada)
    cerro = a.fase == "FINISHED" and a.motivo == MOTIVO_RETO
    tiempo = a.tiempo_final_ms
    paso = cerro and tiempo == 180_000
    todo_bien = todo_bien and paso
    print("  {:<58} {:>8}  {}".format(
        "cumplido a los 180 s, confirmado a los 181: registra",
        "{} s".format(tiempo / 1000.0 if tiempo is not None else "—"),
        "OK" if paso else "FALLA: esperaba 180.0 s"))

    # Caso 3: el cronómetro queda detenido a la vista.
    reloj.avanzar(45_000)
    r = a.reloj()
    paso = r.transcurrido_ms == 180_000 and r.restante_ms == DURACION_MS - 180_000
    todo_bien = todo_bien and paso
    print("  {:<58} {:>8}  {}".format(
        "el cronómetro queda detenido, y sobra lo que sobró",
        "{} s".format(r.transcurrido_ms / 1000.0), "OK" if paso else "FALLA"))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Verifica el árbitro de la ronda: transiciones y cronómetro."
    ).parse_args(argv)

    cfg = _config()
    print()
    print("  preparación: {} s   ·   ronda: {} s   (valores de prueba)".format(
        PREPARACION_MS / 1000, DURACION_MS / 1000))
    print()
    resultados = [
        verificar_transiciones(cfg),
        verificar_reloj(cfg),
        verificar_reto_cumplido(cfg),
    ]
    print("=" * 78)
    print("RESULTADO GENERAL: {}".format("TODO OK" if all(resultados) else "HAY FALLAS"))
    print("=" * 78)
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
