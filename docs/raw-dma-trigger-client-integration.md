# Adquisición DMA con trigger y pretrigger

La extensión de `daphneServer`, `osc.py` y `protobuf_acquire_list_channels.py`
admite `software`, `external` y `timing` en modo **triggered**. Spybuffer sigue
siendo el backend predeterminado; el DMA finito mantiene su START Linux por
waveform y no requiere la extensión de trigger. El scanner DMA sigue capturando
patrones físicos en modo finito.

## Contrato

- `--dma --capture-mode finite`: software, P=0. Es el comportamiento DMA anterior.
- `--dma --capture-mode triggered --pretrigger P`: software/external/timing,
  L>0 y 0<=P<L. Se devuelve [T-P, T-P+L), con el trigger en la muestra P.
- N cuenta eventos aceptados, uno por ARM. PREPARE se hace una vez por lote;
  la waveform se copia antes del siguiente ARM. El último lote puede ser parcial.
- ARM llena el historial; software emite SOFTWARE_TRIGGER cuando ARMED.
  External/timing esperan un evento físico y nunca emiten software trigger.
- Los eventos anteriores al historial suficiente, durante captura/drenaje y
  durante el tiempo muerto no se encolan para el siguiente ARM.
- Esta entrega tiene un anillo de historial por ruta y staging acotado del lote.
  No ofrece adquisición continua ni múltiples slots simultáneos.

La admisión usa ABI, variante, capabilities y UAPI, sin fijar un commit de
firmware. Triggered requiere capability bit 6, consumidor con los ioctls A45–A48
y proveedor cyclic `daphne-dma-bounded`. PREPARE_TRIGGER comprueba AFEC y la
versión de API del proveedor antes de ARM. La negociación anuncia disponibilidad
del consumidor y binding; esa comprobación final del proveedor puede rechazar
la preparación. No existe fallback automático a finito ni a otra fuente.

**External y timing son experimentales.** El firmware dispone de esas fuentes,
pero la prueba con external controlado, timing positivo y jitter físico sigue
pendiente. Timing requiere endpoint válido; ENOLINK es un error, no una petición
para cambiar a software. CH39 conserva su tratamiento habitual y su diagnóstico
independiente queda fuera de esta entrega.

## Protocolo y límites

Capabilities usa revisión 2 solo si el cliente solicita
`maximum_protocol_revision >= 2`. Una petición antigua recibe revisión 1. Un
servidor antiguo ignora el campo nuevo y contesta revisión 1; el cliente nuevo
rechaza triggered **antes de DMA_ACQUIRE**. Regenerar protobuf C++ y Python.

El job confirma modo/fuente/P, versión de contrato y plazo total. STATUS publica
la fase almacenada por el worker, sin ejecutar TRIGGER_STATUS en el router.
KEEPALIVE y CANCEL permanecen disponibles durante la espera de eventos. El
cliente renueva la lease mientras espera o descarga; el servidor cancela al
expirar la lease y no publica READY hasta comprobar la parada.

Se conserva staging de 64 MiB por job, hasta 256 waveforms y fragmentos de hasta
1 MiB. El anillo es independiente de N:

```text
D = 8192 ticks
R = ceil((L + 2*D)/D)*D
reserva por ruta = PAGE_ALIGN(2 * canales_en_ruta * R + 128)
R/D <= 512; payload <= 256 MiB/ruta; reserva total <= 448 MiB
```

`--trigger-timeout-ms` es el plazo por waveform (10..600000 ms), incluyendo
llenado de historial y espera de evento. `--job-timeout-ms` es el plazo total del
lote; 0 deriva N*(plazo por waveform + margen de limpieza)+5000 ms. Un plazo
explícito no puede exceder ese presupuesto. `--timeout_ms`/`-timeout_ms` mantiene
su función de transporte y no sustituye al plazo del trigger.

El proveedor actual puede tardar aproximadamente 3,9 s en finalizar una captura
cyclic. La interfaz muestra espera/finalización; waveforms cortas no eliminan esa
latencia. Optimizar la terminación es una entrega separada.

Cada fragmento repite metadatos por waveform: modo, fuente, L/P, índice T,
window_first, stream_ticks, período/anillo, triggers ignorados y timestamp del
trigger con validez explícita. El timestamp antiguo conserva su referencia al
primer tick del stream. El cliente valida esos campos y su consistencia entre
fragmentos y rutas. No convierte timestamps inválidos en tiempo absoluto.

## Uso

Compilar en Linux ARM y usar los bindings generados también en el PC:

