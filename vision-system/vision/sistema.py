"""El sistema de visión: el programa que encadena todo y se enciende.

Cómo se corre:

    python -m vision.sistema                  # con la cámara real
    python -m vision.sistema --sintetico      # sin cámara, con imágenes generadas
    python -m vision.sistema --fase RUNNING   # arrancar ya en juego

Mientras corre, se escribe por teclado: `ready`, `start`, `stop`, `quit`.

Un solo sistema, y lo único que cambia es la entrada
-----------------------------------------------------
Este bucle es **el mismo** con la cámara real y con imágenes generadas. No hay
dos caminos ni dos programas: `FuenteCamara` y `FuenteSintetica` cumplen la
misma interfaz, así que todo lo que viene después no se entera de cuál le tocó.

**Lo sintético nunca arranca solo.** Sin argumentos se abre la cámara. Para
correr con imágenes generadas hay que pedirlo, y el sistema lo repite en pantalla
todo el tiempo: nadie tiene que poder confundir una demostración con una ronda.

Los dos relojes
---------------
Este bucle corre a la velocidad de la **cámara**. La publicación corre por su
**propio temporizador**, en otro hilo, y entre los dos hay una sola casilla con
el último estado bueno. Ninguno espera al otro (CLAUDE.md, sección 3).

Falla abierto
-------------
Cada cuadro se procesa dentro de un `try`. Si algo falla —se tapó un marcador de
esquina, la cámara devolvió basura, un detector se rompió— **no se actualiza la
casilla y se sigue**. La publicación continúa emitiendo el último estado bueno,
que envejece a la vista de todos.

El sistema **no se cae a mitad de una ronda**. Un dato de hace 300 milisegundos,
marcado como viejo, le sirve mucho más a un equipo que un silencio repentino.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

try:  # como paquete
    from .configuracion import CONFIG_POR_DEFECTO, ConfigVision, avisos_config, cargar_config
    from .detectors.cubos import detectar_cubos
    from .detectors.rovers import detectar_rovers
    from .geometry.coordenadas import (
        AnclajeCancha, ErrorDuplicado, ErrorGeometria, detectar_marcadores_crudo,
        filtrar_plausibles, pose_camara, resolver_duplicados,
    )
    from .geometry.distorsion import (
        ErrorCalibracion, FuenteRectificada, Rectificador, comparar_con_camara, elegir_perfil,
    )
    from .mundo import VERSION_PROTOCOLO, RelojRonda
    from .publish.puerto import ErrorPuerto
    from .publish.telemetria import PublicadorTelemetria
    from .record.acta import escribir_acta, mmss
    from .reglas.acopio import ContadorAcopio
    from .tracking.admision import RegistroAdmision
    from .tracking.seguimiento import Seguidor
    from .vista import Vista
    from .sources.camara import ErrorCamara, FuenteCamara
    from .sources.generador_sintetico import FuenteSintetica
except ImportError:  # como script suelto
    from vision.configuracion import (  # type: ignore[no-redef]
        CONFIG_POR_DEFECTO, ConfigVision, avisos_config, cargar_config,
    )
    from vision.detectors.cubos import detectar_cubos  # type: ignore[no-redef]
    from vision.detectors.rovers import detectar_rovers  # type: ignore[no-redef]
    from vision.geometry.coordenadas import (  # type: ignore[no-redef]
        AnclajeCancha, ErrorDuplicado, ErrorGeometria, detectar_marcadores_crudo,
        filtrar_plausibles, pose_camara, resolver_duplicados,
    )
    from vision.geometry.distorsion import (  # type: ignore[no-redef]
        ErrorCalibracion, FuenteRectificada, Rectificador, comparar_con_camara, elegir_perfil,
    )
    from vision.mundo import (  # type: ignore[no-redef]
        VERSION_PROTOCOLO, RelojRonda,
    )
    from vision.publish.puerto import ErrorPuerto  # type: ignore[no-redef]
    from vision.publish.telemetria import PublicadorTelemetria  # type: ignore[no-redef]
    from vision.record.acta import escribir_acta, mmss  # type: ignore[no-redef]
    from vision.reglas.acopio import ContadorAcopio  # type: ignore[no-redef]
    from vision.tracking.admision import RegistroAdmision  # type: ignore[no-redef]
    from vision.tracking.seguimiento import Seguidor  # type: ignore[no-redef]
    from vision.vista import Vista  # type: ignore[no-redef]
    from vision.sources.camara import ErrorCamara, FuenteCamara  # type: ignore[no-redef]
    from vision.sources.generador_sintetico import FuenteSintetica  # type: ignore[no-redef]

BASE_VISION = os.path.dirname(os.path.abspath(__file__))


def primera_altura(fuente, tiempo_max: float = 5.0) -> int:
    """Alto en píxeles del primer cuadro que entregue la fuente.

    La vista lo necesita para escalar la tipografía del panel: el mismo tamaño
    de letra se lee bien en 720p y queda diminuto en 1080p.
    """
    limite = time.monotonic() + tiempo_max
    while time.monotonic() < limite:
        cuadro = fuente.leer()
        if cuadro is not None:
            return int(cuadro.imagen.shape[0])
        time.sleep(0.01)
    return 720

#: Por qué terminó una ronda. Viaja al acta: sin motivo escrito, un cronómetro
#: en pantalla no sirve para revisar nada cuando un equipo reclama.
MOTIVO_RETO = "reto_cumplido"
MOTIVO_TIEMPO = "tiempo_agotado"
MOTIVO_OPERADOR = "detenida_por_operador"
MOTIVO_ABORTADA = "abortada_en_preparacion"

#: Transiciones que dispara UNA PERSONA desde el teclado.
#:
#: `start` no está, y su ausencia es la regla más importante de este mapa: el
#: paso de READY a RUNNING lo hace el reloj, no una tecla. Si se pudiera
#: adelantar, el tiempo de preparación igual para todos los equipos sería
#: decorativo, y con él la razón de que la visión lleve el cronómetro.
#:
#: `ready` tampoco se acepta ya desde READY. Con cuenta regresiva, volver a
#: apretarlo la reiniciaría: sería estirar la preparación apretando una tecla.
#: Para rehacerla hay que abortar a IDLE y volver a entrar, que deja rastro.
_TRANSICIONES = {
    "ready": ("READY", ("IDLE", "FINISHED")),
    "stop": ("FINISHED", ("RUNNING",)),
    "abort": ("IDLE", ("READY", "FINISHED")),
}

#: Las otras dos transiciones las dispara el reloj, en `tictac`:
#:     READY  -> RUNNING    al agotarse la preparación
#:     RUNNING -> FINISHED  al agotarse la ronda, o al cumplirse el reto
_AUTOMATICAS = ("READY -> RUNNING", "RUNNING -> FINISHED")


class Arbitro:
    """La fase de la ronda y su cronómetro oficial. La visión arbitra de verdad.

    Tiene que ser una sola voz, así que se protege con un candado: la escriben el
    hilo del teclado y el de proceso, y la lee el de proceso para armar el estado
    del mundo.

    Dos relojes, dos trabajos
    -------------------------
    El cronómetro oficial se mide con `time.monotonic()`, **nunca con el de
    pared**. Un ajuste de hora del sistema —un servidor de tiempo corrigiendo la
    máquina en mitad de una ronda— no puede alterar un tiempo de competencia. El
    `ts_ms` del mensaje sigue siendo de pared, porque el contrato lo promete así
    y los equipos miden latencia con él.

    El reloj se puede inyectar para poder verificar las transiciones sin esperar
    diez minutos reales. No es un adorno de diseño: sin esa costura, la única
    forma de probar el cierre por tiempo agotado sería dormir.

    Las transiciones inválidas se rechazan avisando, en vez de aceptarse en
    silencio: escribir `stop` sin ronda en juego es un error de quien opera, y
    merece enterarse.
    """

    def __init__(self, cfg: ConfigVision, inicial: str = "IDLE", reloj=time.monotonic):
        if inicial not in ("IDLE", "READY"):
            # Arrancar en RUNNING produciría una ronda que PARECE válida y no lo
            # es: sin preparación, sin cronómetro desde cero y sin acta de
            # arranque. Para probar sin cancha se entra en READY y se espera, o
            # se baja `ronda.preparacion_ms`, que para eso está declarado.
            raise ValueError(
                "fase inicial {!r}: solo se puede arrancar en IDLE o READY".format(inicial))
        self._cfg = cfg
        self._reloj = reloj
        self._lock = threading.Lock()
        self._fase = "IDLE"
        #: Cuándo empezó a contar la fase actual, en tiempo monótono.
        self._inicio: float | None = None
        #: Cuánto dura la fase actual. En cero, esta fase no cuenta nada.
        self._total_ms = 0
        #: El tiempo final, congelado al cerrar. Es lo que hace que el
        #: cronómetro se DETENGA a la vista en vez de seguir corriendo.
        self._final_ms: int | None = None
        self._motivo: str | None = None
        #: Si el reto se vio INCOMPLETO alguna vez durante esta ronda. Sin esto,
        #: una ronda que arranca con los tres cubos ya puestos —porque nadie los
        #: sacó de la anterior— se cerraría sola al segundo, con un tiempo de un
        #: segundo. El cierre por reto cumplido exige haber pasado de incompleto
        #: a completo DURANTE la ronda.
        self._vio_incompleto = False
        if inicial == "READY":
            self._entrar("READY")

    # -- lectura ----------------------------------------------------------

    @property
    def fase(self) -> str:
        with self._lock:
            return self._fase

    @property
    def motivo(self) -> str | None:
        """Por qué terminó la ronda, o `None` si no terminó."""
        with self._lock:
            return self._motivo

    @property
    def tiempo_final_ms(self) -> int | None:
        """El tiempo oficial de la ronda cerrada, o `None` si sigue abierta."""
        with self._lock:
            return self._final_ms

    def reloj(self) -> RelojRonda:
        """El cronómetro ahora, para que viaje dentro del estado del mundo."""
        with self._lock:
            return self._reloj_actual()

    def instantanea(self) -> tuple[str, RelojRonda]:
        """La fase y el cronómetro **del mismo instante**, bajo un solo candado.

        Pedirlos por separado dejaría que un `tictac` se cuele entre las dos
        llamadas, y entonces un mensaje diría una fase y un cronómetro de
        momentos distintos: el peor caso es publicar `RUNNING` con el reloj de
        la preparación todavía puesto. Duraría un cuadro y sería casi imposible
        de reproducir, que es exactamente el tipo de error que no hay que dejar
        que exista.
        """
        with self._lock:
            return self._fase, self._reloj_actual()

    # -- escritura --------------------------------------------------------

    def intentar(self, comando: str) -> str:
        """Aplica una transición pedida por una persona."""
        destino, desde = _TRANSICIONES[comando]
        with self._lock:
            if self._fase not in desde:
                return "'{}' no es válido desde {} (se puede desde {})".format(
                    comando, self._fase, list(desde))
            anterior = self._fase
            if destino == "FINISHED":
                self._cerrar(MOTIVO_OPERADOR)
            elif destino == "IDLE":
                motivo = MOTIVO_ABORTADA if anterior == "READY" else None
                self._entrar("IDLE")
                self._motivo = motivo
            else:
                self._entrar(destino)
            return "fase: {} -> {}".format(anterior, destino)

    def tictac(self) -> str | None:
        """Deja que el reloj haga lo suyo. Se llama una vez por cuadro.

        Devuelve el aviso de la transición si hubo una, o `None`. Vive en el
        hilo de proceso y no en un temporizador aparte porque una ronda que
        avanza sin cuadros no tendría sentido: si la cámara se cayó, lo que hace
        falta es que alguien mire la pantalla, no que el reloj siga solo.
        """
        with self._lock:
            if self._inicio is None or self._final_ms is not None:
                return None
            if self._transcurrido_ms() < self._total_ms:
                return None
            if self._fase == "READY":
                self._entrar("RUNNING")
                return "fase: READY -> RUNNING (se agotó la preparación)"
            if self._fase == "RUNNING":
                self._cerrar(MOTIVO_TIEMPO)
                return "fase: RUNNING -> FINISHED (se agotó el tiempo)"
            return None

    def observar_reto(self, completo: bool, instante: float | None) -> str | None:
        """Le informa al árbitro cómo está el reto, y él decide si cerrar.

        `instante` es el tiempo monótono de la **entrada del último cubo**, no el
        del cumplimiento de la permanencia. El contador exige un segundo
        sostenido para no titilar; tomar el tiempo oficial ahí le costaría ese
        segundo a todos los equipos por igual, que es lo mismo que decir que el
        cronómetro está mal calibrado.
        """
        with self._lock:
            if self._fase != "RUNNING" or self._final_ms is not None:
                return None
            if not completo:
                self._vio_incompleto = True
                return None
            if not self._vio_incompleto:
                # Los cubos ya estaban puestos al arrancar. No se cierra: que el
                # reto se cumpla es que alguien lo cumpla durante la ronda.
                return None
            self._cerrar(MOTIVO_RETO, instante)
            return "fase: RUNNING -> FINISHED (reto cumplido)"

    # -- interno (siempre con el candado tomado) --------------------------

    def _entrar(self, destino: str) -> None:
        duraciones = {"READY": self._cfg.ronda.preparacion_ms,
                      "RUNNING": self._cfg.ronda.duracion_ms}
        self._fase = destino
        self._total_ms = duraciones.get(destino, 0)
        self._inicio = self._reloj() if self._total_ms else None
        self._final_ms = None
        self._motivo = None
        if destino != "RUNNING":
            self._vio_incompleto = False

    def _cerrar(self, motivo: str, instante: float | None = None) -> None:
        # Se recorta al total, y no es un detalle cosmético. `tictac` se entera
        # en el cuadro SIGUIENTE al vencimiento, así que el transcurrido real de
        # una ronda agotada siempre se pasa unos milisegundos: medido en el
        # simulador, 5019 sobre 5000. Esos 19 ms son latencia del bucle, no
        # tiempo de competencia, y sin recortar rompen el invariante que el
        # contrato valida —transcurrido + restante = total—, que fue justamente
        # quien lo delató. Cerrando antes del vencimiento el recorte no hace
        # nada, que es lo que corresponde.
        transcurrido = min(self._transcurrido_ms(instante), self._total_ms)
        self._fase = "FINISHED"
        self._final_ms = transcurrido
        self._motivo = motivo

    def _transcurrido_ms(self, instante: float | None = None) -> int:
        if self._inicio is None:
            return 0
        ahora = self._reloj() if instante is None else instante
        return max(0, int(round((ahora - self._inicio) * 1000.0)))

    def _reloj_actual(self) -> RelojRonda:
        if self._final_ms is not None:
            transcurrido = self._final_ms
        elif self._inicio is None:
            return RelojRonda()
        else:
            transcurrido = min(self._transcurrido_ms(), self._total_ms)
        return RelojRonda(
            transcurrido_ms=transcurrido,
            restante_ms=max(0, self._total_ms - transcurrido),
            total_ms=self._total_ms,
        )


def abrir_fuente(cfg: ConfigVision, args):
    """Devuelve `(fuente, descripción)`. Cámara por defecto; sintético si se pide.

    La cámara real pasa además por `FuenteRectificada`, que le quita la
    distorsión del lente **antes** de que nadie la mire. Las imágenes generadas
    no la necesitan: representan el cuadro ya rectificado a propósito.
    """
    if args.sintetico:
        return FuenteSintetica(cfg), "IMÁGENES GENERADAS (sin cámara)"

    camara = FuenteCamara(cfg.camara, indice=args.indice)
    primero, limite = None, time.monotonic() + 10.0
    while primero is None and time.monotonic() < limite:
        primero = camara.leer()
        time.sleep(0.01)
    if primero is None:
        camara.cerrar()
        raise ErrorCamara("la cámara no entregó imágenes")
    alto, ancho = primero.imagen.shape[:2]

    perfil = elegir_perfil(cfg.calibracion, BASE_VISION, ancho, alto,
                           nombre=args.camara, interactivo=sys.stdin.isatty())
    print(comparar_con_camara(perfil, ancho, alto).mensaje())
    rectificador = Rectificador(perfil, alpha=cfg.calibracion.alpha, tamano=(ancho, alto))
    fuente = FuenteRectificada(camara, rectificador)
    fuente.matriz_camara = rectificador.matriz_nueva  # la que necesita la pose
    return fuente, "cámara {} ({}x{})".format(perfil.camara, ancho, alto)


def procesar(cuadro, cfg, matriz_camara, fase, reloj, seguidor, anclaje, descartados, duplicados,
             rechazos, admision, demorados):
    """De un cuadro al estado del mundo. Lanza si la geometría no se puede armar.

    Una sola pasada del detector de ArUco por cuadro: el mismo resultado sirve
    para armar las coordenadas y para encontrar los rovers.

    La detección se toma **cruda**, sin colapsar por ID, porque el diccionario
    por ID destruye el caso peligroso antes de que nadie lo mire: dos marcadores
    que dicen ser el mismo rover. `resolver_duplicados` decide cuál es el bueno
    midiéndolos contra lo que el sistema ya sabe —cuánto mide ese marcador y
    dónde estaba— y lanza si no puede decidir.

    `descartados` es un conjunto que se va llenando con los IDs vistos que no son
    ni esquina ni rover declarado, para poder informarlos. `duplicados` es una
    lista que acumula los IDs repetidos que sí se pudieron resolver: no son un
    no-evento, son fantasmas que estuvieron a punto de pisar un marcador de
    verdad, y su cuenta es la que dice si el problema se agrava.

    `rechazos` acumula los marcadores que el filtro de plausibilidad descartó
    por tamaño o por posición. Se cuentan y se informan por el mismo motivo:
    un filtro mudo que empieza a rechazar marcadores de verdad es
    indistinguible de una cámara que dejó de verlos.

    `admision` es la última defensa, y la única que no depende de ningún margen
    medido en esta escena: un ID de rover que el seguimiento **no** venía
    siguiendo tiene que sostenerse varios cuadros seguidos antes de entrar. Va
    después del tamaño y de los duplicados a propósito: los dos anteriores ya
    sacaron del camino casi todo, y lo que llega acá es lo que aquellos no
    supieron ver. `demorados` acumula `(id, cuadros)` de los que todavía
    esperan, para poder informarlos.

    Devuelve `(sistema de coordenadas, estado del mundo)`. El sistema se devuelve
    porque la vista lo necesita para dibujar celdas sobre la imagen; el estado es
    lo único que cruza hacia los consumidores.

    El estado sale del **seguidor** y no de las detecciones sueltas, porque es
    él quien tiene la memoria: si algo no se ve en este cuadro, conserva su
    última posición buena y le hace crecer la edad, en vez de que desaparezca.

    Ojo con el orden: si esta función lanza, el seguidor **no se entera** de que
    hubo un cuadro. Es lo correcto: un cuadro que no se pudo procesar no es una
    observación, y la edad de todos los objetos tiene que seguir creciendo.
    """
    crudos = detectar_marcadores_crudo(
        cuadro.imagen, cfg.marcadores_esquina.nombre_diccionario,
        cfg.deteccion_marcadores.refinamiento_esquinas)
    # Lo que se espera del marcador de un rover no es una constante: está a 80 mm
    # del tablero, así que se ve más grande Y corrido hacia afuera. Las dos cosas
    # salen de la pose deducida de la geometría GUARDADA —la de este cuadro
    # todavía no existe, y justamente uno de los candidatos en disputa podría ser
    # el que la arme—.
    pose_guardada = None
    if anclaje.sistema is not None:
        try:
            pose_guardada = pose_camara(anclaje.sistema, matriz_camara)
        except ErrorGeometria:
            pose_guardada = None
    # Primero se descarta lo que NO PUEDE SER un marcador de esta cancha, y
    # recién después se resuelven los duplicados. El orden importa: un fantasma
    # que cae por tamaño deja de disputar el ID, así que el duplicado desaparece
    # en vez de tener que resolverse. Medido en la cancha: trece disputas por
    # minuto que dejan de existir.
    crudos, descartes = filtrar_plausibles(
        crudos, cfg, anclaje.sistema, pose_rover=pose_guardada)
    rechazos.extend(descartes)

    detectados, repetidos = resolver_duplicados(
        crudos, cfg, anclaje.sistema, seguidor.ultimas_poses_rover(),
        pose_rover=pose_guardada)
    duplicados.extend(repetidos)
    # Marcadores que no son ni esquina ni rover declarado. Casi siempre son
    # detecciones falsas de la cuadrícula del tablero, pero también serían un
    # rover que alguien pegó y nadie declaró: por eso se cuentan y se informan
    # en vez de descartarse en silencio.
    descartados.update(
        set(detectados) - cfg.marcadores_esquina.ids_esperados - cfg.deteccion_rovers.ids_rover)
    # Una identidad de rover NUEVA tiene que sostenerse para existir. Se aplica
    # acá, antes del anclaje, y solo afecta a los IDs de rover: demorar un
    # marcador de esquina demoraría el sistema de coordenadas entero.
    detectados, esperando = admision.filtrar(detectados, seguidor.ultimas_poses_rover())
    demorados.extend(esperando)
    # El anclaje aguanta que falte UN marcador: conserva la homografía buena y usa
    # los tres visibles para comprobar que la cámara no se movió. Con dos o menos,
    # o si los tres la desmienten, lanza y el falla-abierto se hace cargo.
    sistema = anclaje.actualizar(cuadro.imagen, detectados)
    pose = pose_camara(sistema, matriz_camara)
    return sistema, seguidor.actualizar(
        ts_ms=cuadro.ts_ms,
        fase=fase,
        reloj=reloj,
        rovers=detectar_rovers(detectados, sistema, cfg, pose),
        cubos=detectar_cubos(cuadro.imagen, sistema, cfg, pose),
    )


def _hilo_teclado(arbitro: Arbitro, salir: threading.Event) -> None:
    """Lee comandos por consola. La visión es árbitro; esta es su boca."""
    for linea in sys.stdin:
        if salir.is_set():
            return
        comando = linea.strip().lower()
        if comando in ("quit", "salir"):
            salir.set()
            return
        if comando in _TRANSICIONES:
            print("[fase] " + arbitro.intentar(comando), flush=True)
        elif comando == "start":
            print("[fase] 'start' ya no existe: de READY a RUNNING pasa el reloj, no "
                  "una tecla. Adelantarlo le daría a un equipo menos preparación que "
                  "al resto.", flush=True)
        elif comando:
            print("[fase] comandos: ready | stop | abort | quit", flush=True)
    salir.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sistema de visión del Vision-Rover-Challenge.")
    parser.add_argument("--config", default=CONFIG_POR_DEFECTO)
    parser.add_argument("--sintetico", action="store_true",
                        help="correr SIN cámara, con imágenes generadas (hay que pedirlo)")
    parser.add_argument("--indice", type=int, default=None, help="índice de cámara")
    parser.add_argument("--camara", default=None, help="nombre del perfil de calibración")
    parser.add_argument("--fase", choices=("IDLE", "READY"), default="IDLE",
                        help="fase inicial; RUNNING no se acepta, porque saltear la "
                             "preparación produce una ronda que parece válida y no lo es")
    parser.add_argument("--duracion", type=float, default=0.0,
                        help="segundos a correr; 0 = hasta 'quit' o Ctrl-C")
    parser.add_argument("--ventana", action="store_true",
                        help="abrir la vista en vivo: la imagen con lo detectado encima")
    parser.add_argument("--ventana-hz", type=float, default=12.0,
                        help="cuántas veces por segundo refrescar la vista")
    args = parser.parse_args(argv)

    cfg = cargar_config(args.config)
    try:
        fuente, descripcion = abrir_fuente(cfg, args)
    except (ErrorCamara, ErrorCalibracion) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2

    matriz = getattr(fuente, "matriz_camara", None)
    if matriz is None:  # fuente sintética: la matriz es la de su propia cámara
        matriz = fuente.verdad.camara.matriz

    arbitro = Arbitro(cfg, args.fase)
    seguidor = Seguidor(cfg)
    contador = ContadorAcopio(cfg)
    anclaje = AnclajeCancha(cfg)
    admision = RegistroAdmision(cfg)
    descartados: set[int] = set()
    duplicados: list = []
    rechazos: list = []
    demorados: list = []
    duplicados_totales = ambiguos = rechazos_totales = 0
    vista = None
    if args.ventana:
        # La vista es un CONSUMIDOR: solo lee. Si se apaga, el sistema sigue
        # igual, y por eso puede refrescarse a su propio ritmo sin frenar nada.
        vista = Vista(cfg, alto_imagen=primera_altura(fuente), hz=args.ventana_hz)
    publicador = PublicadorTelemetria(cfg, avisar=lambda t: print(t, flush=True))
    salir = threading.Event()

    print("=" * 70)
    print("SISTEMA DE VISIÓN — Vision-Rover-Challenge · protocolo v{}".format(VERSION_PROTOCOLO))
    print("Entrada: {}".format(descripcion))
    if args.sintetico:
        print("")
        print("  ##################################################################")
        print("  ##  DATOS SINTÉTICOS: ESTO NO ES LA CANCHA REAL                 ##")
        print("  ##  Las posiciones son inventadas. No usar para una ronda.      ##")
        print("  ##################################################################")
    print("Cancha: {}x{} celdas de {:.0f} mm".format(
        cfg.tablero.cols, cfg.tablero.rows, cfg.tablero.cell_mm))
    print("Comandos: ready | stop | abort | quit   (de READY a RUNNING pasa solo)")
    for aviso in avisos_config(cfg):
        # No impiden arrancar —para eso está `revisar_config`— pero tienen que
        # verse. El detalle completo, con `python -m vision.tools.verificar_config`.
        print("[aviso] {}".format(aviso))
    print("=" * 70)

    try:
        publicador.arrancar()
    except ErrorPuerto as exc:
        # Sin puerto no hay telemetría, y sin telemetría el sistema no sirve
        # para nada: no tiene sentido seguir procesando cuadros para nadie.
        print("ERROR: {}".format(exc), file=sys.stderr)
        if vista is not None:
            vista.cerrar()
        fuente.cerrar()
        return 3
    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=_hilo_teclado, args=(arbitro, salir),
                         name="teclado", daemon=True).start()

    cuadros = fallos = 0
    ultimo_estado = None
    acopio = None
    ultimo_error = ""
    #: Para detectar los cambios de fase desde el bucle. Se mira acá y no en el
    #: árbitro porque las transiciones llegan de tres lados —el reloj, el
    #: teclado y la ventana— y el acta tiene que escribirse una sola vez,
    #: cualquiera haya sido el que la disparó.
    fase_previa = arbitro.fase
    #: Los cubos que ya estaban en su zona al empezar a jugar. Va al acta.
    arranque: tuple[str, ...] = ()
    proximo_informe = time.monotonic() + 5.0
    fin = time.monotonic() + args.duracion if args.duracion > 0 else float("inf")

    try:
        while not salir.is_set() and time.monotonic() < fin:
            cuadro = fuente.leer()
            if cuadro is None:
                time.sleep(0.005)
                continue
            cuadros += 1
            # El reloj de la ronda avanza con los cuadros y no en un temporizador
            # aparte: una ronda que sigue corriendo sin que la cámara vea nada no
            # es una ronda, es un cronómetro solo.
            aviso_fase = arbitro.tictac()
            if aviso_fase:
                print("[fase] " + aviso_fase, flush=True)
            sistema_actual = None
            # ---- falla abierto -------------------------------------------
            # Si un cuadro no se puede procesar, NO se toca la casilla y se
            # sigue. La publicación continúa emitiendo el último estado bueno,
            # que envejece a la vista de todos. El sistema no se calla nunca.
            try:
                fase_ahora, reloj_ahora = arbitro.instantanea()
                sistema_actual, estado = procesar(
                    cuadro, cfg, matriz, fase_ahora, reloj_ahora, seguidor, anclaje,
                    descartados, duplicados, rechazos, admision, demorados)
                publicador.actualizar(estado)
                ultimo_estado = estado
                # El conteo va DESPUÉS de publicar y en su propio try: es para
                # la pantalla, no para el contrato, así que un error suyo no
                # puede frenar la telemetría ni tumbar la ronda. Si falla, se
                # conserva la última cuenta buena, igual que todo lo demás.
                try:
                    acopio = contador.actualizar(estado, estado.ts_ms)
                    # El contador informa; el árbitro decide. Se le pasa el
                    # instante de ENTRADA del último cubo, que es con el que
                    # fecha el cierre: la permanencia se cumple un segundo más
                    # tarde y cobrárselo a todos sería descalibrar el reloj.
                    aviso_reto = arbitro.observar_reto(
                        acopio.completo, acopio.instante_completo)
                    if aviso_reto:
                        print("[fase] " + aviso_reto, flush=True)
                except Exception as exc:  # noqa: BLE001 — a propósito
                    ultimo_error = "acopio: {}: {}".format(type(exc).__name__, exc)
            except ErrorDuplicado as exc:
                # Un duplicado que NO se pudo resolver. Se descarta el cuadro y
                # el falla-abierto conserva el último estado bueno: entre dos
                # candidatos igual de plausibles, elegir sería adivinar, y una
                # posición inventada vale menos que un dato viejo marcado.
                ambiguos += 1
                fallos += 1
                ultimo_error = str(exc).split(".")[0]
            except ErrorGeometria as exc:
                fallos += 1
                ultimo_error = str(exc).split(".")[0]
            except Exception as exc:  # noqa: BLE001 — a propósito: nada tumba la ronda
                fallos += 1
                ultimo_error = "{}: {}".format(type(exc).__name__, exc)

            # ---- el acta -------------------------------------------------
            # Va acá, fuera del try del cuadro, para que se escriba aunque el
            # cuadro que cerró la ronda haya fallado: la ronda terminó igual.
            if arbitro.fase != fase_previa:
                anterior, fase_previa = fase_previa, arbitro.fase
                if fase_previa == "RUNNING":
                    # Qué había en las zonas al empezar. Si ya había cubos
                    # adentro, la ronda arranca con parte del reto hecho: no se
                    # invalida acá, se registra y se avisa fuerte.
                    arranque = tuple(
                        z.color for z in acopio.zonas if z.adentro) if acopio else ()
                    if arranque:
                        print("[AVISO] la ronda arrancó con {} ya dentro de su zona. El "
                              "cierre por reto cumplido exige pasar de incompleto a "
                              "completo durante la ronda, así que no se va a disparar "
                              "solo por esto, y el acta lo deja registrado.".format(
                                  ", ".join(arranque)), flush=True)
                elif fase_previa == "FINISHED" or (anterior == "READY"
                                                   and fase_previa == "IDLE"):
                    # Un consumidor que falla no puede tumbar nada: se avisa y
                    # se sigue. Un disco lleno no arruina una competencia.
                    try:
                        ruta = escribir_acta(
                            cfg,
                            motivo=arbitro.motivo or "desconocido",
                            tiempo_final_ms=arbitro.tiempo_final_ms,
                            acopio=acopio, estado=ultimo_estado, arranque=arranque)
                        print("[acta] ronda cerrada por {} · tiempo {} · acta en {}".format(
                            arbitro.motivo, mmss(arbitro.tiempo_final_ms), ruta), flush=True)
                    except Exception as exc:  # noqa: BLE001 — a propósito
                        print("[acta] NO SE PUDO ESCRIBIR EL ACTA: {}: {}. La ronda "
                              "terminó igual, pero no queda constancia.".format(
                                  type(exc).__name__, exc), flush=True)
                    arranque = ()

            # ---- la vista ------------------------------------------------
            if vista is not None and vista.toca_dibujar(time.monotonic()):
                # La fase y el reloj, del MISMO instante: en dos llamadas
                # sueltas podrían caer a los lados de una transición y el panel
                # mostraría una fase con el cronómetro de otra.
                fase_panel, reloj_panel = arbitro.instantanea()
                vista.dibujar(cuadro.imagen, sistema_actual, ultimo_estado, {
                    "fase": fase_panel, "reloj": reloj_panel,
                    "motivo": arbitro.motivo, "sintetico": args.sintetico,
                    "clientes": publicador.clientes, "emitidos": publicador.emitidos,
                    "acopio": acopio,
                    "fps": fuente.fps_real, "fallos": fallos,
                    "esquinas_visibles": anclaje.esquinas_visibles,
                    "desvio_mm": anclaje.desvio_mm,
                })
                comando = vista.tecla()
                if comando == "quit":
                    salir.set()
                elif comando:
                    print("[fase] " + arbitro.intentar(comando), flush=True)

            if time.monotonic() >= proximo_informe:
                proximo_informe += 5.0
                edad = publicador.edad_del_estado_ms()
                print("[estado] fase={} cuadros={} fallos={} emitidos={} clientes={} "
                      "pisados={} fps={:.1f} edad={} conservados={}/{} acopio={} "
                      "duplicados={} rechazados={}".format(
                          arbitro.fase, cuadros, fallos, publicador.emitidos,
                          publicador.clientes, publicador.pisados, fuente.fps_real,
                          "{} ms".format(edad) if edad is not None else "sin estado",
                          seguidor.conservados_rover, seguidor.conservados_cubo,
                          "{}/{}".format(acopio.en_posicion, acopio.total)
                          if acopio is not None else "sin datos",
                          duplicados_totales + len(duplicados),
                          rechazos_totales + len(rechazos)),
                      flush=True)
                if rechazos:
                    rechazos_totales += len(rechazos)
                    por_motivo: dict[str, int] = {}
                    for r in rechazos:
                        por_motivo[r.motivo] = por_motivo.get(r.motivo, 0) + 1
                    ultimo = rechazos[-1]
                    print("[aviso] marcadores rechazados por no ser plausibles: {}. No pueden "
                          "ser marcadores de esta cancha: el detector los inventa sobre la "
                          "cuadrícula del tablero. Ejemplo: ID {} rechazado por {}, midió "
                          "{:.1f} mm donde se esperaban {:.1f}, en la celda ({:.1f}, {:.1f})".format(
                              ", ".join("{} por {}".format(n, m) for m, n in sorted(
                                  por_motivo.items())),
                              ultimo.id, ultimo.motivo, ultimo.lado_mm, ultimo.esperado_mm,
                              ultimo.col, ultimo.row), flush=True)
                    rechazos.clear()
                if duplicados or ambiguos:
                    duplicados_totales += len(duplicados)
                    porid: dict[int, int] = {}
                    for d in duplicados:
                        porid[d.id] = porid.get(d.id, 0) + 1
                    print("[aviso] IDs que aparecieron DUPLICADOS en un mismo cuadro: {}. "
                          "Un fantasma con el ID de un marcador de verdad lo pisaría en "
                          "silencio; se resolvieron {} midiendo los candidatos y {} "
                          "cuadros se descartaron por no poder decidir. Ejemplo: {}".format(
                              sorted(porid) or "—", len(duplicados), ambiguos,
                              "{} con lados de {} mm, ganó {:.1f}".format(
                                  duplicados[-1].id,
                                  ", ".join("{:.1f}".format(x) for x in duplicados[-1].lados_mm),
                                  duplicados[-1].ganador_mm)
                              if duplicados else "—"), flush=True)
                    duplicados.clear()
                    ambiguos = 0
                if demorados:
                    por_id: dict[int, int] = {}
                    for id_demorado, racha in demorados:
                        por_id[id_demorado] = max(por_id.get(id_demorado, 0), racha)
                    esperando = admision.esperando
                    print("[aviso] identidades de rover demoradas hasta sostenerse {} cuadros: "
                          "{}. Es lo normal al poner un robot en la cancha —se paga una vez, "
                          "unos {:.0f} ms— y es lo que impide que un fantasma invente un rover "
                          "que no existe. {}".format(
                              cfg.deteccion_marcadores.cuadros_para_admitir_rover,
                              ", ".join("ID {} llegó a {} cuadro(s)".format(i, n)
                                        for i, n in sorted(por_id.items())),
                              1000.0 * cfg.deteccion_marcadores.cuadros_para_admitir_rover
                              / max(fuente.fps_real, 1.0),
                              ("SIGUEN esperando ahora mismo: {} — si hay un robot de verdad "
                               "ahí, no se está viendo estable".format(sorted(esperando))
                               if esperando else "Ninguna quedó esperando.")), flush=True)
                    demorados.clear()
                if descartados:
                    print("[aviso] marcadores vistos que NO son ni esquina ni rover "
                          "declarado, y por eso se descartan: {}. Si alguno es un robot "
                          "de verdad, hay que agregarlo a deteccion_rovers.ids_rover; si "
                          "no, son detecciones falsas de la cuadrícula.".format(
                              sorted(descartados)), flush=True)
                    descartados.clear()
                if anclaje.conservando:
                    print("[aviso] falta un marcador de esquina: se ven {}, y se viene "
                          "conservando la geometría hace {} cuadros (desvío {:.2f} mm). "
                          "Las coordenadas siguen siendo válidas.".format(
                              anclaje.esquinas_visibles, anclaje.cuadros_conservados,
                              anclaje.desvio_mm), flush=True)
                if ultimo_error:
                    print("[aviso] último problema: {}".format(ultimo_error), flush=True)
                    ultimo_error = ""
    except KeyboardInterrupt:
        pass
    finally:
        if vista is not None:
            vista.cerrar()
        publicador.detener()
        fuente.cerrar()
        print("\nSistema detenido. Cuadros={} fallos={} mensajes publicados={}".format(
            cuadros, fallos, publicador.emitidos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
