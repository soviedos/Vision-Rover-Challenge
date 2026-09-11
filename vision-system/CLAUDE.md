# CLAUDE.md — Reglas del Proyecto (Sistema de Visión)

Este repositorio es un **fork** del reto **Vision-Rover-Challenge** de CENFOTEC.
Este documento fija las reglas que rigen TODO el desarrollo del **sistema de visión**
para que sea consistente. Cualquier trabajo debe respetar lo aquí escrito.

> Rama de trabajo: **`desarrollo`**. Nunca se commitea a `main`.

---

## 1. Alcance

- Construimos **únicamente el sistema de visión**: una cámara cenital que observa
  una cancha de ~1 m × 1 m y publica varias veces por segundo, por TCP, la posición
  de cada robot, cada cubo y cada obstáculo, como telemetría que los equipos consumen.
- **NO construimos la inteligencia de los rovers**: planificación, control,
  coordinación ni firmware de juego. Eso es responsabilidad de los equipos.
- **NO se toca lo existente en el repo.** Son intocables, y viven **en la raíz del
  repositorio, un nivel ARRIBA de `vision-system/`** (donde está este archivo):
  `../archivos_fabricacion/`, `../codigos/`, `../README.md`, `../reglamento.md`,
  `../robot.md` y las imágenes. No se editan, mueven ni borran sin pedir permiso.
- Todo lo nuestro va **dentro de `vision-system/`** (ver la estructura en la sección 4).

---

## 2. Regla de oro — El contrato es sagrado

El formato **JSON** que publica la visión es un **contrato** con los equipos.
Los equipos consumen ese formato y **no pueden adaptarse a cambios sorpresa**.

- El contrato **NO se cambia** sin **subir la versión de protocolo** y **avisar**.
- Todo cambio de forma, nombre de campo, unidad o semántica = cambio de contrato.
- Ante la duda: si un equipo ya escribió código contra el formato, es contrato.

---

## 3. Arquitectura

**Flujo en una sola dirección: productores → interfaz → consumidores.**

- **Productores** (cámara, geometría, detectores, seguimiento) generan un
  **"estado del mundo"**.
- **Consumidores** (publicación, grabación) **leen** ese estado.
- Lo único que cruza entre ambos lados es el **estado del mundo**, que es **inmutable**.
  No se muta en el lugar; se produce uno nuevo.

**Relojes desacoplados:**
- El **procesamiento** corre a la velocidad de la **cámara**.
- La **publicación** corre por **temporizador**.
- Uno **nunca** bloquea al otro.

**Falla abierto (fail-open):**
- Ante cualquier excepción se **conserva el último estado bueno** y se **sigue publicando**.
- El sistema **no se cae a mitad de ronda**.

---

## 4. Regla de dependencias

- El **contrato** es una pieza **independiente de primer nivel**:
  carpeta **`contrato/`**, hermana de **`vision/`**.
- El **sistema de visión puede depender del contrato**.
- El **contrato NUNCA depende del sistema de visión.**
  Debe poder entregarse solo a los equipos.

Todo nuestro trabajo vive dentro de **`vision-system/`**, que es hermana de los
archivos originales de CENFOTEC:

```
Vision-Rover-Challenge/          # raíz del repositorio (fork)
├── README.md, reglamento.md, robot.md   # de CENFOTEC — intocables
├── archivos_fabricacion/, codigos/      # de CENFOTEC — intocables
└── vision-system/               # TODO nuestro trabajo vive acá
    ├── CLAUDE.md                # este archivo
    ├── .gitignore
    ├── contrato/                # independiente; entregable a los equipos por sí solo
    └── vision/                  # depende de contrato/, nunca al revés
```

---

## 5. Decisiones cerradas (no re-litigar)

### Transporte y publicación
- **Transporte: TCP con NDJSON** (un JSON por línea). **No MQTT, no WebSocket.**
- **Puerto: `2026`.** Es el puerto oficial. El simulador del contrato y el sistema
  real publican en el **mismo** puerto, para que un equipo pase del simulador a la
  cancha sin tocar su código.
- **Versión de protocolo: `v2`.** Viaja en el campo `v` de cada mensaje.
  Un cliente que ve una versión que no conoce **descarta el mensaje**, no adivina.
  La v2 (sep-2026) movió las zonas de acopio y la salida, y agregó los campos
  raíz `depot_size` y `cube_side`. El detalle y la nota de migración están en
  `contrato/CONTRATO.md`.
- **El último valor gana:** buffer de **un mensaje por cliente**; si no drena, se pisa.
  **Nunca encolar telemetría vieja.**
- Cada mensaje lleva **número de secuencia** y **marca de tiempo de captura**.

### Árbitro y fases
- La **visión es árbitro**: expone un campo de **fase**:
  `IDLE` / `READY` / `RUNNING` / `FINISHED`.