```sh
cmake -S daphne-server -B build/dma-server \
  -DCMAKE_BUILD_TYPE=Release -DDAPHNE_BUILD_DMA_DIAG=ON
cmake --build build/dma-server --parallel 2
ctest --test-dir build/dma-server --output-on-failure
export DAPHNE_PROTO_PYTHON_DIR="$PWD/build/dma-server/srcs/protobuf"
```

El cambio de firmware, módulos y servicio es una operación separada: seguir el
[handoff del driver](raw-dma-trigger-driver.md) y las instrucciones del firmware.
El cliente no carga gateware. Con la sesión triggered cualificada cargada, sin
otros propietarios del hardware y con frontend configurado/alineado, el nuevo
servidor se inicia con los mismos flags DMA:

```sh
sudo build/dma-server/daphneServer \
  --dma --gateware-mode raw-dma --bind 'tcp://*:40001'
```

La configuración conserva `configure_fe_min_v2.py --dma --skip-alignment`; la alineación
con `scan_afe_delay_eye.py --dma --apply-best` sigue siendo finita.

En PowerShell, suponiendo `$taskPython` y los bindings ya seleccionados:

```powershell
& $taskPython .\client\osc.py -ip 193.206.157.36 -port 40001 `
  --dma --capture-mode triggered --trigger-source software --pretrigger 1024 `
  -L 2048 --channels 0,1 --trigger-timeout-ms 30000

& $taskPython .\client\protobuf_acquire_list_channels.py `
  -ip 193.206.157.36 -port 40001 -foldername .\triggered_run `
  --dma --capture-mode triggered --trigger-source software --pretrigger 8192 `
  -channel_list 0,17,32 -L 65536 -N 2 -chunk 2 --trigger-timeout-ms 30000
```

External/timing usan los mismos argumentos, cambiando `--trigger-source`.
Preparar el estímulo/endpoint apropiado antes de interpretar los resultados.

`osc.py` muestra tiempo relativo `(j-P)/Fs` en µs y una línea en t=0. Durante la
espera identifica el trazado como el último evento completado. Al cerrar, mantiene
la interfaz operativa hasta terminar CANCEL y la comprobación de reposo. Si la
limpieza no se confirma, presenta el error y exige mantener el overlay cargado.

Los archivos continúan siendo ADC14 offset binary u16 little endian, en el orden
de canales solicitado. `dma_format.json` registra modo/L/P/fuente por canal; el
append rechaza contratos distintos o desconocidos para triggered antes de abrir
los archivos. Los JSON por waveform incluyen posición en los archivos y job ID.
ACK ocurre después de validar/guardar los datos. No se rellenan eventos ausentes.

## Verificación de esta integración

Las pruebas offline cubren sesión reutilizable, EAGAIN, wrap, conteos/guards,
fallos de ARM/read/parada y cuarentena; jobs/ownership/BUSY, progreso, plazo total
y expiración de lease; fuentes, negociación antigua, metadatos, append y último
lote parcial; worker Qt, eje relativo y cierre durante espera. La compilación y
CTest ARM se ejecutan en una copia aislada de `/tmp` de daphne-10, sin instalar
el binario ni modificar el servicio activo. Qt se verifica en el PC.

Resultados del 2026-10-11: compilación Release completa en daphne-10, **25/25
entradas CTest aprobadas**, 18 pruebas Python de cliente y 5 Qt aprobadas en el
PC. En ARM Qt es opcional y las pruebas Qt se omiten si no está instalado. El
binario queda en
`/tmp/dma-trigger-server-review-20261011/build/daphneServer`; el registro completo
de CTest está en `build/dma-trigger-full-ctest.log` dentro de esa copia. Los dos
ejecutables ARM (`daphneServer` y `daphne-afe-dma-quiesce`) y el registro también
se guardaron en `build/dma-trigger-arm64/` del PC; su SHA256 coincide con ARM.
La consulta
read-only del runtime activo devolvió revisión 1, capabilities `0x530`, y el
cliente nuevo rechazó triggered antes de ACQUIRE, como corresponde a esa sesión.

Esto completa la adaptación de software T1–T4. T5, la prueba física del nuevo
servidor/cliente con la sesión triggered, sigue siendo una puerta de aceptación
separada: software 1 canal y 40, P=0/P>0, dos eventos, timeout/cancel y regresión
spybuffer mínima. El informe físico previo acredita firmware/UAPI, no sustituye
esa prueba del nuevo protocolo. Preparar UART y recuperación antes de cargar
el firmware de pruebas; no repetir las campañas DDR ya cerradas. T6 (latencia de
terminación) y la cualificación física de external/timing permanecen pendientes.
