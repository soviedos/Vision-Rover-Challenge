"""Cuántos cubos están en posición. La regla de entrega del reto.

Qué hace y qué NO hace
----------------------
Toma el **estado del mundo** —dónde está cada cubo— y le aplica la regla del
reglamento: un cubo está entregado cuando queda **completamente dentro** de la
zona de acopio de su color. Devuelve la cuenta y el detalle por color.

**No dibuja**: eso es de `vista.py`. **No publica**: el conteo no viaja en el
mensaje. **No cambia la fase**: cuando están los tres, la pantalla lo anuncia y
la ronda la sigue cerrando una persona con `stop`. La visión informa; el juez
decide.

El veredicto no se calcula acá
------------------------------
Sale de `contrato/schema.py`, igual que el que calcula el equipo en su rover. Si
esta pieza escribiera su propia versión de la cuenta, un cubo podría estar
"adentro" en nuestra pantalla y "afuera" en el código del equipo, y no habría
forma de decidir quién tiene razón. Acá solo vive la **memoria entre cuadros**,
que es lo que el contrato no puede tener porque no ve la secuencia.

Por qué hay una permanencia mínima
----------------------------------
El conteo es **en vivo**: cuenta los que están adentro **ahora**, y si un rover
saca un cubo, la cuenta baja. Pero un cubo dejado **justo en el borde del
criterio** entra y sale del veredicto con el puro jitter de la detección, y sin
permanencia el número saltaría entre 2 y 3 varias veces por segundo, que en
pantalla se lee como un sistema roto.

No es hipotético: con el fondo de zona de 100 mm que tuvo la primera versión de
la v2, la ventana medía 15,2 mm sobre ese eje y en la cancha real un cubo bien
puesto oscilaba entre 5 y 10 mm afuera del límite, cuadro a cuadro.

La permanencia solo demora **entrar**, nunca **salir**. Demorar la salida sería
peor que el titileo: diría que un cubo está entregado cuando un rover ya se lo
llevó.

Un cubo tapado sigue contando
-----------------------------
Y es deliberado. El seguimiento conserva la última posición buena de un objeto
ocluido —es la promesa del contrato—, así que un cubo que ya estaba adentro y
queda tapado por el rover que acaba de entregarlo **sigue contado**. Lo
contrario sería que el contador se cayera justo en el momento de la entrega, que
es exactamente cuando hay un rover encima.

Como el veredicto se sostiene sobre una posición conservada y no sobre una
observación fresca, el detalle expone la **edad** del cubo, y la vista la
muestra cuando pasa a ser vieja. Quien mira la pantalla tiene que poder saber
sobre qué se apoya lo que está viendo.
"""

from __future__ import annotations

from dataclasses import dataclass

try:  # como paquete
    from ..configuracion import ConfigVision, geometrias_deposito
    from ..mundo import EstadoMundo
except ImportError:  # como script suelto
    from vision.configuracion import ConfigVision, geometrias_deposito  # type: ignore[no-redef]
    from vision.mundo import EstadoMundo  # type: ignore[no-redef]

# Importar `configuracion` deja `contrato/` en el camino de búsqueda, así que
# esto va después y no antes.
from contrato import schema  # noqa: E402


@dataclass(frozen=True, slots=True)
class EstadoZona:
    """Cómo está una zona de acopio en este instante.

    `adentro` es el veredicto **instantáneo** y `contado` es ese veredicto ya
    sostenido durante la permanencia mínima. Se exponen los dos porque son
    preguntas distintas: el primero dice si el cubo está bien puesto, el segundo
    si el sistema ya lo da por entregado. En el borde del criterio pueden
    discrepar por un rato, y esconderlo haría parecer que la pantalla no
    reacciona.

    `falta_celdas` es cuánto hay que mover el cubo para que entre; vale `inf`
    cuando no hay ningún cubo de ese color en el estado del mundo.
    """

    color: str
    presente: bool
    adentro: bool
    contado: bool
    falta_celdas: float
    adentro_hace_ms: int
    edad_cubo_ms: int


