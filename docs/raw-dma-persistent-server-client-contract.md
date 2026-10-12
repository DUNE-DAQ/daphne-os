# Servidor y clientes de sesión DMA persistente

Contrato implementado el 2026-10-11 sobre la UAPI candidata
`daphne_afe_session_uapi.h`, ABI 1/features 31. Su disponibilidad física depende
del firmware y módulo realmente cargados; las pruebas offline no la acreditan.

## Negociación y compatibilidad

EnvelopeV2/protobuf sobre ZeroMQ se conserva. Capabilities negocia revisión 1,
2 o 3, según el máximo solicitado. `persistent` requiere revisión 3, capability
bit 7, CAPS ABI 1/features 31 y modo disponible. No hay fallback. Finite y
triggered mantienen sus contratos y defaults; configuración/alineación siguen
usando finite. No se condiciona compatibilidad a un commit de firmware.

`DmaAcquireRequest`: `capture_mode=DMA_CAPTURE_PERSISTENT`,
`protocol_revision=3`, `target_waveforms=N>0`, `waveforms=0`, canales 0..39,
L positivo, 0<=P<L, fuente software/external/timing. D=8192. Software usa AUTO.
PREPARE y START se ejecutan una vez. El pool depende de geometría y presupuesto,
con anillos normalizados por el driver, nunca de N ni del chunk de transporte.

## Ownership y presión

Un único worker posee el FD y hace GET/READ/RELEASE. GET reclama un evento;
READ copia todas sus rutas a staging; RELEASE termina toda referencia a DDR.
Sólo después del RELEASE aceptado se publica el evento en el protocolo.
EBUSY permite reintentar RELEASE, con plazo de limpieza; una operación mutante
interrumpida de resultado desconocido nunca se repite. El crédito hardware es
asíncrono y `driver_released` refleja su confirmación, no la llamada aceptada.

El staging admite como máximo 16 eventos y 64 MiB por defecto. El evento en
copia ocupa el espacio reservado dentro del mismo presupuesto. Con staging
lleno el worker deja de hacer GET, el pool DDR agota sus créditos y el firmware
suspende la aceptación entre ventanas. El worker continúa actualizando STATUS,
comprobando cancelación y plazo total. El router no ejecuta ioctls ni espera
paradas; READ del router sólo copia un fragmento acotado del staging.

STATUS lista hasta 16 `available_events`, cada uno con session/sequence/slot/
generation completos. READ exige ese ID, una ruta activa y offsets secuenciales.
Cada fragmento incluye el mismo ID/metadatos y `fragment_sequence` de 64 bits.
No se aceptan IDs en el READ legacy ni índices legacy en READ persistente.

ACK con `event_ids` valida el lote entero, ordenado desde el evento pendiente
más antiguo, y exige haber leído todas las rutas. Un ID obsoleto, duplicado,
de otra sesión/generación, o un lote parcialmente inválido no libera staging.
ACK libera staging, cuyo contenido ya no depende de DDR. El cliente debe
procesar y completar sus escrituras solicitadas antes del ACK.

## Producción, descarga, tiempos y cierre

READ y ACK por evento están disponibles en RUNNING y READY. COMPLETE del driver
significa producción detenida y guards válidos; puede preceder a la descarga.
El worker drena todos los eventos y espera released=N antes de cerrar y probar
reposo vivo. READY del servicio significa productor cerrado con staging aún
legible. ACK sin IDs sólo cierra el job cuando todos los eventos fueron ACKed
y el productor está cerrado. El último chunk puede ser parcial.

Los campos legacy completed/expected no describen sesiones persistentes. Usar
`session_progress`: target, accepted, completed, driver_delivered,
driver_released, staged, delivered (eventos completamente leídos por red),
acknowledged, ocupación/bytes, estado del driver, errores/guards, ignored[4],
segment/pauses, allocated_bytes, starts/stops y start_ns/end_ns. Contadores e
IDs conservan 64 bits. `staging_copy_ns` suma asignación/copia de rutas mediante
READ, excluyendo espera de RELEASE y la parada final.

Timeout de trigger: 10..600000 ms, excluye presión en el driver. Timeout de
presión: cero sin límite, o 10..600000 ms. Plazo total: cero delega en driver y
lease; si es explícito, 10 ms..7 días, incluyendo espera de consumo mientras
produce. Lease=30 s por defecto; STATUS/READ/ACK/KEEPALIVE lo renuevan. CANCEL y
lease vencido solicitan parada al worker, también con staging lleno. El cierre
del FD descarta referencias residuales sólo después de la prueba de reposo del
driver; después se verifica reposo vivo mediante el camino finito. Un fallo de
prueba/guards conserva cuarentena y bloquea nuevos trabajos.

## Ventanas y formato

La ventana ADC es [T-P,T-P+L). El trigger ocupa el índice P. `trigger_index` y
`window_first` usan el índice ADC; `first_cursor` y `fence_end` usan el cursor
DDR. Tras presión difieren. Fence es múltiplo de D, y su distancia al primer
cursor está en [L,L+D). Conservar `segment`, timestamp/validez, máscara,
valid_bytes[3] e ignored[4] en todos los fragmentos. No unir segmentos como un
tiempo continuo. READY demuestra prefijos DDR sin exigir motores detenidos.

Los clientes normales decodifican RAW16 LE ADC14 two's complement desplazado
dos bits a ADC14 offset binary exactamente una vez. Archivos u16 LE y contratos
de append se conservan; `persistent` se registra como modo distinto.

