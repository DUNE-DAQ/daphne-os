# Raw DMA: sesión persistente y adquisición con descarga concurrente

Informe para el hilo responsable de firmware y driver. Fecha: 2026-10-11.
Estado: propuesta de diseño para acordar entre ambos hilos; no autoriza comenzar
el desarrollo ni cargar firmware/módulos. Este documento no define una ABI final.

## Objetivo y responsabilidades

La funcionalidad de captura triggered ya está demostrada. La siguiente etapa
debe maximizar throughput mediante una sesión persistente: iniciar los motores
DMA al comienzo de la adquisición, producir múltiples eventos mientras se
descargan los anteriores y detenerlos al completar el objetivo o cancelar.
Optimizar únicamente el reset por waveform no satisface este objetivo.

- Hilo receptor: arquitectura de firmware, proveedor DMA y consumidor kernel;
  proponer y cualificar el contrato de buffers/eventos y su UAPI.
- Hilo daphne-os actual: daphneServer, protobuf y clientes del PC, incluidos
  osc.py y protobuf_acquire_list_channels.py; adaptar descarga incremental,
  créditos/ACK y cancelación después de acordar ese contrato.
- Ambos hilos: acordar semántica, capacidades, métricas y aceptación antes de
  desarrollar sus partes. El driver pertenece a este repositorio, aunque su
  implementación corresponde al hilo receptor.

Corrección explícita del usuario: **N=0 fue un typo; quiso decir N=1**. El ejemplo
comienza con la primera waveform y termina con la waveform N=100000. N es el
número objetivo de waveforms completas, no el índice usado para arrancar DMA.
No se solicita un modo indefinido con N=0. Para esta propuesta, N debe ser positivo;
los identificadores internos pueden usar otra base si se documenta.

No ligar admisión o implementación a un commit de firmware. Usar capacidades y
versiones de contrato/UAPI, conservando la comprobación de identidad de la sesión
real. Mantener intacto el camino spybuffer y compatible el modo DMA finito usado
por configuración/alineación. Numeración normal 0..39, sin excepción para AFE4;
el diagnóstico independiente de CH39 queda fuera de esta etapa.

## Evidencia y limitación actual

La extensión actual conserva una waveform por ARM. PREPARE reutiliza las
reservas de un lote, pero cada evento ejecuta ARM, espera trigger, completa el
stream, termina los DMA y copia la ventana. El servidor publica el lote después
de capturarlo y comprobar la parada. No existe una cola de eventos consumibles
mientras el siguiente sigue capturándose.

Mediciones del 2026-10-11:

| Camino | Resultado |
|---|---|
| Motor C++ directo, una ruta, L=2048 | ~1,31 s/evento, sin protobuf/red |
| Motor C++ directo, tres rutas, 40 canales, L=65536 | ~3,94 s/evento |
| Cliente de archivos, CH0/1, L=2048, P=1024, N=1000, chunk=10 | Usuario reportó 1000/1000 en 22:23, ~1,34 s/evento |
| osc.py, CH0/1, L=2048, P=1024 | Dos eventos adquiridos y dibujados tras corregir validación del snapshot |

El proveedor cíclico intenta RUNSTOP/HALTED, agota polling atómico con espera
nominal de 1.000.000 us por ruta y después hace reset. Las rutas se terminan
secuencialmente. Logs, código y tiempos atribuyen a esa secuencia la demora
dominante; no se dispone de un perfil por función de toda la sesión.
Reducir L o aumentar chunk no elimina esa parada por evento.

Conservar la corrección de snapshots: el consumidor actual toma los monitores
antes de halt/reset y publica COMPLETE después de comprobar DDR y parada.
Un snapshot retenido con IDLE y RUN puede describir una captura ya completada;
no debe interpretarse como prueba del estado vivo de reposo. En una sesión
persistente habrá que separar todavía más la finalización de un evento del
estado de los motores que continúan trabajando.

Referencias de implementación y ensayos:

- [Verificación del servidor/GUI y latencia](raw-dma-trigger-snapshot-fix-2026-10-11.md).
- [Contrato actual de clientes](raw-dma-trigger-client-integration.md).
- [Driver actual](raw-dma-trigger-driver.md) y
  [UAPI actual](../daphne-server/kernel/daphne-afe-dma/daphne_afe_dma_uapi.h).
- [Instrucciones de integración del firmware](../../daphne-firmware/docs/daphne-os-trigger-pretrigger-integration-instructions.md).
- [Informe físico del firmware](../../daphne-firmware/docs/afe-dma-trigger-1d17a11-board-test-2026-10-11.md).
- [Diseño previo de descarga con slots/créditos](../../daphne-firmware/docs/afe-full-dma-capture-brainstorm.md).

