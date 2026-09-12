"""Mide los falsos positivos del detector de ArUco sobre la cancha real.

Cómo se corre:

    python -m vision.tools.diagnostico_falsos_positivos
    python -m vision.tools.diagnostico_falsos_positivos --minutos 5
    python -m vision.tools.diagnostico_falsos_positivos --indice 1

⚠️ **La cancha tiene que estar VACÍA**, con los cuatro marcadores de esquina y
nada más: sin rovers, sin cubos, sin manos. Todo marcador que aparezca que no
sea una esquina es, por definición, un falso positivo.

Primero medir, después corregir
-------------------------------
El detector de ArUco encuentra marcadores donde no los hay. Es esperable: el
tablero es una cuadrícula fina de blanco y negro, que es exactamente la clase de
textura con la que se construye un código ArUco, y `DICT_4X4_50` tiene poca
distancia entre códigos. Con la corrección de errores que trae OpenCV por
defecto, un recorte cualquiera de la cuadrícula puede terminar pareciéndose lo
suficiente a un código válido.

Esta herramienta **no corrige nada**. Mide, para que las correcciones se elijan
con números en vez de con intuición:

- **qué IDs** aparecen, y si alguno cae en los IDs declarados de rover, que es
  el caso grave: un fantasma con el ID de un rover pisa a un rover de verdad;
- **de qué tamaño** son, medidos en milímetros sobre el plano del tablero con la
  homografía. Un marcador real de esquina mide 100 mm y el del rover 40; un
  fantasma recortado de la cuadrícula casi nunca cae cerca de esos números;
- **cuán cuadrados** son. En el espacio de celdas un marcador real vuelve a ser
  un cuadrado —la homografía deshace la perspectiva— así que sus cuatro lados y
  sus dos diagonales tienen que coincidir entre sí. Un fantasma casi nunca lo
  hace;
- **cuánto duran**. Un falso positivo suele vivir uno o dos cuadros y saltar a
  otro lado; un marcador de verdad está ahí cuadro tras cuadro.

Los cuatro marcadores de esquina se miden también, y con la misma vara: son el
**control** de la medición. Sin saber cuánto se desvía un marcador legítimo no
hay forma de elegir una tolerancia para rechazar los falsos.

El paralaje infla al marcador del rover
---------------------------------------
El marcador del rover está a 90 mm sobre el tablero, así que se ve más grande de
lo que es: `H/(H−h)`, un 4,5 % con la cámara a 2,1 m. La herramienta calcula ese
factor con la pose de cámara —deducida de los cuatro marcadores, sin declarar
nada— y lo informa, para que quien fije la tolerancia sepa de cuánto es el
corrimiento que tiene que contemplar.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections import defaultdict

import numpy as np

try:  # como paquete
    from ..configuracion import cargar_config
    from ..geometry.coordenadas import (
        AnclajeCancha, ErrorGeometria, centro_de, detectar_marcadores, pose_camara,
    )
    from ..sistema import abrir_fuente
except ImportError:  # como script suelto
    from vision.configuracion import cargar_config  # type: ignore[no-redef]
    from vision.geometry.coordenadas import (  # type: ignore[no-redef]
        AnclajeCancha, ErrorGeometria, centro_de, detectar_marcadores, pose_camara,
    )
    from vision.sistema import abrir_fuente  # type: ignore[no-redef]


# --------------------------------------------------------------------------
# La medición de un marcador
# --------------------------------------------------------------------------


def medir(esquinas_px: np.ndarray, sistema) -> dict:
    """Mide un marcador detectado **sobre el plano del tablero**, no en píxeles.

    Los píxeles no sirven para juzgar tamaños: un marcador en un borde de la
    imagen se ve más chico que el mismo marcador en el centro, y con la cámara
    inclinada la diferencia crece. La homografía deshace exactamente eso, así
    que en celdas un cuadrado vuelve a ser un cuadrado del tamaño que es.

    Devuelve el lado medio en milímetros, el error de cuadratura en por ciento y
    el centro en celdas.
    """
    celdas = sistema.a_celdas(np.asarray(esquinas_px, dtype=np.float64).reshape(4, 2))
    cell_mm = sistema.cell_mm

    lados = [
        float(np.linalg.norm(celdas[(i + 1) % 4] - celdas[i])) * cell_mm for i in range(4)
    ]
    diagonales = [
        float(np.linalg.norm(celdas[2] - celdas[0])) * cell_mm,
        float(np.linalg.norm(celdas[3] - celdas[1])) * cell_mm,
    ]
    lado_medio = sum(lados) / 4.0
    diagonal_media = sum(diagonales) / 2.0

    # Tres formas de no ser un cuadrado, y se toma la peor:
    #   1. los cuatro lados no miden lo mismo (es un rectángulo o un rombo);
    #   2. las dos diagonales no miden lo mismo (está torcido);
    #   3. la diagonal no es el lado por raíz de dos (no tiene ángulos rectos).
    # Las tres son relativas al tamaño, para que un fantasma chico y uno grande
    # se puedan comparar con el mismo número.
    disp_lados = (max(lados) - min(lados)) / lado_medio * 100.0 if lado_medio else float("inf")
    disp_diag = (abs(diagonales[0] - diagonales[1]) / diagonal_media * 100.0
                 if diagonal_media else float("inf"))
    relacion = (abs(diagonal_media / (lado_medio * math.sqrt(2.0)) - 1.0) * 100.0
                if lado_medio else float("inf"))

    col, row = centro_de(celdas)
    return {
        "lado_mm": lado_medio,
        "lados_mm": lados,
        "cuadratura_pct": max(disp_lados, disp_diag, relacion),
        "disp_lados_pct": disp_lados,
        "disp_diagonales_pct": disp_diag,
        "relacion_diagonal_pct": relacion,
        "col": col,
        "row": row,
    }


# --------------------------------------------------------------------------
# Acumulación
# --------------------------------------------------------------------------


class Registro:
    """Lo que se vio de un ID a lo largo de la corrida.

    La **racha** es lo que separa un fantasma de un marcador: se cuenta cuántos
    cuadros CONSECUTIVOS apareció el mismo ID, y se guarda la más larga. Un
    marcador pegado al tablero tiene una racha tan larga como la corrida; un
    recorte afortunado de la cuadrícula dura uno o dos cuadros y desaparece.
    """

    def __init__(self, id_aruco: int):
        self.id = id_aruco
        self.apariciones = 0
        self.eventos = 0            # rachas distintas: cuántas VECES apareció
        self.racha = 0
        self.mejor_racha = 0
        self._ultimo_cuadro = -10
        self.lados_mm: list[float] = []
        self.cuadratura: list[float] = []
        self.celdas: list[tuple[float, float]] = []

    def registrar(self, cuadro: int, medida: dict) -> None:
        if cuadro == self._ultimo_cuadro + 1:
            self.racha += 1
        else:
            self.racha = 1
            self.eventos += 1
        self._ultimo_cuadro = cuadro
        self.mejor_racha = max(self.mejor_racha, self.racha)
        self.apariciones += 1
        self.lados_mm.append(medida["lado_mm"])
        self.cuadratura.append(medida["cuadratura_pct"])
        self.celdas.append((medida["col"], medida["row"]))


def _resumen(valores: list[float]) -> str:
    if not valores:
        return "—"
    v = np.array(valores, dtype=np.float64)
    return "{:.1f} / {:.1f} / {:.1f}".format(v.min(), float(np.median(v)), v.max())


# --------------------------------------------------------------------------
# Programa
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mide los falsos positivos del detector de ArUco sobre la cancha real."
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--minutos", type=float, default=2.0, help="cuánto medir")
    parser.add_argument("--indice", type=int, default=None, help="índice de cámara")
    parser.add_argument("--camara", default=None, help="nombre del perfil de calibración")
    parser.add_argument("--sintetico", action="store_true",
                        help="correr sobre imágenes generadas (para probar la herramienta)")
    args = parser.parse_args(argv)

    cfg = cargar_config(args.config) if args.config else cargar_config()

    print("=" * 78)
    print("DIAGNÓSTICO DE FALSOS POSITIVOS DEL DETECTOR DE ArUco")
    print("=" * 78)
    print("  La cancha tiene que estar VACÍA: los cuatro marcadores de esquina y nada")
    print("  más. Todo lo que aparezca que no sea una esquina es un falso positivo.")
    print("  Diccionario: {}  ·  midiendo {:.0f} s".format(
        cfg.marcadores_esquina.nombre_diccionario, args.minutos * 60.0))

    fuente, descripcion = abrir_fuente(cfg, args)
    matriz = getattr(fuente, "matriz_camara", None)
    if matriz is None:  # fuente sintética
        matriz = fuente.verdad.camara.matriz
    print("  Entrada: {}".format(descripcion))
    print("=" * 78)

    esquinas_esperadas = cfg.marcadores_esquina.ids_esperados
    ids_rover = cfg.deteccion_rovers.ids_rover
    anclaje = AnclajeCancha(cfg)

    falsos: dict[int, Registro] = {}
    control: dict[int, Registro] = {}
    cuadros = sin_geometria = 0
    factores = []

    inicio = time.monotonic()
    fin = inicio + args.minutos * 60.0
    proximo_aviso = inicio + 15.0

    try:
        while time.monotonic() < fin:
            cuadro = fuente.leer()
            if cuadro is None:
                time.sleep(0.005)
                continue
            cuadros += 1

            detectados = detectar_marcadores(
                cuadro.imagen, cfg.marcadores_esquina.nombre_diccionario)
            try:
                sistema = anclaje.actualizar(cuadro.imagen, detectados)
            except ErrorGeometria:
                # Sin homografía no hay plano del tablero sobre el cual medir, así
                # que el cuadro no aporta. Se cuenta para poder informarlo: si
                # fueran muchos, la medición entera valdría menos.
                sin_geometria += 1
                continue

            if anclaje.esquinas_visibles == 4:
                try:
                    pose = pose_camara(sistema, matriz)
                    factores.append(pose.factor_paralaje(
                        cfg.paralaje.altura_marcador_rover_mm))
                except ErrorGeometria:
                    pass

            for id_aruco, esquinas in detectados.items():
                medida = medir(esquinas, sistema)
                destino = control if id_aruco in esquinas_esperadas else falsos
                destino.setdefault(id_aruco, Registro(id_aruco)).registrar(cuadros, medida)

            if time.monotonic() >= proximo_aviso:
                proximo_aviso += 15.0
                print("  [{:>4.0f} s] cuadros={} · falsos positivos={} en {} IDs distintos".format(
                    time.monotonic() - inicio, cuadros,
                    sum(r.apariciones for r in falsos.values()), len(falsos)), flush=True)
    except KeyboardInterrupt:
        print("\n  (interrumpido: se informa lo medido hasta acá)")
    finally:
        fuente.cerrar()

    duracion = time.monotonic() - inicio
    informe(cfg, duracion, cuadros, sin_geometria, control, falsos, ids_rover, factores)
    return 0


def informe(cfg, duracion, cuadros, sin_geometria, control, falsos, ids_rover, factores) -> None:
    minutos = duracion / 60.0 if duracion > 0 else 1.0
    apariciones = sum(r.apariciones for r in falsos.values())
    eventos = sum(r.eventos for r in falsos.values())

    print("\n" + "=" * 78)
    print("LO QUE SE MIDIÓ")
    print("=" * 78)
    print("  {:.0f} s · {} cuadros procesados · {:.1f} por segundo".format(
        duracion, cuadros, cuadros / duracion if duracion else 0.0))
    if sin_geometria:
        print("  {} cuadros sin geometría (no se pudo medir nada en ellos)".format(sin_geometria))

    print("\n  CONTROL — los cuatro marcadores de esquina, medidos con la misma vara")
    print("  Es la referencia: así de bien se porta un marcador de VERDAD.")
    print("  {:>4} {:>12} {:>10} {:>26} {:>22}".format(
        "ID", "apariciones", "% cuadros", "lado mm (mín/med/máx)", "cuadratura % (m/m/M)"))
    print("  " + "-" * 78)
    for id_aruco in sorted(control):
        r = control[id_aruco]
        print("  {:>4} {:>12} {:>9.1f}% {:>26} {:>22}".format(
            r.id, r.apariciones, 100.0 * r.apariciones / cuadros if cuadros else 0.0,
            _resumen(r.lados_mm), _resumen(r.cuadratura)))
    print("  esperado: {:.0f} mm de lado (marcadores_esquina.lado_mm)".format(
        cfg.marcadores_esquina.lado_mm))
    if factores:
        f = float(np.median(factores))
        print("  el marcador del rover, a {:.0f} mm de altura, se ve {:.1f} % más grande:".format(
            cfg.paralaje.altura_marcador_rover_mm, (f - 1.0) * 100.0))
        print("  {:.0f} mm reales se medirían como {:.1f} mm sobre el plano del tablero".format(
            cfg.elementos.marcador_rover.lado_mm, cfg.elementos.marcador_rover.lado_mm * f))

    print("\n" + "=" * 78)
    print("FALSOS POSITIVOS")
    print("=" * 78)
    if not falsos:
        print("  Ninguno en {:.0f} s. El detector no inventó un solo marcador.".format(duracion))
        return

    print("  {} detecciones falsas en {:.1f} min  ->  {:.1f} por minuto".format(
        apariciones, minutos, apariciones / minutos))
    print("  {} apariciones distintas (rachas)   ->  {:.1f} por minuto".format(
        eventos, eventos / minutos))
    print("  {} IDs distintos: {}".format(len(falsos), sorted(falsos)))

    chocan = sorted(set(falsos) & set(ids_rover))
    if chocan:
        print("\n  ⚠️  GRAVE: los IDs {} son IDs DECLARADOS DE ROVER. Un fantasma con ese".format(
            chocan))
        print("      ID no se descarta: pisa la posición de un rover de verdad, en silencio.")

    print("\n  {:>4} {:>7} {:>8} {:>7} {:>24} {:>20} {:>16}".format(
        "ID", "aparic", "rachas", "racha máx", "lado mm (mín/med/máx)",
        "cuadratura % (m/m/M)", "celda típica"))
    print("  " + "-" * 92)
    for id_aruco in sorted(falsos, key=lambda i: -falsos[i].apariciones):
        r = falsos[id_aruco]
        celdas = np.array(r.celdas, dtype=np.float64)
        print("  {:>4} {:>7} {:>8} {:>9} {:>24} {:>20} {:>16}".format(
            r.id, r.apariciones, r.eventos, r.mejor_racha,
            _resumen(r.lados_mm), _resumen(r.cuadratura),
            "({:.1f}, {:.1f})".format(float(np.median(celdas[:, 0])),
                                      float(np.median(celdas[:, 1])))))

    todos_lados = [v for r in falsos.values() for v in r.lados_mm]
    todas_cuad = [v for r in falsos.values() for v in r.cuadratura]
    rachas = [r.mejor_racha for r in falsos.values()]
    lados = np.array(todos_lados, dtype=np.float64)

    print("\n  DISTRIBUCIÓN DE TAMAÑOS de los falsos positivos")
    print("  mín {:.1f} · p25 {:.1f} · mediana {:.1f} · p75 {:.1f} · máx {:.1f} mm".format(
        lados.min(), float(np.percentile(lados, 25)), float(np.median(lados)),
        float(np.percentile(lados, 75)), lados.max()))
    esperados = (
        ("esquina", cfg.marcadores_esquina.lado_mm),
        ("rover", cfg.elementos.marcador_rover.lado_mm),
    )
    for nombre, lado in esperados:
        cerca = int(np.sum(np.abs(lados - lado) <= 0.20 * lado))
        print("  a menos de 20 % del lado de un marcador de {} ({:.0f} mm): {} de {}".format(
            nombre, lado, cerca, len(lados)))

    print("\n  CUADRATURA de los falsos positivos: mín/mediana/máx = {} %".format(
        _resumen(todas_cuad)))
    print("  PERSISTENCIA: racha más larga por ID: mín {} · mediana {:.0f} · máx {} cuadros".format(
        min(rachas), float(np.median(rachas)), max(rachas)))
    print("\n" + "=" * 78)
    print("Esta herramienta NO corrige nada: los números de arriba son para decidir")
    print("con qué criterio rechazar, y con qué tolerancia, sin adivinar umbrales.")
    print("=" * 78)


if __name__ == "__main__":
    sys.exit(main())
