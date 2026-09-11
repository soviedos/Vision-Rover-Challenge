# reglas/

**Lo que el sistema decide**, a partir del estado del mundo que producen los
detectores y el seguimiento.

Está separado de [`../detectors/`](../detectors/README.md) por la misma razón
que el proyecto separa siempre **detectar** de **decidir**: son dos trabajos
distintos y, sobre todo, se equivocan de formas distintas. Un detector falla por
la luz, un reflejo o una oclusión; una regla falla por el criterio. Mezclados,
no hay forma de saber cuál de los dos anduvo mal.

## Lo que existe

### `acopio.py` — cuántos cubos están en posición

Aplica la regla de entrega del reglamento: un cubo está entregado cuando queda
**completamente dentro** de la zona de acopio de su color.

| Hace | No hace |
|---|---|
| Evaluar cada cubo contra su zona | **Dibujar** — eso es de [`../vista.py`](../vista.py) |
| Llevar la memoria entre cuadros | **Publicar** — el conteo no viaja en el mensaje |
| Exponer la cuenta y el detalle por color | **Cambiar la fase** — la ronda la cierra una persona |

## El veredicto no se calcula acá

Sale de [`contrato/schema.py`](../../contrato/CONTRATO.md), que es el mismo
código que corre el equipo en su rover. Si esta pieza escribiera su propia
versión de la cuenta, un cubo podría estar *adentro* en nuestra pantalla y
*afuera* en el código del equipo, y no habría forma de decidir quién tiene
razón.

Lo que vive acá es la **memoria entre cuadros**, que es justamente lo que el
contrato no puede tener: él ve un cubo y una zona, no una secuencia.

## Por qué hay una permanencia mínima

El conteo es **en vivo**: cuenta los que están adentro **ahora**. Si un rover
saca un cubo, la cuenta baja.

El problema es que la ventana de aceptación sobre el fondo de la zona es
angosta —**7,6 mm** a cada lado del eje— así que un cubo dejado justo en el
borde del criterio entra y sale del veredicto con el puro temblor de la
detección. Sin permanencia, el número saltaría entre 2 y 3 varias veces por
segundo, y eso en pantalla **se lee como un sistema roto**.

**La permanencia solo demora entrar, nunca salir.** Demorar la salida sería peor
que el titileo: diría que un cubo está entregado cuando un rover ya se lo llevó.

Es un milisegundaje de presentación, no un filtro de calidad: una detección
dudosa ya la filtró el seguimiento antes, conservando la última posición buena.
El valor está en `conteo_acopio.permanencia_minima_ms`.

## Un cubo tapado sigue contando

Es deliberado, y es la regla de oclusión del contrato aplicada al conteo. El
seguimiento conserva la última posición buena de un objeto tapado, así que un
cubo que ya estaba adentro y queda oculto por el rover que acaba de entregarlo
**sigue contado**.

Lo contrario sería que el contador se cayera justo en el momento de la entrega,
que es exactamente cuando hay un rover encima del cubo.

Como ese veredicto se sostiene sobre una posición **conservada** y no sobre una
observación fresca, `EstadoZona` expone la **edad** del cubo y la vista la
muestra cuando pasa a ser vieja. Quien mira la pantalla tiene que poder saber
sobre qué se apoya lo que está viendo.

## Verificado

Con `python -m vision.tools.verificar_acopio`, en dos bloques:

| Bloque | Qué comprueba |
|---|---|
| **El criterio, sin imágenes** | que el límite de la ventana esté donde dice, y que con el centro del cubo en ese límite el cubo entre entero **girado como esté** (0° a 90°, cuatro bordes, tres zonas) |
| **El sistema entero** | cubos en el centro, justo adentro, justo afuera y girados 45°, procesando el cuadro completo en los dos modos de cámara |

Cada veredicto positivo se contrasta además **contra la verdad del generador**:
que el cubo dado por entregado esté de verdad entero dentro del rectángulo.

El antirrebote se verifica aparte, con estados escritos a mano: un cubo que
entra y no se sostiene no cuenta, uno que se sostiene cuenta, uno que sale
descuenta de inmediato, y uno tapado sigue contando con su edad creciendo.

## La visión informa, no arbitra

Cuando los tres cubos están en posición, la imagen lo anuncia. **La fase no
cambia sola**: la ronda la sigue cerrando una persona con `stop`, de acuerdo con
la señal del juez. Es la misma frontera que rige en todo el sistema —la visión
dice lo que ve, los demás deciden— y por eso el conteo tampoco viaja en el
mensaje.