El diseño previo de chunks continuos aporta la propiedad de slots y el análisis
de caudales. Su regla de no delimitar ventanas por triggers no se traslada aquí:
esta propuesta sigue siendo una adquisición de waveforms sincronizadas al trigger.

## Semántica propuesta de adquisición

Una sesión configura máscara de canales, L, P, fuente y N objetivo. Las fuentes
software, external y timing mantienen su significado y requisitos. Se devuelve
exactamente L muestras por canal en la ventana [T-P, T-P+L), con 0 <= P < L.

1. Reservar un pool acotado, preparar descriptores y arrancar DMA una vez.
2. Declarar disposición para aceptar eventos cuando existe historial suficiente,
   hay espacio reservado para una ventana completa y la fuente es válida.
3. Aceptar un trigger y capturar su ventana; ignorar triggers durante esa ventana.
4. Publicar un evento inmutable cuando todas sus rutas y escrituras DDR están
   completas. La publicación no requiere detener los motores de la sesión.
5. Preparar la aceptación del siguiente trigger en hardware, sin esperar un
   round-trip de Linux o del PC por evento. Medir cualquier drenaje adicional.
6. Si no hay créditos, suspender la aceptación de nuevos eventos entre ventanas;
   continuar al recuperar espacio, sin reset/reinicio de sesión.
7. Al completar N eventos, dejar de aceptar triggers, terminar la producción
   con prueba de reposo y descargar los eventos pendientes. Sesión adquirida
   y sesión completamente entregada son estados diferentes.

N cuenta waveforms válidas completas. En un fin normal, accepted=completed=N y
delivered/acknowledged llegará a N al terminar la descarga. Un evento corrupto
no incrementa completed ni se sustituye silenciosamente por otro: publicar
el fallo y la cantidad realmente completada. No rellenar datos ausentes.

La secuencia de máximo rendimiento en software puede autorizar desde Linux una
serie de disparos ejecutados por firmware cuando hay crédito e historial válido.
Es una propuesta de nueva operación, no una función existente. Debe tener límite
N, cancelación y contadores; evitar RPC/MMIO sincronizado por cada waveform.
External/timing continúan dependiendo del evento físico, sin sustitución por
software ni replay de eventos observados mientras no se podía aceptar.

## Buffers, pretrigger y control de presión

Propuesta: pool de slots de eventos con propiedad explícita y descriptores SG
reciclables. El mecanismo exacto de descriptores corresponde al hilo receptor;
un anillo AXI DMA cyclic sin protección adicional no basta, porque reutiliza
direcciones aunque el consumidor todavía no haya liberado sus datos.

Cada evento lógico abarca sus rutas activas. Reservar conjuntamente espacio en
todas ellas antes de aceptar el trigger; una ruta con crédito no compensa otra
llena. Ninguna ruta debe sobrescribir un evento pendiente ni adelantarse con
muestras de otro evento. Considerar más de un descriptor por evento cuando lo
exijan geometría, alineación o límites SG.

Estados conceptuales de slot:

```text
FREE -> RESERVED -> FILLING -> READY -> READING/OWNED_BY_CONSUMER -> FREE
```

El retorno a FREE necesita una liberación explícita después de que ningún
lector, copia o envío conserve referencias. Usar ID de sesión, secuencia de
evento y generación de slot para rechazar lecturas/liberaciones obsoletas.
No reciclar solo por el avance del puntero del DMA.

Separar historial circular de pretrigger y retención de eventos completos.
El hilo receptor debe comparar alternativas: proteger regiones del historial,
copiar ventanas a slots, o mantener historial en otra memoria. Cuantificar RAM,
tráfico DDR, recursos FPGA, coste de copia y tiempo muerto antes de elegir.
No imponer una copia adicional por tick si elimina el rendimiento buscado.

Si el historial continúa durante la presión, los eventos pendientes deben
permanecer protegidos. Si se suspende el historial, la reanudación debe esperar
P muestras nuevas antes de declarar disposición: no unir muestras anteriores
y posteriores a una pausa como si fueran una ventana temporalmente continua.

El ADC no puede esperar al PC. Al agotarse espacio, cerrar la admisión antes
del próximo evento y conservar capacidad para acabar el que ya fue aceptado,
incluyendo drenaje y escrituras en vuelo. No usar una detención arbitraria a
mitad de waveform como mecanismo normal de presión. Un stall que provoque
pérdida de muestras dentro de una ventana es error de integridad.

Para external/timing, presión implica eventos no adquiridos aunque no haya
overwrite. Exponer contadores por motivo: captura ocupada, falta de crédito,
historial insuficiente y fuente inválida cuando sea observable. No anunciar
adquisición sin pérdidas para una fuente física que excede el caudal sostenible.
Usar contadores amplios o comunicar explícitamente saturación y alcance.

