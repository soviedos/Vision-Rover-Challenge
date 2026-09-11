# Contrato de telemetría — Vision-Rover-Challenge

**Protocolo v2**

Este documento es el acuerdo entre el **sistema de visión** y **los equipos**.
La visión mira la cancha desde arriba y publica, varias veces por segundo, dónde
está cada cosa. Ustedes lo consumen.

Lo que está acá **no cambia por sorpresa**. Si algo tiene que cambiar, sube el
número de versión (`v`) y se les avisa. Pueden escribir código contra este
formato con confianza.

> ### 🔁 Qué cambió en la v2
>
> - Las **zonas de acopio** dejan de ser un punto en una esquina: ahora son
>   **rectángulos de 20 × 10 cm**, uno al **centro de cada uno de los tres lados**
>   que no son el de la salida. `depots[i]` es el **centro** del rectángulo.
> - La **salida** deja de estar en la esquina del marcador 0 y pasa al **centro
>   del lado que va del marcador 0 al 3** (el lado izquierdo). **El origen de
>   coordenadas no se movió**: sigue siendo el centro del marcador 0.
> - El mensaje suma dos campos raíz: **`depot_size`** (el tamaño de las zonas) y
>   **`cube_side`** (el lado del cubo), los dos en celdas.
> - Con eso se puede calcular **si un cubo está completamente dentro de su
>   zona**, que es la condición de entrega del reglamento. La regla, con código
>   para copiar, está en la [sección 3](#cuándo-un-cubo-está-en-su-zona).
>
> La nota de migración —qué se rompe y qué no— está en la
> [sección 9](#9-cambios-de-contrato).

> ### 🚀 ¿Nunca corriste esto? Empezá por la [sección 7](#7-herramientas-incluidas-y-cómo-correrlas)
>
> Ahí está la guía paso a paso para pasar de "tengo la carpeta" a "veo
> telemetría en pantalla", sin dar por sabido nada de línea de comandos.
> Las secciones 1 a 6 describen **el formato**; la 7 explica **cómo correrlo**.

---

## 1. Cómo se conectan

| | |
|---|---|
| **Transporte** | TCP |
| **Puerto** | `2026` |
| **Formato** | NDJSON — **un objeto JSON por línea**, terminada en `\n` |
| **Codificación** | UTF-8 (en la práctica, ASCII) |
| **Dirección** | Solo la visión escribe. Ustedes **nunca envían nada**. |

Se conectan, leen líneas y listo. No hay handshake, ni suscripción, ni comandos.

### El error clásico: TCP no respeta los límites de los mensajes

Un `recv()` puede devolverles **media línea**, o **dos líneas y media**. Si
parsean directo lo que llegó, les va a funcionar en la compu y les va a fallar
en la cancha.

**Hay que acumular en un buffer y cortar por `\n`:**

```python
buffer = b""
while True:
    trozo = conexion.recv(4096)
    if not trozo:
        break                      # la visión cerró la conexión
    buffer += trozo
    while b"\n" in buffer:
        linea, buffer = buffer.split(b"\n", 1)
        mensaje = json.loads(linea)
        # ... usar mensaje ...
```

Está implementado así en [`test_client.py`](test_client.py), listo para copiar.

### Si la conexión se cae

Reconecten. La visión acepta clientes en cualquier momento y les manda el estado
actual: **no hay que ponerse al día con nada**, porque no existe historial. El
primer mensaje que reciben ya es el presente.

### Conectarse desde el robot: la IP importa

En todos los ejemplos de este documento aparece `127.0.0.1`. Esa dirección
significa **"esta misma computadora"** y solo sirve para probar el simulador y
el cliente en una sola máquina.

**Un robot nunca se conecta a `127.0.0.1`.** El rover es otro aparato, en otro
lugar de la red: tiene que apuntar a la **IP de la computadora donde corre la
visión** (o el simulador).

**1. Averiguá la IP de la máquina de visión.** En esa computadora, ejecutá:

| Sistema | Comando |
|---|---|
| Windows (PowerShell) | `ipconfig` → mirá "Dirección IPv4" del adaptador de Wi-Fi |
| macOS | `ipconfig getifaddr en0` |
| Linux | `hostname -I` |

Te va a dar algo como `192.168.1.47`. **Esa** es la dirección que va en el
código del robot, junto con el puerto `2026`.

**2. Los dos tienen que estar en la misma red.** El robot y la computadora de
visión deben estar conectados al **mismo Wi-Fi**. Si el robot está en la red de
invitados y la computadora en otra, no se van a ver aunque la IP esté bien.

**3. Si no conecta, sospechá del firewall.** El cortafuegos de Windows suele
bloquear conexiones entrantes la primera vez. Hay que permitirle a Python
aceptar conexiones en redes privadas.

**4. Probá primero desde otra computadora**, antes de pelearte con el robot:

```bash
python3 test_client.py --host 192.168.1.47 --port 2026
```

Si eso funciona desde otra máquina de la red, el problema no es la visión: es el
código o la red del robot.

> **Qué viene después: el cliente de referencia del robot.** El cliente que
> vamos a entregar para el rover está pensado en **CircuitPython, sobre
> ESP32/IdeaBoard** (no Arduino). Todavía **no está incluido en esta carpeta**;
> se va a agregar más adelante.
>
> Mientras tanto, el ejemplo probado y funcionando es el de la sección 7: abrir
> un socket TCP contra `IP:2026`, acumular en un buffer, cortar por `\n` y
> parsear con `json`. Eso es todo lo que necesita el rover; lo único que cambia
> en la placa es la parte de conectarse al Wi-Fi.

---

## 2. El mensaje

Ejemplo real, formateado para leerlo (en el cable viaja **todo en una sola
línea**):

```json
{
  "v": 2,
  "seq": 4137,
  "ts_ms": 1785012345678,
  "phase": "RUNNING",
  "grid": { "cols": 43, "rows": 43, "cell_mm": 20.0 },
  "rovers": [
    { "id": 10, "col": 18.402, "row": 6.705,  "theta": 84.20, "age_ms": 0 },
    { "id": 11, "col": 15.265, "row": 28.661, "theta": 40.22, "age_ms": 0 }
  ],
  "cubes": [
    { "color": "green", "col": 21.480, "row": 2.512,  "age_ms": 0   },
    { "color": "blue",  "col": 15.000, "row": 29.000, "age_ms": 425 },
    { "color": "red",   "col": 33.071, "row": 25.983, "age_ms": 0   }
  ],
  "obstacles": [],
  "start":  { "col": 2.5, "row": 21.5 },
  "depots": [
    { "color": "green", "col": 21.5, "row": 2.5  },
    { "color": "red",   "col": 40.5, "row": 21.5 },
    { "color": "blue",  "col": 21.5, "row": 40.5 }
  ],
  "depot_size": { "length": 10.0, "depth": 5.0 },
  "cube_side": 3.0
}
```

> Mirá el cubo **azul**: `age_ms: 425`. El rover 11 está justo encima
> (`15.265, 28.661`) y lo tapa. El cubo **no desapareció** de la lista: sigue
> ahí, con su última posición conocida y la edad creciendo. Esto es lo normal,
> no un error. Ver la sección 6.
>
> Y mirá el **verde**: está en `(21.480, 2.512)` y su zona está centrada en
> `(21.5, 2.5)`. Ese cubo **ya está entregado**, y se comprueba con la cuenta de
> [más abajo](#cuándo-un-cubo-está-en-su-zona) — no alcanza con que las
> coordenadas se parezcan.

---

## 3. Campo por campo

### Nivel raíz

| Campo | Tipo | Significado |
|---|---|---|
| `v` | entero | Versión del protocolo. Hoy `2`. **Si ven un número que no conocen, descarten el mensaje**: el formato cambió. |
| `seq` | entero | Número de secuencia, sube de a uno por mensaje publicado. Sirve para detectar pérdidas. |
| `ts_ms` | entero | Instante de **captura del cuadro**, en milisegundos desde época (Unix). **No** es el instante de envío. |
| `phase` | texto | `IDLE`, `READY`, `RUNNING` o `FINISHED`. Ver sección 5. |
| `grid` | objeto | Dimensiones de la cancha. |
| `rovers` | lista | Robots detectados. **Dinámico.** |
| `cubes` | lista | Cubos detectados. **Dinámico.** |
| `obstacles` | lista | Obstáculos detectados. **Dinámico.** |
| `start` | objeto | Punto de salida de los robots. **Estático.** |
| `depots` | lista | Zonas de acopio: el **centro** de cada una. **Estático.** |
| `depot_size` | objeto | Tamaño de las zonas, en celdas. **Uno solo para las tres.** **Estático.** |
| `cube_side` | número | Lado del cubo, en celdas. **Estático.** |

### `grid`

| Campo | Tipo | Significado |
|---|---|---|
| `cols` | entero | Ancho de la cancha, en celdas. |
| `rows` | entero | Alto de la cancha, en celdas. |
| `cell_mm` | float | Lado de una celda en milímetros. Vale `20.0`. |

**Lean `grid` del mensaje, no lo hardcodeen.** La cancha efectiva es el área
encerrada por los **centros** de los cuatro marcadores ArUco de esquina, y
depende de dónde se peguen el día del montaje.

> **Ojo: el tablero físico y la cancha del sistema son dos números distintos.**
> En la cancha actual, el tablero mide **50 × 50 cuadros** pero la cancha
> efectiva es de **43 × 43 celdas**, porque los marcadores van pegados hacia
> adentro del borde. Los 7 cuadros de diferencia son margen y **no se usan**:
> todo el juego ocurre dentro del área de 43 × 43.
>
> Por eso `grid` viene en cada mensaje y hay que leerlo de ahí. Si montan otra
> cancha, el número va a ser otro.

### `rovers[]`

| Campo | Tipo | Significado |
|---|---|---|
| `id` | entero | **ID del marcador ArUco** pegado al robot. Es su identidad. |
| `col` | float | Posición en celdas, eje horizontal. |
| `row` | float | Posición en celdas, eje vertical. |
| `theta` | float | Orientación en **grados**, `0` = derecha, sentido **antihorario**, rango `[0, 360]`. |
| `age_ms` | entero | Milisegundos desde la última vez que se lo vio de verdad. |

Los dos robots son **negros e idénticos**: lo único que los distingue es el
marcador. **Su rover es el del ID de su marcador.** Búsquenlo por `id`, nunca
por posición en la lista.

### `cubes[]`

| Campo | Tipo | Significado |
|---|---|---|
| `color` | texto | `green`, `blue` o `red`. **El color es la identidad.** |
| `col` | float | Posición en celdas. |
| `row` | float | Posición en celdas. |
| `age_ms` | entero | Milisegundos desde la última observación real. |

Cubos de **6 cm**. **No hay dos del mismo color**, por eso no llevan `id`: el
color alcanza para identificarlos. Puede haber 2 o 3 cubos en juego.

### `obstacles[]`

| Campo | Tipo | Significado |
|---|---|---|
| `col` | float | Posición en celdas. |
| `row` | float | Posición en celdas. |
| `age_ms` | entero | Milisegundos desde la última observación real. |

Bloques **amarillos de 10 cm**. No llevan `color` porque **el amarillo está
reservado**: un objeto amarillo **nunca** es un cubo. No llevan `id` porque son
intercambiables entre sí; lo único que importa es esquivarlos.

> ### ℹ️ En esta primera edición del reto, `obstacles` viene **vacío**
>
> No hay obstáculos en la cancha. **El campo sigue existiendo y sigue siendo una
> lista**: simplemente llega sin elementos.
>
> **Esto NO es un cambio de contrato.** El formato es idéntico y `v` sigue
> valiendo `1`. No hay que tocar nada: si iteran la lista —como manda la
> [regla 6.1](#61-iterar-nunca-indexar-por-posición-fija)— no encuentran nada y
> siguen de largo. El código que escriban hoy va a seguir funcionando si en una
> edición futura vuelven los obstáculos.
>
> El simulador también los emite vacíos, para que lo que prueban sea lo que van
> a encontrar en la cancha.

### `start`

| Campo | Tipo | Significado |
|---|---|---|
| `col` | float | Posición en celdas. |
| `row` | float | Posición en celdas. |

**Punto de salida de los robots**, compartido por los dos. Está al **centro del
lado que va del marcador 0 al 3** —el lado izquierdo mirando la cancha desde
arriba—, a 2,5 celdas del borde.

> **Ojo, que son dos cosas distintas.** Hasta la v1 la salida coincidía con el
> **origen (0,0)**, que es el centro del marcador ArUco de menor ID. En la v2 la
> salida se mudó al centro del lado, pero **el origen no se movió**: se sigue
> midiendo desde el marcador 0. Si su código usaba `start` como si fuera el
> origen, ahí hay un supuesto que dejó de valer.

### `depots[]`

| Campo | Tipo | Significado |
|---|---|---|
| `color` | texto | `green`, `blue` o `red`. |
| `col` | float | **Centro** de la zona, en celdas. |
| `row` | float | **Centro** de la zona, en celdas. |

Zonas de acopio, **una por color**, al **centro de cada uno de los tres lados**
que no son el de la salida. **Cada cubo va al depot de su color.** Se cruzan las
dos listas por `color`:

```python
depots_por_color = {d["color"]: d for d in msg["depots"]}
for cubo in msg["cubes"]:
    destino = depots_por_color[cubo["color"]]
```

**No asuman qué color va en qué lado.** Eso se define al montar la cancha y
puede cambiar. Léanlo del mensaje.

**`col` y `row` son el CENTRO del rectángulo**, no una esquina. El tamaño está
en `depot_size` y la orientación **no se declara**: se deduce, y cómo se deduce
está [más abajo](#cuándo-un-cubo-está-en-su-zona).

### `depot_size`

| Campo | Tipo | Significado |
|---|---|---|
| `length` | float | Lado **largo** de la zona, en celdas. Va **paralelo al borde** donde apoya. |
| `depth` | float | **Fondo**: cuánto entra la zona desde el borde hacia adentro, en celdas. |

Hoy vale `{ "length": 10.0, "depth": 5.0 }`, o sea **200 × 100 mm**.

Es **uno solo para las tres zonas**, y por eso viaja una vez en la raíz del
mensaje y no repetido en cada `depot`: tres copias del mismo número son tres
oportunidades de que un día digan cosas distintas.

Se llama largo y fondo —y no ancho y alto— porque **la zona gira con su lado**:
la de arriba tiene sus 10 celdas sobre `col`, y la de la derecha, sobre `row`.
"Ancho" querría decir cosas distintas en cada una.

### `cube_side`

| Tipo | Significado |
|---|---|
| float | Lado del cubo, en celdas. Hoy `3.0`, o sea **60 mm**. |

Viaja en el mensaje por la misma razón que `grid`: **no lo asuman**. El veredicto
de "cubo completamente dentro de su zona" depende del lado del cubo tanto como
del tamaño de la zona, y un número copiado de este documento no se puede
verificar contra lo que la cancha está publicando.

### Cuándo un cubo está en su zona

El reglamento pide que el cubo quede **completamente dentro** del área de su zona
de acopio. Esta es la cuenta exacta con la que se decide, y es la misma que usa
el sistema de visión para mostrarlo en pantalla.

**Primero: sobre qué lado apoya la zona.** No viene en el mensaje, se deduce. La
zona apoya su lado largo sobre el **borde de la cancha más cercano a su centro**.
Con los números de esta edición el centro está a **2,5 celdas** de su borde y a
**21,5** de los perpendiculares, así que no hay ambigüedad posible.

**Después: el margen de media diagonal.** El centro del cubo tiene que estar a
`cube_side * √2 / 2` de cada borde del rectángulo. Ese número —**2,1213 celdas =
42,43 mm**— es el radio del círculo que contiene al cubo entero, así que el
criterio **vale para cualquier rotación** del cubo, y ustedes lo pueden calcular
**con el puro centro**: la rotación del cubo no viaja en el mensaje, y no hace
falta.

Lo que queda es la **ventana de aceptación**: dónde puede caer el centro del cubo.

| | Zona | Ventana donde cae el centro |
|---|---|---|
| A lo **largo** | 200 mm | **115,15 mm** (±57,6 mm desde el centro) |
| A lo **ancho del fondo** | 100 mm | **15,15 mm** (±7,6 mm desde el centro) |

> ⚠️ **El fondo es angosto: 7,6 mm de tolerancia a cada lado del eje de la zona.**
> El sistema de visión ubica con un error máximo medido de 1 a 1,6 mm y declara
> 10 mm como criterio de aceptación, así que el margen existe pero es ajustado.
> Traducido a la cancha: **empujen el cubo hasta el fondo de la zona**, no lo
> dejen apoyado en el borde de adentro.

Este fragmento corre tal cual, con Python puro y nada importado:

```python
import math


def cubo_en_su_zona(cubo, depot, depot_size, grid, cube_side):
    """¿El cubo entero está dentro de su zona? Devuelve (adentro, cuánto falta)."""
    # 1. Sobre qué borde apoya la zona: el más cercano a su centro.
    distancias = {
        "arriba": depot["row"],
        "abajo": grid["rows"] - depot["row"],
        "izquierda": depot["col"],
        "derecha": grid["cols"] - depot["col"],
    }
    lado = min(distancias, key=lambda l: distancias[l])

    # 2. El largo va paralelo al borde, así que cuál de las dos medidas
    #    corresponde a col y cuál a row depende del lado.
    if lado in ("arriba", "abajo"):
        semi_col, semi_row = depot_size["length"] / 2, depot_size["depth"] / 2
    else:
        semi_col, semi_row = depot_size["depth"] / 2, depot_size["length"] / 2

    # 3. Media diagonal del cubo: el margen que lo mete entero con cualquier
    #    rotación, sin necesitar conocerla.
    margen = cube_side * math.sqrt(2) / 2

    exceso_col = max(0.0, abs(cubo["col"] - depot["col"]) - (semi_col - margen))
    exceso_row = max(0.0, abs(cubo["row"] - depot["row"]) - (semi_row - margen))
    falta = math.hypot(exceso_col, exceso_row)
    return falta == 0.0, falta
```

Con el cubo verde del mensaje de la [sección 2](#2-el-mensaje) —`(21.480, 2.512)`
contra una zona centrada en `(21.5, 2.5)`— da `(True, 0.0)`: está entregado. Si
el mismo cubo estuviera medio celda más abajo, en `row = 3.012`, daría
`(False, 0.1213)`: le faltarían 0,12 celdas, o sea 2,4 mm.

Está implementado así en [`test_client.py`](test_client.py), listo para copiar.

### ¿Por qué `start`, `depots`, `depot_size` y `cube_side` no tienen `age_ms`?

Porque no se detectan: **se declaran**. Son lugares y medidas fijas que siempre
están y nunca se ocluyen. Los cubos, en cambio, se mueven, se tapan y envejecen.
Por eso van en listas separadas aunque compartan el color.

---

## 4. Sistema de coordenadas

```
              col ─────────────────────────────────────►

   (0,0) ▣═════════════[  zona VERDE  ]═════════════▣ (cols, 0)
     │   ║                                          ║
     │   ║                                          ║          ▣ = marcador
    row  ║                                    zona  ║              ArUco
     │   ▪ SALIDA            ▪ cubo           ROJA  ╢
     │   ║                                          ║
     ▼   ║                                          ║
         ▣═════════════[  zona AZUL   ]═════════════▣ (cols, rows)
```

Los números exactos de esta cancha de 43 × 43 celdas:

| Lugar | Color | Lado | Centro (col, row) | Ocupa en col | Ocupa en row |
|---|---|---|---|---|---|
| Acopio | `green` | arriba (0→1) | `(21.5, 2.5)` | 16,5 a 26,5 | 0 a 5 |
| Acopio | `red` | derecha (1→2) | `(40.5, 21.5)` | 38 a 43 | 16,5 a 26,5 |
| Acopio | `blue` | abajo (2→3) | `(21.5, 40.5)` | 16,5 a 26,5 | 38 a 43 |
| Salida | — | izquierda (3→0) | `(2.5, 21.5)` | — | — |

**Léanlos del mensaje igual.** Están acá para que se entienda la disposición, no
para que los escriban en el código: si se monta otra cancha, cambian.

- **Origen (0,0)** = marcador ArUco de **menor ID (el 0)**. Desde la v2 **no** es
  la salida: la salida está al centro del lado izquierdo. El origen es desde
  dónde se mide; la salida, dónde arrancan los robots.
- **`col` crece hacia la derecha.**
- **`row` crece hacia abajo.**
- **Unidad: celdas con decimales.** Una celda = **20 mm**.
  `col = 12.35` significa 247 mm desde el origen. Para pasar a milímetros:
  `mm = celdas * grid["cell_mm"]`.
- **`theta` en grados**, `0` = hacia la derecha (`col` creciente), sentido
  **antihorario**, rango `[0, 360]`.

Ojo con el ángulo: como `row` crece hacia **abajo**, un `theta` de 90° apunta
hacia **arriba** en la pantalla (`row` decreciente). El vector unitario de avance
es:

```python
dcol = math.cos(math.radians(theta))
drow = -math.sin(math.radians(theta))   # el signo menos es porque row va hacia abajo
```

### Nunca redondeen a entero

Las posiciones vienen con decimales **a propósito**. Un cubo en `col = 12.4` no
está "en la celda 12": está a 248 mm del origen. Redondear tira 10 mm de
precisión, que es la mitad de una celda. Trabajen en float.

### Puede haber valores apenas fuera de la grilla

La visión corrige el **paralaje** (los objetos altos se ven corridos hacia
afuera desde el centro de la cámara). Después de corregir, un objeto pegado al
borde puede quedar en `col = -0.3`. Es un dato **válido**, no un error. Si
necesitan acotarlo, acótenlo ustedes.

---

## 5. Fases

**La visión es árbitro.** Ella dice en qué fase está la ronda, y los rovers
obedecen.

| Fase | Qué significa | Qué hace su rover |
|---|---|---|
| `IDLE` | Sistema encendido, ronda no preparada. | Quieto. |
| `READY` | Cancha lista, robots en la salida. Está por empezar. | Quieto. Pueden leer telemetría y planificar. |
| `RUNNING` | **Ronda en juego.** | Se mueve. |
| `FINISHED` | Ronda terminada. | **Frenar de inmediato.** |

Transiciones normales: `IDLE → READY → RUNNING → FINISHED`, y `FINISHED → READY`
para la ronda siguiente.

**En `RUNNING` se juega, en todo lo demás se está quieto.** Un rover que se
mueve fuera de `RUNNING` está infringiendo.

La visión **sigue publicando en todas las fases**, incluso en `IDLE`. Que llegue
telemetría no significa que la ronda esté corriendo: hay que mirar `phase`.

---

## 6. Reglas de consumo

Estas cinco reglas son la diferencia entre un cliente que anda en la cancha y
uno que anda solo en la compu.

### 6.1. Iterar, nunca indexar por posición fija

**Mal:**

```python
mi_rover = msg["rovers"][0]        # ¿y si esta vez sos vos el [1]?
cubo_verde = msg["cubes"][0]       # ¿y si el verde está ocluido... o el orden cambió?
```

**Bien:**

```python
mi_rover = None
for r in msg["rovers"]:
    if r["id"] == MI_ID_ARUCO:
        mi_rover = r
        break

cubo_verde = next((c for c in msg["cubes"] if c["color"] == "green"), None)
```

La cantidad de objetos **cambia entre mensajes** y el orden **no está
garantizado**. Busquen siempre por identidad: `id` para rovers, `color` para
cubos y depots. Y manejen el caso de que **no esté**: `mi_rover` puede ser
`None`.

### 6.2. `age_ms` alto significa oclusión, no desaparición

Cuando algo se tapa —un rover encima de un cubo, un reflejo sobre un marcador—
la visión **no lo saca de la lista**. Lo mantiene con su **última posición
conocida** y **`age_ms` creciendo**.

Esto es deliberado: un objeto que parpadea entre existir y no existir vuelve
loco al consumidor. Es preferible un dato viejo y marcado como viejo, que un
agujero.

**Cómo se usa:**

```python
if cubo["age_ms"] < 200:
    pass    # dato fresco, se puede navegar hacia ahí
elif cubo["age_ms"] < 1500:
    pass    # probablemente tapado por un rover; sigue estando ahí, con menos certeza
else:
    pass    # muy viejo: acercarse con cuidado y volver a mirar
```

Elijan sus umbrales, pero **elíjanlos**. Tratar un dato de 3 segundos igual que
uno de 20 ms es la forma más rápida de chocar.

Y al revés: **que un cubo tenga `age_ms` alto no quiere decir que se lo llevaron**.
Quiere decir que la visión no lo ve. Casi siempre sigue justo donde dice.

### 6.3. Quédense con el último mensaje

La visión publica con la política **"el último valor gana"**: hay un buffer de
**un solo mensaje por cliente**, y si ustedes no lo drenan a tiempo, **se pisa**.
Nunca se les va a encolar telemetría vieja.

Esto significa que **los saltos en `seq` son normales**. Si ven `seq` 100, 101,
104, se perdieron dos: ustedes estaban ocupados. No hay nada que recuperar,
porque no hay nada que valga la pena recuperar — dónde estaba su rover hace
150 ms no le sirve a nadie.

**Lo que sí importa:** si `seq` salta **mucho**, su bucle es demasiado lento.
Midan los saltos y usen ese número para calibrar. `test_client.py` los cuenta.

**No acumulen mensajes para procesarlos después.** Lean, quédense con el más
nuevo, descarten el resto.

### 6.4. No naveguen con datos viejos

Midan la latencia: **`ahora_ms - ts_ms`**. `ts_ms` es el instante de **captura**,
así que ese número es la edad real del dato desde que la cámara lo vio.

```python
latencia_ms = int(time.time() * 1000) - msg["ts_ms"]
if latencia_ms > 500:
    frenar()        # estoy manejando a ciegas
```

Si la latencia se dispara —red saturada, su bucle trabado, la visión atrasada—
lo correcto es **frenar**, no seguir con la última orden. Un rover que sigue
avanzando con datos de hace un segundo choca.

> Esto supone que el reloj del rover y el de la visión están más o menos en
> hora. Si difieren mucho, la latencia absoluta va a estar corrida; en ese caso
> miren la **variación** de la latencia, que sigue siendo útil.

### 6.5. Validen la versión

```python
if msg["v"] != 2:
    continue      # formato desconocido: descartar, no adivinar
```

Es una línea y les evita interpretar mal un mensaje del futuro.

---

## 7. Herramientas incluidas y cómo correrlas

Todo corre con **Python puro**: sin OpenCV, sin cámara, sin instalar nada.

Esta sección está escrita para alguien que **nunca usó la línea de comandos**.
Si ya te manejás, andá directo a "Resumen para tener a mano" al final.

---

### Paso 1 — Comprobá que tenés Python

Necesitás **Python 3.9 o superior**. El piso es bajo a propósito, para que te
sirva el que ya tenés: el que viene de fábrica en macOS es 3.9 y alcanza.

Abrí una terminal:

- **Windows:** apretá la tecla Windows, escribí `PowerShell`, Enter.
- **macOS:** apretá `Cmd + Espacio`, escribí `Terminal`, Enter.
- **Linux:** `Ctrl + Alt + T`.

Escribí este comando y apretá Enter:

| Sistema | Comando |
|---|---|
| **Windows** | `python --version` |
| **macOS / Linux** | `python3 --version` |

Tiene que responder `Python 3.9.x` o un número mayor.

> **⚠️ `python` y `python3` no son lo mismo.** En macOS y Linux el comando casi
> siempre es **`python3`**: si escribís `python` a secas te va a decir
> `command not found`. En Windows suele ser **`python`**.
>
> **Regla simple: usá de ahora en adelante el mismo nombre que te funcionó
> acá.** En todo este documento verás `python3`; si estás en Windows,
> reemplazalo mentalmente por `python` en cada comando.
>
> Si en Windows `python` no anda, probá `py` — algunas instalaciones usan ese.

Si no tenés Python o es muy viejo, bajalo de
[python.org/downloads](https://www.python.org/downloads/).

---

### Paso 2 — Pararte en la carpeta correcta

**Este es el paso donde más gente se traba.** La terminal siempre está "parada"
en alguna carpeta, y los comandos solo funcionan desde la carpeta correcta.

Tenés que pararte **dentro de la carpeta `contrato`** (la que contiene
`mock_publisher.py`). Escribí `cd `, un espacio, y **arrastrá la carpeta desde
el explorador de archivos hasta la ventana de la terminal**: se pega sola la
ruta. Después Enter.

Te va a quedar algo así:

```bash
cd "/Users/tu-usuario/Descargas/contrato"        # macOS / Linux
cd "C:\Users\tu-usuario\Downloads\contrato"      # Windows
```

> **Las comillas importan** si la ruta tiene espacios. Sin comillas, la terminal
> cree que le pasás varias cosas y falla.

Para confirmar que estás donde tenés que estar:

| Sistema | Comando | Qué tiene que aparecer |
|---|---|---|
| **Windows** | `dir` | la lista de archivos, con `mock_publisher.py` entre ellos |
| **macOS / Linux** | `ls` | ídem |

**Si no ves `mock_publisher.py` en esa lista, no sigas**: estás en otra carpeta
y todo lo demás va a fallar.

---

### Paso 3 — Levantar el simulador (terminal 1)

```bash
python3 mock_publisher.py
```

*(En Windows: `python mock_publisher.py`.)*

**Lo que tenés que ver si arrancó bien:**

```
==================================================================
Simulador del Vision-Rover-Challenge — protocolo v2
Publicando NDJSON en 0.0.0.0:2026 a 20 Hz
Cancha: 43x43 celdas de 20 mm
Comandos: ready | start | stop | quit
==================================================================
```

Y cada 5 segundos, una línea de estado:

```
[estado] fase=IDLE seq=94 clientes=0 pisados=0
```

Que se lee: *estoy en fase IDLE, ya publiqué 94 mensajes, no hay nadie
conectado.*

> ### ⚠️ La terminal queda ocupada y parece congelada. **Está bien.**
>
> Después del cartel no vas a poder escribir otros comandos ahí, y no vuelve a
> aparecer el símbolo del sistema. **No se colgó.** El simulador está corriendo,
> publicando 20 mensajes por segundo, y esa terminal ahora le pertenece.
>
> Dejala abierta y **no la toques**. Todo lo demás va en una segunda terminal.

---

### Paso 4 — Conectar el cliente (terminal 2)

Hace falta **una segunda ventana de terminal**, porque la primera está ocupada
con el simulador.

**Cómo abrir la segunda:**

- **Windows:** abrí PowerShell de nuevo desde el menú Inicio.
- **macOS:** con la Terminal en primer plano, `Cmd + N`.
- **Linux:** `Ctrl + Alt + T` otra vez.

**Importante: en esta terminal nueva hay que repetir el Paso 2.** Cada ventana
arranca en su propia carpeta y no hereda nada de la otra. Volvé a hacer `cd` a
la carpeta `contrato`.

Y ahora sí:

```bash
python3 test_client.py
```

**Lo que tenés que ver si conectó bien:**

```
Conectando a 127.0.0.1:2026 ...
Conectado. Ctrl-C para cortar.

--- primer mensaje: ejemplo de consumo -------------------------
  cancha: 43x43 celdas de 20.0 mm  |  fase: IDLE
  rover id=10  col=3.94 row=17.45 theta=359.9°  age=0 ms
  rover id=11  col=4.02 row=25.43 theta=358.5°  age=0 ms
  zona de acopio: 10.0 x 5.0 celdas (largo x fondo)  |  cubo: 3.0 celdas de lado
  cubo green en (25.99, 10.10) -> zona arriba (21.50, 2.50)  age=0 ms  [le falta 7.40 celdas]
  cubo blue  en (14.92, 28.93) -> zona abajo (21.50, 40.50)  age=0 ms  [le falta 11.78 celdas]
  cubo red   en (32.92, 26.08) -> zona derecha (40.50, 21.50)  age=0 ms  [le falta 7.40 celdas]
  salida en (2.50, 21.50)
---------------------------------------------------------------

[  2.0s] recibidos=38 invalidos=0 saltos=0 (perdidos=0)  latencia min/prom/max = 0/19/35 ms  age_max=38 ms
```

> Los dos rovers arrancan **junto a la salida**, al centro del lado izquierdo, y
> los tres cubos están repartidos por la cancha: por eso a cada uno "le falta"
> lo que le falta para entrar en su zona. Ese corchete es la cuenta de la
> [sección 3](#cuándo-un-cubo-está-en-su-zona) corriendo sobre datos de verdad,
> y cuando el cubo entra dice `EN POSICIÓN`.
>
> `obstacles` no aparece porque llega **vacío**, que es lo normal en esta
> edición del reto.

**Cómo leer esas cifras:**

| Dato | Qué significa | Qué esperar |
|---|---|---|
| `recibidos` | mensajes que llegaron | sube sin parar, ~20 por segundo |
| `invalidos` | mensajes que violaron el contrato | **tiene que ser 0** |
| `saltos` | veces que se salteó un número de secuencia | normal que haya algunos |
| `latencia` | cuánto tardó el dato en llegar, en milisegundos | decenas de ms |

Y en la **terminal 1** vas a ver aparecer la confirmación del otro lado:

```
[cliente] conectado 127.0.0.1:54087
```

Si ves eso, **funciona**. Ya estás recibiendo telemetría.

---

### Paso 5 — Controlar la fase de la ronda

Los comandos se escriben **en la terminal 1, la del simulador**, uno por vez, y
se aprieta **Enter**. El simulador hace de **árbitro**: él decide en qué fase
está la ronda.

| Escribís | Deja la fase en | Qué significa | Qué hacen los robots |
|---|---|---|---|
| `ready` | `READY` | Cancha lista, robots en la salida | Quietos |
| `start` | `RUNNING` | **¡Arrancó la ronda!** | Se mueven |
| `stop` | `FINISHED` | Se terminó | Frenan de inmediato |
| `quit` | — | Apaga el simulador | — |

El orden natural es **`ready` → `start` → `stop`**. Para otra ronda, `ready` de
nuevo.

Cada vez que escribís uno, el simulador te confirma en pantalla:

```
[fase] fase: IDLE -> READY
[fase] fase: READY -> RUNNING
[fase] fase: RUNNING -> FINISHED
```

Ese `fase: X -> Y` es la prueba de que te escuchó.

> **Equivocarte de orden no rompe nada.** Si escribís `start` sin haber hecho
> `ready`, te responde:
>
> ```
> [fase] 'start' no es válido desde IDLE (se puede desde ['READY'])
> ```
>
> y sigue funcionando normal. Probá tranquilo.

El campo `phase` del mensaje cambia al instante, así que podés ver en el cliente
cómo reacciona tu código a cada fase. Qué significa cada una en detalle está en
la **sección 5**.

---

### Paso 6 — Cerrar todo

**Para cerrar el cliente (terminal 2):** apretá **`Ctrl + C`**. Te imprime un
resumen final y volvés al símbolo del sistema.

**Para cerrar el simulador (terminal 1):** dos formas, las dos válidas.

- Escribí **`quit`** y Enter. Es la forma prolija.
- O apretá **`Ctrl + C`**.

En ambos casos te despide con:

```
Simulador detenido. Mensajes publicados: 465
```

Podés cerrar el simulador **aunque el cliente siga conectado**: espera a que
todos terminen antes de salir.

> **`Ctrl + C` no es "copiar" en la terminal.** Es la señal de "interrumpí lo
> que estás haciendo". Para copiar texto en una terminal se usa `Ctrl + Shift +
> C` en Windows/Linux, o `Cmd + C` en macOS.

---

### Problemas frecuentes

#### `No se pudo conectar: [Errno 61] Connection refused`

**Qué pasó:** el cliente no encontró a nadie escuchando.

**Causa casi siempre:** arrancaste el cliente **antes** que el simulador, o el
simulador se cerró.

**Solución:** andá a la terminal 1 y confirmá que el simulador esté corriendo
(tiene que estar mostrando líneas `[estado] ...`). Si no, levantalo primero.
**El orden importa: primero el simulador, después el cliente.**

*(En Windows el número puede ser `[WinError 10061]`; es el mismo problema.)*

#### `OSError: [Errno 48] Address already in use`

**Qué pasó:** el puerto 2026 ya está ocupado. Aparece con varias líneas de texto
técnico; **no rompiste nada**.

**Causa:** ya hay otro simulador corriendo — típicamente uno de antes que quedó
abierto en otra ventana.

**Solución:** buscá la ventana donde quedó corriendo y cerralo con `quit`. Si no
la encontrás, cerrá todas las terminales y volvé a empezar.

*(En Windows el número es `[WinError 10048]`.)*

#### `No module named 'contrato'`

**Qué pasó:** estás parado en la carpeta equivocada.

**Causa:** ese error sale al usar el comando `python3 -m contrato.mock_publisher`
desde **adentro** de la carpeta `contrato`. Esa forma solo funciona desde la
carpeta **de arriba**.

**Solución:** usá la forma simple de esta guía, que anda desde adentro de
`contrato`:

```bash
python3 mock_publisher.py
```

#### `command not found: python` / `'python' no se reconoce...`

**Qué pasó:** ese nombre de comando no existe en tu sistema.

**Solución:** en macOS y Linux probá **`python3`**. En Windows probá **`python`**
y, si tampoco, **`py`**. Usá el que te haya funcionado en el Paso 1.

#### El simulador arrancó pero no pasa nada / parece congelado

**No está congelado.** Es lo normal: la terminal queda ocupada por el programa.
Fijate que cada 5 segundos aparezca una línea `[estado] ...`. Si aparece, está
vivo. El cliente va en **otra** ventana.

#### El cliente conecta pero los rovers no se mueven

Están quietos porque la ronda no arrancó. Andá a la terminal 1 y escribí
`ready`, Enter, después `start`, Enter.

---

### Tu propio código: consumir la telemetría

Todo lo que necesitás está en el JSON que llega por la red. **No hay ninguna
biblioteca que instalar, ni ningún archivo de esta carpeta que importar.** Se
abre un socket, se leen líneas, se parsea cada una con las herramientas
estándar del lenguaje, y se leen los campos.

Este es **el** ejemplo. Corre tal cual contra el simulador:

```python
import json
import socket

HOST = "127.0.0.1"       # IP de la máquina donde corre la visión (ver sección 1)
PORT = 2026
MI_ID_ARUCO = 10         # el ID del marcador pegado a TU robot

conexion = socket.create_connection((HOST, PORT))
buffer = b""

while True:
    trozo = conexion.recv(4096)
    if not trozo:
        break                                   # la visión cerró la conexión
    buffer += trozo

    while b"\n" in buffer:
        linea, buffer = buffer.split(b"\n", 1)
        mensaje = json.loads(linea)

        if mensaje["v"] != 2:                   # versión desconocida: descartar
            continue
        if mensaje["phase"] != "RUNNING":       # fuera de la ronda no se juega
            continue

        # Mi rover se BUSCA por id. Nunca se indexa por posición: el orden de
        # la lista no está garantizado y la cantidad cambia entre mensajes.
        mi_rover = None
        for rover in mensaje["rovers"]:
            if rover["id"] == MI_ID_ARUCO:
                mi_rover = rover
        if mi_rover is None:
            continue                            # este cuadro no me vio

        # Cada cubo va al depot de SU color: se cruzan las dos listas por color.
        depots = {}
        for depot in mensaje["depots"]:
            depots[depot["color"]] = depot

        print("fase={}  mi rover: col={:.2f} row={:.2f} theta={:.1f}".format(
            mensaje["phase"], mi_rover["col"], mi_rover["row"], mi_rover["theta"]))

        for cubo in mensaje["cubes"]:
            if cubo["age_ms"] > 1500:
                continue                        # dato viejo: seguramente tapado
            destino = depots[cubo["color"]]
            print("   cubo {:<5} en ({:.2f}, {:.2f})  ->  depot ({:.2f}, {:.2f})".format(
                cubo["color"], cubo["col"], cubo["row"], destino["col"], destino["row"]))

        for obstaculo in mensaje["obstacles"]:
            pass                                # ... esquivarlos ...
```

**Probalo ahora mismo:** guardá eso como `mi_cliente.py`, dejá el simulador
corriendo (Paso 3), corrélo con `python3 mi_cliente.py` y escribí `start` en la
terminal del simulador. Vas a ver:

```
fase=RUNNING  mi rover: col=12.03 row=17.92 theta=359.2
   cubo green en (26.05, 10.06)  ->  depot (21.50, 2.50)
   cubo blue  en (14.93, 28.96)  ->  depot (21.50, 40.50)
   cubo red   en (33.03, 26.14)  ->  depot (40.50, 21.50)
```

**Detalles que importan de ese ejemplo, y por qué:**

| Qué hace | Por qué |
|---|---|
| Acumula en `buffer` y corta por `\n` | TCP no respeta los límites de los mensajes (sección 1) |
| Descarta si `v` no es 1 | formato desconocido: no adivinar |
| No hace nada fuera de `RUNNING` | moverse fuera de la ronda es infracción (sección 5) |
| **Busca el rover por `id`**, no por posición | el orden de las listas no está garantizado (sección 6.1) |
| **Cruza cubos y depots por `color`** | el color es la identidad del cubo |
| Ignora cubos con `age_ms` alto | están tapados: el dato es viejo (sección 6.2) |

> **Si no imprime nada**, es porque la ronda no arrancó: escribí `start` en la
> terminal del simulador. Y si te sale `ConnectionRefusedError`, el simulador no
> está corriendo — mirá "Problemas frecuentes" acá arriba.

> **En el robot es exactamente lo mismo.** El rover corre **CircuitPython** sobre
> ESP32, que también trae `json` y sockets: la telemetría se parsea igual, con
> las herramientas estándar del lenguaje. Lo único distinto es la parte de
> conectar la placa al Wi-Fi, y que la dirección ya no es `127.0.0.1` sino la IP
> de la máquina de visión (sección 1).

Las reglas completas de consumo —qué hacer con `age_ms`, cómo medir latencia,
por qué quedarse siempre con el último mensaje— están en la **sección 6**.

---

### Las herramientas, en detalle

#### `mock_publisher.py` — el simulador

**Miente feo a propósito.** Reproduce las patologías reales:

- **ruido** en posición y orientación;
- **oclusiones**: un rover que pasa sobre un cubo lo tapa, y el `age_ms` del
  cubo crece;
- **pérdidas** ocasionales de detección de un rover;
- **cubos que se mueven** cuando un rover los empuja.

Si tu código anda contra el simulador, tiene chance en la cancha. Si el ruido
del simulador lo rompe, la cancha lo va a romper igual.

Todo lo configurable está en [`config_simulador.json`](config_simulador.json):
tamaño de grilla, IDs de los rovers, cuántos cubos y de qué color, posiciones de
`start` y `depots`, nivel de ruido y tasa de publicación. Editá ese archivo, no
el código, para probar otros escenarios.

#### `test_client.py` — cliente de referencia

Ejemplo mínimo y funcional de consumo. Se conecta, parsea, **valida cada
mensaje** y mide latencia y saltos de secuencia. Acepta opciones:

```bash
python3 test_client.py --host 127.0.0.1 --port 2026 --duracion 10
```

| Opción | Para qué |
|---|---|
| `--host` | a qué máquina conectarse (ver sección 1 para el caso del robot) |
| `--port` | el puerto; por defecto `2026` |
| `--duracion` | segundos a escuchar y salir solo; `0` = hasta `Ctrl + C` |
| `--silencioso` | solo el resumen final |

Usalo de dos formas: como **punto de partida** para tu propio cliente, y como
**diagnóstico** — si no sabés si el problema es tuyo o de la red, corré esto al
lado y compará.

---

### Resumen para tener a mano

**Terminal 1** — parado dentro de la carpeta `contrato`:

```bash
python3 mock_publisher.py
```

Después escribí `ready`, Enter. Luego `start`, Enter.

**Terminal 2** — también parado dentro de `contrato`:

```bash
python3 test_client.py
```

**Para cerrar:** `Ctrl + C` en el cliente, `quit` en el simulador.

*(En Windows, `python` en lugar de `python3`.)*

> **Nota para quien ya se maneja:** también podés correrlos como módulos desde
> la carpeta **madre** de `contrato/`, con
> `python3 -m contrato.mock_publisher`. Las dos formas son equivalentes; la de
> esta guía se eligió porque funciona desde la carpeta donde están los archivos
> y evita el error `No module named 'contrato'`.

---

## 8. Qué garantiza la visión y qué no

**Garantiza:**

- El formato de este documento, mientras `v` valga `2`.
- Que va a **seguir publicando** aunque algo falle adentro: ante un error se
  conserva el último estado bueno y se sigue emitiendo. El sistema no se cae a
  mitad de ronda.
- Que un objeto **no desaparece** de su lista por estar tapado: se queda con su
  última posición y `age_ms` creciendo.
- Que `seq` sube de a uno **por mensaje publicado** (los huecos que ustedes ven
  son mensajes que se pisaron por la política de último-valor-gana).

**No garantiza:**

- Que todos los objetos estén siempre frescos. Miren `age_ms`.
- Que las listas tengan un largo fijo, ni un orden estable. Iteren y busquen por
  identidad.
- Que las posiciones caigan siempre dentro de la grilla (corrección de paralaje).
- Una tasa de entrega exacta a cada cliente. Un cliente lento recibe menos
  mensajes, siempre los más nuevos.

---

## 9. Cambios de contrato

Este formato **es un contrato**. No cambia sin:

1. **subir `v`**, y
2. **avisarles** con tiempo.

### Migración de la v1 a la v2

**Qué NO se rompe.** Nada de la forma del mensaje que ya consumían: `grid`,
`rovers`, `cubes`, `obstacles`, `phase`, `seq`, `ts_ms`, `start` y `depots`
siguen existiendo, con los mismos nombres, los mismos tipos y las mismas
unidades. El transporte, el puerto, el NDJSON y la política de último-valor-gana
tampoco cambian. El código que itera listas y busca por identidad sigue andando.

**Qué se rompe, y cómo darse cuenta.**

| Qué | Qué hacer |
|---|---|
| El chequeo `msg["v"] != 1` descarta **todos** los mensajes | Cambiarlo por `!= 2`. Es el síntoma más común: el cliente conecta, no procesa nada y parece que la visión no publica. |
| Un validador estricto que rechace campos desconocidos | Ahora llegan `depot_size` y `cube_side`. Aceptarlos. |
| Código que trataba `start` como el **origen (0,0)** | Ya no coinciden. El origen sigue siendo el marcador 0; la salida está en `(2.5, 21.5)`. |
| Código que asumía las zonas **en las esquinas** | Ahora están al centro de los lados. Si estaba escrito leyendo `depots` del mensaje —como pedía la v1— no hay nada que tocar. |
| Llegar a la zona y soltar el cubo "cerca" del punto | En la v1 la zona era un punto y "cerca" era una decisión de cada equipo. Ahora hay un **criterio exacto** y el cubo tiene que quedar **entero adentro**: ver [la cuenta](#cuándo-un-cubo-está-en-su-zona). |

**Qué conviene aprovechar.** `depot_size` y `cube_side` les permiten calcular
**durante la ronda** si un cubo ya está entregado, con la misma cuenta que usa la
visión. No hace falta estimarlo ni pedirlo por radio.

Si algo de este documento les resulta ambiguo, **pregunten antes de asumir**.
Una ambigüedad aclarada a tiempo cuesta cinco minutos; descubierta el día de la
competencia, cuesta la ronda.