### Sistema de coordenadas
- Anclado a **cuatro marcadores ArUco de esquina** (`DICT_4X4_50`).
- **Origen (0,0) = el CENTRO del marcador ID 0.**
  El centro y no una esquina del marcador: es lo único que se puede medir sin
  ambigüedad, tanto en una imagen como sobre la cancha física.
  **El origen NO es la salida de los robots**: desde la v2 la salida está al
  centro del lado que va del marcador 0 al 3. El origen es desde dónde se mide;
  la salida, dónde arrancan los robots.
- **Disposición de los cuatro marcadores — REGLA DE MONTAJE FÍSICO.**
  Mirando la cancha desde arriba, con el ID 0 arriba a la izquierda, los otros
  tres van en **sentido horario**:

  | Marcador | Celda de su centro | Dónde va |
  |---|---|---|
  | **ID 0** | `(0, 0)` | el **origen** de las coordenadas |
  | **ID 1** | `(cols, 0)` | siguiente en sentido horario |
  | **ID 2** | `(cols, rows)` | diagonal opuesta al origen |
  | **ID 3** | `(0, rows)` | última en sentido horario |

  **Si se pegan en otro orden, TODAS las coordenadas salen rotadas o espejadas**,
  y el sistema no se queja: publica números válidos y mal. La guía completa para
  quien arma la cancha —incluida la regla del margen blanco alrededor de cada
  marcador impreso— está en **`MONTAJE.md`**.
- La **cancha efectiva** es el área entre los **centros** de los cuatro marcadores,
  que puede ser menor que el tablero físico según dónde se peguen.
- `col` crece a la **derecha**, `row` crece hacia **abajo**.
- **Ángulo en grados**, `0 = derecha`, sentido **antihorario**.
- Posiciones en **celdas con decimales** (una celda = **20 mm**).
  **Nunca redondear a entero.**

### Entidades
- **Rovers:** identidad = **ID de su marcador ArUco**
  (los dos robots son negros e idénticos; solo el marcador los distingue).
- **Cubos:** **6 cm**, identidad = **color** (`green`, `blue`, `red`);
  **no hay dos del mismo color**.
- **Obstáculos:** bloques **amarillos de 10 cm**.
  El **amarillo está reservado**: nunca es un cubo.
- **Zonas de acopio: son TRES, una por color** (`green`, `blue`, `red`),
  **rectangulares de 200 × 150 mm**, al **centro de cada uno de los tres lados
  que no son el de la salida**: verde arriba (lado 0–1), rojo a la derecha
  (1–2), azul abajo (2–3). **Cada cubo va a la zona de acopio de su color.**
  Decisión confirmada: no hay una zona única compartida.
  - El **largo** va paralelo al borde y el **fondo** entra hacia adentro, así que
    el centro de cada zona queda a **3,75 celdas** de su borde. La salida está a
    esa misma distancia del suyo: todos los lugares fijos, al mismo margen.
  - El fondo pasó de 100 a 150 mm en sep-2026, por decisión de diseño del reto:
    con 100 la ventana de aceptación quedaba de 15 mm y un cubo que entraba
    girado podía quedar afuera por una rendija. **El criterio conservador no se
    toca; se agranda la zona.** Cambiar estas medidas **no sube la versión del
    protocolo**: son datos que viajan en el mensaje.
  - **La orientación NO se declara: se deduce** del borde más cercano al centro.
    Un segundo dato declarado podría contradecir al primero.
  - El tamaño es **uno solo para las tres** y viaja una vez en el mensaje
    (`depot_size`), no repetido en cada zona.
  - **Son virtuales: no se pega ni se pinta nada** sobre el tablero. El detector
    de cubos vive de que el tablero sea acromático, y tres rectángulos de color
    pegados serían tres manchas permanentes que segmentar.
  - Un cubo está entregado cuando queda **completamente dentro**: su centro a
    **media diagonal del cubo** de cada borde. El criterio vive en el contrato,
    para que el veredicto de la pantalla y el del rover sean el mismo código.
- **La salida es UN punto**, compartido por los dos robots, al **centro del lado
  que va del marcador 0 al 3**.
- **Lugares fijos** (salida y zonas de acopio) van en **listas separadas** de los cubos,
  aunque compartan el color: los cubos se **detectan** (se mueven, se ocluyen,
  envejecen) y los lugares fijos se **declaran** (están siempre, no envejecen).

### Cámara
- **Webcam USB**, lente **gran angular**, **enfoque manual**.
- **Exposición, enfoque y balance de blancos SIEMPRE fijos, nunca en automático.**
- **Calibración de distorsión obligatoria** por el lente ancho.

### Percepción
- **Detección de color:** segmentar por **saturación** (el tablero es acromático)
  y clasificar en espacio **Lab** (no HSV).