## Contrato que firmware/driver deben proponer al hilo servidor

Los nombres siguientes son conceptuales; no asignar aún números de ioctl,
registros ni revisión protobuf. Conservar las ABI finita/triggered existentes.
Anunciar la sesión persistente como capacidad adicional verificable.

| Operación/capacidad | Necesidad del servidor |
|---|---|
| Preparar/iniciar sesión | N positivo grande, L/P, máscara, fuente, presupuesto de memoria y política de disparos software |
| Estado no bloqueante | Contadores y fase cacheada: producción, espera de trigger, presión, drenaje, error; nunca esperar stop/reset desde el router |
| Esperar/obtener eventos listos | Cola incremental de eventos completos; poll/notificación agregada o alternativa que evite una IRQ por muestra/período |
| Leer/mapear un evento | Datos inmutables y límites por ruta; conservar RAW16 y orden de canales documentados |
| Liberar eventos | Créditos con IDs/generaciones; admitir liberación por lote y detectar double release/stale ACK |
| Cancelar/cerrar | Interrumpir esperas y producción, mantener datos/memoria protegidos hasta confirmar reposo |
| Capacidades/límites | Número/bytes de slots, geometría, máximo L/P/N, alineación, límites SG y política de historial bajo presión |

Metadatos por evento: sesión/secuencia, L/P/fuente/máscara, índice T y comienzo
de ventana, timestamp y validez, bytes válidos por ruta, contadores de errores
y triggers ignorados. Definir qué índices continúan durante pausas y cómo se
identifican segmentos; no comprimir huecos temporales ni inferir un timestamp
absoluto a partir del reloj monotónico de Linux.

Un evento READY necesita prueba de escrituras DDR completas para sus datos
en todas las rutas activas y metadatos estables. Con DMA activo, IRQ, IDLE,
avance SG o lectura de un contador por sí solos no reemplazan la prueba de
visibilidad/integridad. Proponer un fence por evento/rango compatible con el
solapamiento; el fence global actual ligado a DONE no es automáticamente válido.

Conservar direccionamiento de 40 bits, enlaces SG completos, guards y límites
de acceso. Confirmar coherencia/cache si cambia el tipo de memoria o se añade
mmap. MemAvailable no equivale a memoria DMA asignable; dimensionar CMA/SG
y margen real sin fijar ahora un pool mayor como requisito.

La parada final/cancelación debe ser acotada, con prueba viva de HALTED,
RUN/RESET desactivados y ausencia de escrituras pendientes. Un fallo conserva
memoria/canales y cuarentena; no liberar por vencimiento de un timeout.
Evitar polling atómico prolongado en funcionamiento normal. Optimizar también
la parada final para sesiones cortas, sin convertirla en paso por waveform.

## Adaptación posterior del servidor y clientes: responsabilidad de este hilo

- Una adquisición N grande será una sesión; no fraccionarla en jobs que vuelvan
  a arrancar/detener DMA por chunk. Separar N objetivo, profundidad del pool y
  tamaño del lote de transporte.
- Permitir leer eventos/lotes listos mientras el job sigue produciendo; no
  esperar READY del trabajo completo como en el contrato actual.
- Captura y descarga concurrentes, con todas las colas y copias acotadas.
  El staging actual de 64 MiB/256 waveforms limita un lote, no debe impedir
  N=100000 ni convertirse en una reserva proporcional a N.
- ACK del PC después de validar/consumir o guardar; traducirlo a liberación
  kernel cuando ya no existan referencias. Si se libera DDR tras una copia a
  staging, ese staging también debe tener ownership y créditos acotados: no
  trasladar la presión a una cola RAM ilimitada.
- Mantener STATUS, KEEPALIVE, lectura y CANCEL responsivos; expiración de lease
  o desconexión cancela de manera segura. Separar timeout de trigger, pausa
  por consumidor lento, transporte y plazo total de sesión.
- Cliente de archivos: escritura incremental, conteos/metadatos y ACK por lote.
  osc.py: consumir eventos de una sesión prolongada y renderizar a frecuencia
  acotada; puede omitir actualizaciones visuales, informándolo, sin presentar
  eso como pérdida de eventos adquiridos. Cerrar cancela la sesión.
- Negociar capacidades/contrato nuevos sin fallback silencioso. Conservar
  mensajes de usuario compatibles con los clientes tradicionales.

## Rendimiento: presupuesto y medición

Para K canales, RAW16 y N eventos:

```text
S_event = 2 * K * L bytes
S_total = N * S_event
event_rate_sostenible <= BW_salida_util / S_event
slots_disponibles <= (pool_util - historial - overhead) / S_event
```

