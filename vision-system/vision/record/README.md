# record/

**Consumidor.** Guarda a disco lo que el sistema vio, para poder revisarlo
después. **Solo lee** el estado del mundo; nunca lo modifica.

## Lo que existe

### El acta de la ronda — `acta.py`

Se escribe **una por ronda cerrada**, incluidas las abortadas, en `actas/`.
Guarda cuándo fue, por qué terminó —reto cumplido, tiempo agotado, la cerró el
operador, abortada en preparación—, el tiempo final, cuántos cubos quedaron en
posición y cuáles, las posiciones finales, y en qué estado estaban los cubos al
empezar a jugar.

**Sin acta hay un cronómetro en pantalla y nada que revisar.** Cuando un equipo
reclame, la única respuesta posible sería la memoria de quien miraba.

Las actas **no se versionan**: son datos de una ronda concreta en una cancha
concreta, y con veinte equipos se acumulan cientos en un día. Si alguna hay que
conservar, se archiva a mano.

Dos detalles que no son obvios:

- **Los dos relojes, cada uno en su trabajo.** El tiempo final sale del
  cronómetro monótono, que ningún ajuste de hora puede mover; la fecha sale del
  reloj de pared, porque un tiempo monótono no sirve para fechar nada.
- **El arranque queda registrado.** Si algún cubo ya estaba dentro de su zona al
  pasar a `RUNNING`, el acta marca el arranque como irregular. El sistema no
  invalida la ronda por eso; deja la constancia para decidirlo después, sin que
  dependa de que alguien haya visto un aviso en pantalla.

## Lo que va a existir

### Grabación del estado del mundo

Guardar la secuencia de estados de una sesión para poder **repetirla** más tarde,
sin cámara y sin cancha.

Sirve para dos cosas concretas:

- **Depurar sin montar todo.** Si algo falló en una ronda, se vuelve a correr esa
  grabación tantas veces como haga falta, con el mismo resultado cada vez.
- **Probar cambios contra datos reales.** Un ajuste en la detección se puede
  medir contra una sesión grabada, en vez de contra una corrida nueva que nunca
  es igual a la anterior.

Es un consumidor independiente de `publish/`: que la grabación falle o se apague
no debe afectar en nada a la telemetría que reciben los equipos.