- **Paralaje:** los objetos altos (cubo 6 cm, marcador del rover ~10 cm) se ven
  corridos **hacia afuera**. **Corregirlo es obligatorio**, usando la **pose de cámara**
  deducida de los cuatro marcadores más la **altura conocida** del objeto.
- **Oclusión:** un objeto tapado **mantiene su última posición** con su **edad creciendo**.
  **Nunca** hacerlo parpadear entre existir y no existir.

### Cómo consumen los equipos
- Los equipos **NO importan `schema.py`**: consumen el **JSON crudo**.
  Se conectan, cortan por `\n`, parsean con `json.loads()` e iteran las listas
  buscando por identidad (`id` del rover, `color` del cubo).
- **`schema.py` es infraestructura interna nuestra:** fuente de verdad compartida
  entre el simulador y el sistema de visión. No se ofrece como biblioteca.
- Consecuencia: la documentación dirigida a los equipos **tiene un solo camino**
  —el JSON crudo— y no menciona importar nada.

### Configuración
- **Perfiles de cámara:** los parámetros específicos de cada cámara van en
  **configuración, no en el código**, para soportar más de un modelo sin bifurcar.
- **Formato de configuración: JSON.** En `contrato/` porque debe correr con
  biblioteca estándar pura; en `vision/` por coherencia, para no tener dos formatos.

---

## 6. Estándares de código

- **Python:** `vision/` requiere **3.10+**; `contrato/` requiere **3.9+**.
  La diferencia está en **quién pone el intérprete**:
  - `vision/` se instala con su **propio Python embebido** en el instalador, así
    que la versión **no depende de la máquina donde se instale**. Puede usar
    sintaxis moderna sin reparos.
  - `contrato/` se entrega **suelto, sin instalador**: cada equipo lo corre con el
    Python que ya tiene, y el de fábrica de macOS es 3.9. Piso bajo a propósito
    para no excluir a nadie.
- **Dependencias de visión:** `opencv-contrib-python`, `numpy` y `pillow`, con
  versiones fijadas. **Nada más sin pedirlo.**
  `pillow` es **solo para las herramientas visuales**: dibuja el texto en español
  sobre el video, porque `cv2.putText` es ASCII puro y escribe mal los acentos.
  Está tratada como **opcional en el código**: si falta, el panel se dibuja sin
  acentos en vez de romperse.
  El **`contrato/` no tiene ninguna dependencia**: corre con biblioteca estándar
  pura, y eso no cambia.
- El **cliente de referencia del robot** se escribe en **CircuitPython** (ESP32/IdeaBoard),
  **no en Arduino**.
- **Configuración como datos:** todo umbral, ID, rango de color, tamaño de grilla y tasa
  va en un **archivo de configuración**, no incrustado en el código.
- **Código y comentarios en español**; docstrings que expliquen el **porqué**.
- Preferir **lo simple sobre lo ingenioso**; funciones **cortas y testeables**.
- Separar **"detectar"** de **"decidir"**.
- **No sobre-ingeniería.**

---

## 7. Qué NO hacer

- ❌ No implementar lógica de los rovers.
- ❌ No cambiar el contrato sin subir versión.
- ❌ No usar MQTT ni WebSocket ni colas que acumulen.
- ❌ No usar ajustes automáticos de cámara.
- ❌ No indexar arreglos por posición fija (iterar; la cantidad de objetos varía).
- ❌ No bloquear el proceso esperando la red, ni la red esperando al proceso.
- ❌ No mutar el estado del mundo en el lugar.
- ❌ No crear archivos fuera de `contrato/` y `vision/` sin pedirlo.

---

## 8. Despliegue

- **Un solo sistema, nativo. Sin Docker.** El sistema de visión se instala y corre
  de la **misma forma en todas las máquinas**: la mía y las de los estudiantes.
  **No hay dos caminos de despliegue**, ni contenedor, ni puente de captura.
- El sistema **accede a la webcam USB directamente**, sin capa intermedia.
- **Objetivo: Windows** en las máquinas de los estudiantes.
- **La instalación tiene que ser lo más simple posible.** Es un objetivo
  importante, no un detalle: **instalador fácil, de un clic**, con
  **autodiagnóstico** que verifique cámara, dependencias y permisos, y diga en
  lenguaje claro qué falta. Veinte equipos con veinte niveles de experiencia
  distintos tienen que poder instalarlo sin ayuda.
- Las **herramientas visuales** (calibración, monitor) corren **nativas**, como
  todo lo demás.
- El **contrato** y el **simulador** se entregan **aparte, livianos**, para correr
  con **Python directo** y desarrollar **sin cámara**.

---

## 9. Git

- Rama de trabajo: **`desarrollo`**. **No commitear a `main`.**
- Commits **chicos y descriptivos, en español**.
- Remotos: `origin` = fork propio (`soviedos/Vision-Rover-Challenge`);
  `upstream` = repo original de CENFOTEC.