La fracción de tiempo ocupada por captura añade otra cota: sin ventanas
solapadas, la tasa ideal no excede Fs/(L-P) si P se obtiene de historial previo;
P=0 da Fs/L. Esta cota ignora drenaje y otros tiempos muertos, que deben medirse.
La tasa de trigger aceptada dependerá también de créditos e historial válido.

Ejemplo solicitado, N=100000 y L=32000:

| Canales | Bytes por evento | Total | Tiempo mínimo a 125 MB/s brutos | A 100 MB/s útiles hipotéticos |
|---|---:|---:|---:|---:|
| 2 | 128 kB | 12,8 GB | 102,4 s | 128 s |
| 40 | 2,56 MB | 256 GB | 2048 s | 2560 s |

Unidades decimales; no incluye headers ni copias. 125 MB/s es el techo bruto
de Gigabit Ethernet, no un benchmark. 100 MB/s es solo un escenario de cálculo.
No prometer esas tasas hasta medir red, DDR, CPU y almacenamiento por separado.
Con historial continuo de 40 canales a 62,5 MS/s, considerar 5 GB/s nominales
de entrada más las lecturas/copias de descarga; caudal lógico de eventos y
tráfico físico DDR son métricas distintas.

Medir por etapa: historial/captura, fence/publicación, copia, transporte,
guardado/ACK y parada final. Registrar eventos/s, MB/s útiles, percentiles de
latencia, CPU por core, interrupciones, ocupación máxima de colas, tiempo en
presión y todos los contadores de eventos/errores. Identificar estímulo, K/L/P/N,
memoria y versión de capacidades de cada ensayo, sin convertirla en dependencia.

Como objetivo provisional de integración, comparar el throughput de lotes
suficientemente grandes con un baseline medido del transporte y sink equivalentes;
proponer al menos 80% de ese baseline o justificar y localizar la diferencia.
Ese porcentaje es una propuesta para acordar, no un resultado ni criterio ya
aceptado por el usuario. El criterio estructural sí es esencial: cero paradas/
resets por evento en la ruta normal y trabajo útil de captura/descarga solapado.

## Aceptación y entregables solicitados al hilo receptor

Antes de desarrollar: responder con arquitectura elegida, política de historial,
contrato de ownership/créditos, versión de UAPI/capacidades propuesta, límites
de recursos y reparto de trabajo. Acordar esta respuesta con el hilo servidor.

Después de autorización, planificar commits separados para contrato, firmware,
proveedor/consumidor y pruebas. No mezclar cambios spybuffer ni cargar hardware
como parte de una validación offline.

La aceptación debe demostrar:

1. Múltiples eventos sin parada/reset entre ellos y sin Linux en el camino
   crítico de aceptación. N=1, N=2, N mayor que la capacidad del pool y final
   parcial; L corto/largo, P=0/P>0 y máscaras de una/tres rutas.
2. Rampa física/contador reproducible: continuidad dentro de cada ventana,
   orden de canales, alineación de rutas, trigger en P y metadatos estables.
   No inferir continuidad entre eventos independientes.
3. Consumidor lento/pausado: pool lleno, pausa antes del siguiente evento,
   lectura inmutable, recuperación por créditos, rechazo de ACK obsoleto y
   N final correcto. Probar wrap y reuso muchas veces, no solo dos slots.
4. Triggers durante ventana/presión, no replay al reanudar y pretrigger fresco
   después de cada pausa según la política elegida. External/timing requieren
   fuentes físicas controladas; no cerrar su aceptación con mocks.
5. Error DDR, ruta incompleta, descriptor/guard, cancelación en captura y en
   presión, timeout, lease/desconexión y reset fallido: memoria protegida hasta
   reposo probado; cuarentena cuando corresponda.
6. Perfil de rendimiento sin red y con consumidor concurrente; después,
   integración con servidor/cliente y baseline de salida. Reproducir el problema
   actual y acreditar su eliminación con contadores start/stop/reset y tiempos.
7. Regresión de DMA finito/configuración/alineación y spybuffer, sin alterar
   defaults; compilación del kernel de destino y UAPI layouts comprobados.

Entregar documentación de registros/UAPI, estados y errores, ejemplos mínimos
de uso del driver y metadatos reales de eventos/estado. Separar resultados
simulados, físicos y estimaciones. El benchmark largo N=100000 es una campaña
final de integración dimensionada con el destino de datos; las pruebas iniciales
deben ser acotadas y superar varias veces la capacidad del pool.

Esta etapa sustituye la estrategia de parada por waveform. Su alcance excede
T6 de optimización del proveedor: incluye producción de eventos, retención,
fence por evento, presión y consumo concurrente. No se ha iniciado su desarrollo.