@dataclass(frozen=True, slots=True)
class ResultadoAcopio:
    """La cuenta y el detalle, en un instante. Inmutable, como el estado."""

    zonas: tuple[EstadoZona, ...]

    @property
    def en_posicion(self) -> int:
        return sum(1 for z in self.zonas if z.contado)

    @property
    def total(self) -> int:
        return len(self.zonas)

    @property
    def completo(self) -> bool:
        """Los tres cubos en su zona. Anuncia el reto cumplido; no lo cierra."""
        return self.total > 0 and self.en_posicion == self.total


class ContadorAcopio:
    """Lleva la memoria de cuánto hace que cada cubo está dentro de su zona.

    Es la única pieza con memoria de este paquete, al estilo de
    `tracking/seguimiento.py`, y por el mismo motivo: la regla necesita saber
    qué pasó antes y un estado del mundo solo cuenta el ahora.

    No es seguro para usar desde varios hilos, y no hace falta que lo sea: vive
    en el hilo de proceso, que es el único que lo toca.
    """

    def __init__(self, cfg: ConfigVision):
        self._cfg = cfg
        # Las geometrías se arman UNA vez: son lugares declarados que no cambian
        # entre cuadros, y rehacerlas veinte veces por segundo sería trabajo
        # perdido. Si la configuración fuera incoherente, esto lanza acá, al
        # construir, y no en medio de la ronda.
        self._geometrias = geometrias_deposito(cfg)
        self._permanencia_ms = cfg.conteo_acopio.permanencia_minima_ms
        #: Desde cuándo cada color está adentro sin interrupción, en tiempo de
        #: captura. Se borra la entrada apenas sale: la permanencia se vuelve a
        #: contar desde cero, porque lo que se quiere medir es que se quede.
        self._desde_ms: dict[str, int] = {}

    @property
    def geometrias(self) -> dict[str, schema.GeometriaDepot]:
        """Las zonas, para que la vista las dibuje sin recalcularlas."""
        return self._geometrias

    def actualizar(self, estado: EstadoMundo, ts_ms: int) -> ResultadoAcopio:
        """Evalúa el estado del mundo y devuelve la cuenta.

        `ts_ms` es el instante de **captura** del cuadro, el mismo con el que el
        seguimiento mide la edad. No se usa el reloj de pared: si el
        procesamiento se atrasa, la permanencia tiene que medirse sobre el
        tiempo en que las cosas pasaron, no sobre el tiempo en que se las miró.
        """
        cubos = {c.color: c for c in estado.cubos}  # el color ES la identidad

        zonas = []
        for color in sorted(self._geometrias):
            cubo = cubos.get(color)
            if cubo is None:
                # Sin cubo no hay nada que sostener: se olvida el conteo para
                # que, si vuelve, tenga que ganarse la permanencia de nuevo.
                self._desde_ms.pop(color, None)
                zonas.append(EstadoZona(
                    color=color, presente=False, adentro=False, contado=False,
                    falta_celdas=float("inf"), adentro_hace_ms=0, edad_cubo_ms=0,
                ))
                continue

            veredicto = schema.cubo_en_depot(
                col=cubo.col, row=cubo.row, geometria=self._geometrias[color])

            if not veredicto.adentro:
                self._desde_ms.pop(color, None)
                adentro_hace_ms = 0
            else:
                desde = self._desde_ms.setdefault(color, ts_ms)
                if ts_ms < desde:  # el reloj retrocedió: se reancla, no se resta mal
                    desde = ts_ms
                    self._desde_ms[color] = desde
                adentro_hace_ms = ts_ms - desde

            zonas.append(EstadoZona(
                color=color,
                presente=True,
                adentro=veredicto.adentro,
                contado=veredicto.adentro and adentro_hace_ms >= self._permanencia_ms,
                falta_celdas=veredicto.falta_celdas,
                adentro_hace_ms=adentro_hace_ms,
                edad_cubo_ms=cubo.age_ms,
            ))

        return ResultadoAcopio(zonas=tuple(zonas))