El patrón diagnóstico del firmware es otra codificación RAW16
`(canal<<10)|(índice_ADC&1023)`: **no usar el decoder ADC14**. La sonda
`dma/daphne-afe-session-probe` lo valida directamente y nunca lo publica como
datos analógicos. Su modo `aligned` requiere preparación del frontend por el
operador; la sonda no afirma ni configura alineación.

## Clientes

Archivos: `protobuf_acquire_list_channels.py --dma --capture-mode persistent`.
Inicia una sesión para N; chunk sólo limita las tandas de transporte. Guarda
incrementalmente y hace ACK después de flush. El JSONL conserva metadatos por
evento, offsets de append y resultado final, con tiempos de cliente total,
READ RPC (incluye transporte/serialización), validación/decoder y escritura/flush.
Flush no es un benchmark de persistencia física mediante fsync.

`osc.py --dma --capture-mode persistent` requiere `--max_waveforms N>0`.
El worker consume/guarda todos los eventos y limita emisiones de plots a
`-period_ms`; comunica las actualizaciones visuales omitidas al finalizar.
El eje sigue (j-P)/Fs. Cancelación y cierre siguen en el worker, con errores
visibles. No cambia el modo indefinido legacy de spybuffer.

Un error DMA detiene la adquisición sin rearmarla ni cerrar automáticamente la
ventana: conserva el mensaje en la barra de estado y lo imprime en stderr.
El fin normal de `--max_waveforms` conserva la salida automática. Después de
`configure_fe_min_v2.py --dma --skip-alignment`, los AFEs quedan sin alineación
aprobada; ejecutar el scan DMA antes de volver a abrir `osc.py` para adquirir.

Opciones explícitas para pruebas manuales:

- `scan_afe_delay_eye.py --dma --apply-best --skip-ramp-verification` aplica
  el candidato de la búsqueda sin ejecutar la verificación larga final. El
  resultado registra `ramp_verification_skipped`; la admisión queda sin
  alineación aprobada. El CSV y JSON conservan las mediciones de la búsqueda.
- `osc.py --dma --force_acq` (alias `--force-acq`) solicita al servidor adquirir
  sin exigir la máscara de canales alineados, incluyendo AFEs no configurados,
  fallidos o parcialmente alineados. No cambia ese estado ni otorga aprobación.
  Se mantienen comprobaciones de identidad, clocks, power, IDELAY-controller,
  formato ADC, budgets, ownership, guards y reposo. El contrato de archivos
  forzados registra `force_acquisition=true`, separando el append de datos
  adquiridos con admisión normal.

Ambas opciones requieren soporte anunciado por el servidor mediante capacidades
aditivas; un servidor anterior se rechaza explícitamente. `force_acquisition`
se transmite y se confirma en la respuesta de trabajo, en finite, triggered y
persistent. No cambia la UAPI del driver ni requiere recompilarlo.

Sin `--skip-ramp-verification`, el scan ordena los mejores candidatos de cada
bitslip por canales admitidos y ancho de ventana, y prueba hasta 16 con toda
la longitud solicitada. Selecciona el primer candidato cuyos canales admitidos
tengan cero errores. Registra contadores delta/low/boundary de los rechazados;
si ninguno pasa restaura el timing anterior y falla. El presupuesto incluye
el peor caso antes de MMIO. Un AFE cuyo scan falló puede volver a medirse,
manteniendo la admisión normal de adquisición bloqueada hasta aprobación.

Corrección de GUI del 2026-10-12: se reprodujo contra daphne-10 el rechazo
`ALIGNMENT_REQUIRED` tras reconfiguración. Con la corrección, la ventana
permanece visible, muestra el error, adquiere cero frames y cierra limpiamente
a petición del usuario. Las siete regresiones Qt pasan. En esa misma sesión,
el intento posterior de scan AFE0 también fue rechazado con
`ALIGNMENT_REQUIRED`, desde el PC y desde la placa con sus bindings instalados.
Durante esa comprobación no se aplicó timing ni se modificaron ajustes
analógicos. La actualización de opciones manuales permite reintentar un scan
desde `FRONTEND_FAILED`: ese estado bloqueaba también la recalibración en la
versión anterior. La adquisición normal sigue bloqueada hasta aprobación.

API compartida: `start_session`, `read_batch`, `ack_batch`, `finish_session`.
Sólo una tanda sin ACK a la vez. El consumidor debe llamar `cancel` en finally
si falla su procesamiento; los clientes CLI y Qt lo hacen. `acquire` conserva
los modos anteriores y rechaza persistent para impedir sesiones por chunk.

## Cualificación

Pruebas nuevas: engine/servicio con UAPI inyectada, staging lleno, RELEASE busy,
vueltas/generaciones, stale/double ACK, N>2^32, cancelación y metadatos corruptos;
clientes offline de archivos/append, decoder y Qt; cliente Python contra el
servicio C++ real por ZeroMQ con backend simulado. No prueban coherencia DDR.

El [informe físico del 12 de octubre](raw-dma-persistent-physical-results-2026-10-12.md)
registra la carga de 630a9da, el DTBO Linux compatible, las pruebas reales desde
daphne-dev y las mediciones por etapa. La admisión triggered se refresca en el
worker después de calibración, manteniendo capabilities como consulta cacheada.

Ensayos físicos separados: sonda patrón N=1/2/8/37 y presión, cliente de archivos
con N no múltiplo de chunk, Qt offscreen/archivo, lease/cancel y adquisición finita
posterior. External/timing requieren estímulos controlados y revisión CDC.
El driver usa polling (mínimo efectivo 4 ms); IRQ no está integrada. La parada
final mantiene el coste heredado del proveedor. Medir hardware, staging, red,
decoder y disco; el 80% del plan anterior no es un umbral aprobado.
