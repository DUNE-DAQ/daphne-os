# Extensión del driver: trigger hardware e historial DDR

Complementa la API finita, que mantiene sus ioctls y estructuras ABI 1.
El firmware experimental requiere identidad variante 3, capacidad bit 6 y
extensión AFEC `B0080100=1`. No se altera el perfil default spybuffer, daphneServer,
los protobuf ni los servicios de arranque como parte de esta implementación.

## UAPI

`daphne_afe_dma_uapi.h` añade:

- PREPARE_TRIGGER (A45, config 48 bytes): flags pattern/aligned, máscara, L, P,
  período, ring, fuente, timeout y build esperado.
- ARM (A46): comienza a escribir historial. Tras COMPLETE permite reutilizar
  buffers; invalida la waveform anterior, que debe haberse leído previamente.
- SOFTWARE_TRIGGER (A47): evento posterior a ARM, mediante MMIO. Devuelve
  EAGAIN mientras no haya historial suficiente o el mailbox esté ocupado.
- TRIGGER_STATUS (A48, 272 bytes): status finito embebido, índice/timestamp
  del trigger, comienzo de ventana, ticks totales, ARMED, validez e ignorados.

Fuentes: 0 software, 1 external, 2 timing. No equivalen automáticamente a los
valores de selección spybuffer. `read()` y SELECT_ROUTE no cambian de API:
se devuelven exactamente L ticks por ruta, ordenados desde T-P, sin padding.
`received_bytes` en la extensión cuenta el stream completo escrito, incluyendo
historial y drenaje; `valid_bytes` solo cuenta la waveform devuelta. El campo
`captured_ticks` antiguo puede contener la parte baja del stream; usar el nuevo
`stream_ticks` de 64 bits para ese conteo. El timestamp antiguo sigue siendo el
primer tick del stream, y `trigger_timestamp` es el evento registrado en hardware.
No inferir validez absoluta si `trigger_flags & 1` es cero.

P<L; período potencia de dos entre 8 y 1048576; ring múltiplo de período y
>= L+2*período; máximo 512 períodos, 256 MiB/ruta y pool 448 MiB por defecto.
Reservas coherentes contiguas por ruta: fallo CMA se devuelve al cliente.
Timeout comprende espera de trigger y captura. No hay escritor automático
tras open/PREPARE, después de COMPLETE, al cerrar ni durante arranque.

## Proveedor necesario

El consumidor nuevo funciona en modo finito con el proveedor cualificado anterior.
Para cíclico exige `daphne_bounded_cyclic_api()` versión 1 y driver
`daphne-dma-bounded`. El proveedor original no ofrece esa admisión.

`kernel/daphne-afe-dma/prepare_cyclic_provider.py` requiere el directorio del
proveedor bounded del punto 3 con `dmaengine.h` y fuente SHA256
`7b0694e793756b72835c23a934b327479493bce4a1223647a87a96d7d0afea70`.
Aplica `cyclic-provider.patch` sin fuzz en un directorio nuevo. Corrige enlaces
cíclicos/append AXI DMA a 40 bits, propaga fallo de reset antes de liberar SG y
mantiene solo IRQ de error para el consumidor sin callback de período.

```bash
python3 daphne-server/kernel/daphne-afe-dma/prepare_cyclic_provider.py \
  /ruta/al/proveedor-bounded-cualificado /ruta/nueva/proveedor-ciclico
make -C "$KDIR" M=/ruta/nueva/proveedor-ciclico ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" modules
make -C "$KDIR" M="$PWD/daphne-server/kernel/daphne-afe-dma" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" modules
```

DONE del firmware prueba todas las respuestas DDR de payload antes de terminar
los DMA. Cyclic callbacks, DMASR Idle y reset no se usan como prueba de integridad.
Si la parada no se confirma, el consumidor conserva reservas/canales y bloquea
la descarga del módulo mediante QUARANTINED. No descargar overlay para recuperar
ese estado; seguir el procedimiento de recuperación cualificado.

## Compilación y diagnóstico

Compilado en daphne-dev en `/tmp/daphne-trigger-driver/{consumer,provider}`,
contra `6.18.10-xilinx-g4f7afe14f724`, ARM64. Fuentes y logs aislados, módulos
sin instalar. Verificación del parche reproducible realizada, normalizando
únicamente finales de línea. No se ha cargado firmware ni driver en DAPHNE10.

Tras calificar firmware/proveedor y preparar AFEs, el helper directo permite
una waveform con metadatos y archivos por ruta:

```bash
sudo python3 daphne-server/dma/daphne-afe-trigger.py \
  --channels 0,1,8,16,24,32 --length 100000 --pretrigger 1000 \
  --source software --period-ticks 65536 --ring-ticks 262144 \
  --expected-build-id 0xBUILD --pattern --output /tmp/trigger-prueba-nueva
```

Sustituir BUILD por la identidad real; usar `--frontend-aligned` en lugar de
`--pattern` únicamente después de configurar y verificar los cinco AFEs.
External/timing esperan el evento físico y no lo emiten desde Linux.
El helper no cambia servicios, gateware, SPI ni defaults. No demuestra jitter
físico; ese ensayo requiere un evento referenciado y configuración verificable.

La integración posterior debe mantener el default spybuffer, seleccionar esta
API solo con petición explícita y capability comprobada, transportar índice del
trigger, P, L, timestamp/validez y estado de fallos, y detener historial por lease,
cancelación o desconexión. N es número de eventos aceptados, C agrupa waveforms.
Esta versión necesita ARM/evento/READ por waveform; múltiples slots simultáneos
y descarga concurrente permanecen como etapa posterior del plan.
