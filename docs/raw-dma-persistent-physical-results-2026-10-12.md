# Sesión DMA persistente: despliegue y pruebas físicas del 2026-10-12

La imagen `630a9da`, el consumidor kernel y el servidor ARM están instalados en la sesión experimental de daphne-10. La campaña funcional software y la corrida N=100000/L=32000 con **12,8 GB guardados y validados** pasaron desde daphne-dev. La placa queda preparada con el servidor experimental; los límites y pendientes físicos se enumeran al final.

Este documento actualiza [el informe del 11 de octubre](raw-dma-persistent-integration-results-2026-10-11.md). El usuario resolvió el acceso sudo y confirmó **VGAIN 1700**. El driver se compiló en **daphne-dev**, contra el proyecto PetaLinux original; el servidor se compiló y probó nativamente en **daphne-10**.

## Estado instalado

| Componente | Identificación |
|---|---|
| Placa y puerto | `193.206.157.36:40001` |
| Unidad experimental | `daphne-dma-manual.service` |
| Servidor | `/opt/daphne-dma-persistent-manual-20261012/daphneServer` |
| Comando | `--dma --gateware-mode raw-dma --expected-gateware-build-id 0x0630a9da --bind tcp://*:40001` |
| Firmware/identidad real | `daphne_selftrigger_ol_630a9da`, build `0x0630a9da`, ABI gateware 2.0, variante 3 |
| Contrato | Protocolo 3; sesión ABI 1, features 31, ocho slots, staging máximo 16 eventos/64 MiB |
| Kernel | `6.18.10-xilinx-g4f7afe14f724` |
| Consumidor | `daphne_afe_dma`, `max_pool_mib=448`, `/dev/daphne-afe-dma` root 0600 |
| Proveedor | `daphne-dma-bounded` en las tres rutas `b0020000/b0040000/b0060000` |
| Perfil de arranque | `self-trigger`, sin cambios |

Hashes de los productos realmente instalados:

| Producto | SHA256 |
|---|---|
| Servidor ARM final | `928686a809e160f03b8471dc72c0c3f57d6d18436915f44bfcfc9cb59c024417` |
| Sonda ARM instrumentada | `93c78e1b7d946ab60ef715a6daed820b708898abd087e167ae372e82f735aaa5` |
| Control de reposo ARM final | `2acd53b90f2f9b9f9f27bbc17c0a6aff27837f3b873e6f21c170898ce92a428a` |
| Consumidor ARM | `d25ab970bb5288e1d419974f63ab92e9427163a34ec68a9d2a3c0f0f5f9a4255` |
| DTBO Linux final | `3ad11bb16a1718eb0eff6200eb230443ce0a5bcd024eacd0ca4149303e64222d` |

El consumidor mantiene el mismo build `W=1`, compilador de la receta GCC 13.4.0, KDIR y vermagic del informe anterior. No se modificaron su UAPI ni sus fuentes durante la cualificación física.

El servidor final incorpora `0dbb33b`: refrescar la admisión triggered en el worker después de calibración. El primer servidor conservaba un resultado negativo del sondeo de arranque, aunque un diagnóstico con la misma librería confirmó soporte real (`TRIGGER_STATUS` devuelve EINVAL sin trabajo preparado). La corrección tiene una regresión offline específica; el build ARM final pasó **28/28 casos de CTest**, con los siete subcasos Qt opcionales omitidos en ARM y ejecutados en daphne-dev. La regresión física triggered posterior pasó.

`ad3f4a7` cierra la causa específica observada después de una sesión persistente: el driver reutiliza asignación cíclica, y puede conservar el indicador legacy con metadatos triggered vacíos. El ioctl devuelve éxito, ABI trigger 0 y captura ABI 1/IDLE. El sondeo final reconoce ese estado vacío como presencia del dispatcher; PREPARE_TRIGGER sigue validando ABI/proveedor y los metadatos de captura siguen exigiendo ABI 1. Se rechazan ABI desconocida, estado activo vacío, ENOTTY y EBUSY. No se modificó el driver. La corrida N100000 utilizó el servidor `bff8c0f...`; el último cambio afecta sólo sondeo de disponibilidad, y se repitieron CTest ARM y la campaña funcional en el binario final.

## DTBO y carga

El DTBO original de firmware era hardware-only: el bloque `afe_dma_capture@b0080000` tenía compatible Xilinx y una sola región. No incluía el contrato del consumidor Linux (`daphne,afe-dma-capture-v1`, cinco regiones, tres phandles DMA S2MM). El driver no enlazó y el primer control de reposo detectó ausencia del dispositivo; no se lanzó ninguna adquisición en ese estado.

Se generó el DTBO Linux **desde el DTS original de 630a9da**, con los helpers existentes `prepare_afe_dma_dts.py`/`prepare_raw_dma_dts.py` y dtc del proyecto PetaLinux. Se conservaron bitstream, identidad, clocks y propiedades de sesión; se añadió el contrato Linux validado por el consumidor. Fuentes y log en `dtbo-linux-630a9da` de daphne-dev y en el stage de la placa. DTS hardware SHA256 `2e7f74003896541abe3e3d48c29735ec720bc7fd7ffeeb1d0142a12b67bee5e3`; DTS Linux `20351b69361f4d77527264551176884a3d48717390b6a81d5673d6dd984c84f6`.

Antes de sustituir el DTBO hardware-only se comprobó explícitamente ausencia de consumidor enlazado, controlador detenido y los tres motores HALTED/RUN=0/RESET=0. Después de la carga Linux pasó nuevamente el control de reposo **a través del driver**. No se retiraron recursos en cuarentena ni se forzó unload.

Procedimiento implementado en `scripts/deploy/raw_dma_session_activate.py`, con backup y guardas de boot, identidad y hashes. La versión final de `activate` instala directamente el DTBO Linux; `repair-dtbo` conserva el procedimiento de reparación efectivamente usado. No ejecutar prepare/activate sobre una sesión ya instalada: rechaza backups e instalaciones existentes.

El kernel emitió advertencias OF de referencias/leaks de overlay al retirar/cargar la imagen, registradas por UART. La carga retornó correctamente; estos avisos heredados no se presentan como reparados.

## Frontend y alineación

Desde daphne-dev se configuró: VGAIN 1700, offset 2275, LPF 10 MHz, PGA clamp `-2 dBFS`, PGA gain `24 dB`, LNA gain `12 dB`, clamp `1.15 Vpp`, ADC resolution 0 y bias_control DAC 1300. Se conservó el pedido del usuario; no se importaron taps/slips anteriores.

Los cinco AFEs pasaron scan AUTO/coarse-step 16, búsqueda con 2048 muestras y verificación física de rampa con **32768 muestras**, ocho lanes por AFE. Se repitió después de cada reinicio del servidor corregido. Capabilities final: cinco `FRONTEND_ALIGNED`, máscaras `0xff`, generación 2. Resultados de entrega en `alignment-release-20261012/dma-eye-20261012-013135-ca276d0d`; se conservan también las mediciones anteriores. Matplotlib no estaba instalado, por lo que se conservaron CSV/JSON sin heatmap.

## Pruebas físicas realizadas

Todos los **clientes contra la placa se ejecutaron en daphne-dev**, con Python 3.9.18 y los bindings copiados del mismo build ARM, seleccionados mediante `DAPHNE_PROTO_PYTHON_DIR`. Las sondas locales driver/DDR se ejecutaron en daphne-10 como root y no son pruebas de red.

| Ensayo | Resultado y evidencia |
|---|---|
| Negociación | PASS: identidad real, revisión 3, ABI 1/features 31/slots 8 |
| Patrón N=1 | PASS, L2048/P1024, canales 39/0/17; guards y un START/stop |
| Patrón N=2 | PASS, una ruta y P=0 |
| Patrón N=8 | PASS, los 40 canales, L2048/P1024 |
| Patrón N=37 | PASS, tres rutas, L32000/P4096, vueltas de slots/generaciones |
| Patrón con consumidor pausado | PASS, 100 ms/evento, 26 pausas y datos completos |
| RPC N=37 y último lote parcial | PASS, READ en RUNNING y todos los contadores finales N |
| RPC 40 canales largos | PASS, orden inverso 39..0, L32769/P1000/N19, fragmentación sobre 1 MiB |
| Staging lleno/consumidor lento | PASS, cola 16; presión acotada y nuevos segmentos |
| IDs y ACK inválidos | PASS, lote parcialmente inválido sin liberación parcial; stale/double ACK y READ obsoleto rechazados |
| N de 64 bits y CANCEL | PASS, target 4294967297, cancelación y recursos recuperados |
| Regresión finite/triggered | PASS después de persistente; dos eventos finitos y uno triggered |
| Router durante parada final | PASS, STATUS máximo 1,20 ms en el caso de presión registrado |
| Archivos y append | PASS, sesiones N19+3, 22 waveforms/canal, 4224000 bytes en total y un START/stop por sesión |
| osc.py completo | PASS, 37 eventos de L32000 en tres rutas, 7104000 bytes guardados, último frame 37; repetición final con 12 renders/25 refrescos omitidos |
| Eje/decimación Qt | PASS, ventana original 32000 puntos, trigger en P4096 a t=0; render reduce a 16000 puntos sin reducir lo guardado |
| Cierre Qt durante sesión | PASS, retorno de close 0,49 ms; cancelación/fin del worker 3,94 s después, sin error de limpieza |
| Desconexión sin CANCEL | PASS, lease 30 s; recuperación y adquisición finita a los 33,87 s |
| N100000 con disco | PASS, una sesión, dos archivos de 6400000000 bytes, 100000 IDs y todos los contadores N |

Patrón diagnóstico valida RAW16 `(canal<<10)|(índice_ADC&1023)` directamente, sin aplicar el decoder ADC14. Los clientes reales validan framing/IDs/metadatos y guardan ADC14 offset binary tras una sola conversión. Los contadores normales se correlacionaron `accepted=completed=driver_delivered=driver_released=staged=delivered=acknowledged=N`, `starts=stops=1`, guards válidos y errores/ignored cero.

La primera aserción de la prueba Qt miraba `getData()` como si fuese el dataset completo; pyqtgraph aplica reducción automática de puntos al render. Se corrigió la sonda para validar `getOriginalDataset()` y verificar separadamente el dataset visible, sin modificar osc.py por esa aserción.

Una captura normal de GUI mostró picos descendentes en **CH39** (mínimo 7615 frente a media 8122,3). Se conservaron PNG y datos. Tras la última recalibración, la repetición final observó CH39 **8101..8125**, media 8112,35, sin esos picos en esa ventana. Esto se registra como observación de señal; las comprobaciones de patrón, rampa de calibración, framing y ownership no acreditan por sí solas fidelidad analógica normal. El handoff excluye el diagnóstico independiente de CH39 de esta implementación; no se declaró resuelto ni se atribuyó una causa.

## Performance por etapa

Baselines aislados:

- TCP sintético placa → daphne-dev, 128 MiB validados: **104,56 MB/s**.
- Escritura en home de daphne-dev, 256 MiB sintéticos con flush+fsync: **38,41 MB/s**. Se retiró sólo el archivo temporal generado.
- Disco verificado antes de N100000: 97 GiB libres; 12,8 GB de payload caben con margen.

Sesiones L32000/P4096/N256, cifras decimales de payload útil y tiempo completo:

| Etapa | Canales | Payload | Tiempo | Caudal |
|---|---:|---:|---:|---:|
| Engine/driver local, sin red | 2 | 32,768 MB | 5,40 s | 6,07 MB/s |
| Engine/driver local, sin red | 40 | 655,36 MB | 12,07 s | 54,28 MB/s |
| Transporte con sink memoria | 2 | 32,768 MB | 5,41 s | 6,06 MB/s |
| Transporte con sink memoria | 40 | 655,36 MB | 15,24 s | 42,99 MB/s |

Copias DDR → userspace de la sonda: 0,227 s (dos canales) y 5,274 s (40). En el cliente: READ RPC 0,672/9,334 s y validación/decoder 0,165/2,225 s. En el servidor de la corrida de red, copia a staging 0,231/5,442 s. Los tiempos se solapan; no sumarlos como etapas seriales ni llamar READ RPC exclusivamente tiempo de red.

La instrumentación `capture_delivery_seconds`/`capture_read_ack_s` incluye las esperas del driver: el último GET puede quedar retenido durante su parada final. `final_drain_close_seconds` mide sólo el remanente después de recibir el último payload; su valor pequeño no demuestra una parada hardware rápida. El N=1 de tres rutas tardó 3,89 s y el cierre GUI activo 3,94 s, coherentes con el coste heredado del proveedor. No hay STOP/reset por waveform en las sesiones normales.

## Campaña N100000 con disco

**PASS**: una sesión con canales 0/1, L32000/P4096, chunk16, timeout total 2400000 ms y watchdog CLI 2460 s. Tiempo de cliente **1606,554 s** (26 min 46,6 s), **62,25 eventos/s**, **7,97 MB/s útiles** con guardado real. PREPARE/START se ejecuta una vez; el chunk no inicia sesiones nuevas.

Se validó con memoria acotada todo el JSONL: 100000 IDs ordenados de sesión 27, slots y generaciones hasta 12500, ventanas L/P/fence, máscaras, valid_bytes y offsets de archivos. Cada archivo contiene **3200000000 muestras u16 LE / 6400000000 bytes**. Rango ADC14: canal 0=8172..8239, media 8202,516; canal 1=8180..8245, media 8208,099.

- Canal 0 SHA256: `5411f54f55c7e25000173fd8e4fdb5da2bc6c9bda7640d78ad8361fc050d0483`.
- Canal 1 SHA256: `7708eaf66931267f5d7699d8679c4fca2ff0c4f8677bdd908f74a472874e3730`.

Final: target/accepted/completed/driver_delivered/driver_released/staged/delivered/acknowledged **100000**, starts=stops=1, guards válidos, hardware_error/error/ignored=0. Hubo **99999 pausas/segmentos**: el productor está limitado por el ciclo de crédito/polling y no se presenta como ADC continuo entre eventos. Reserva DMA de la sesión: **266240 bytes**, independiente de N.

Tiempo acumulado de copia a staging 90,283 s; READ RPC 265,214 s; validación/decoder 64,351 s; escritura/flush del cliente 41,520 s. Estos tiempos se solapan con producción. La CLI hace flush sin fsync por lote; al terminar se ejecutó fsync de los dos archivos completos, medido separadamente en 0,00105 s (writeback ya efectuado).

Muestreo de recursos: servidor RSS **22364 KiB constante** en 1503 muestras; cliente **45456..47996 KiB** en 1533 muestras. CMA libre del servidor **219308 KiB constante** en ese intervalo. CPU de sistema promedio 2,39% en la placa de cuatro cores y 2,48% en la VM cliente de 16 cores; se conservaron porcentajes por core. Son counters del sistema, no CPU exclusiva del proceso; incluyen actividad breve de empaquetado/transferencia. El muestreo comenzó después de los primeros segundos de la corrida.

Después del ACK final se comprobó el estado vivo: **driver IDLE, allocated_bytes=0, hardware_error=0, tres SR HALTED y CR RUN/RESET=0**. El `allocated_bytes` del resultado de sesión conserva la reserva anterior al cierre, no una asignación viva pendiente. La consulta de capacidades y el readback final confirmaron VGAIN 1700 y frontend alineado.

## Comandos de cliente reproducibles

En daphne-dev:

```bash
cd /home/ecristal/daphne-tests/persistent-20261011/server-client-final-134e588
export DAPHNE_PROTO_PYTHON_DIR="$PWD/../server-arm-artifacts/protobuf"
../venv/bin/python scripts/validation/probe_dma_session_caps.py --require-persistent
../venv/bin/python scripts/validation/run_dma_session_network_campaign.py --output ../network-release-20261012
QT_QPA_PLATFORM=offscreen ../venv/bin/python scripts/validation/probe_dma_session_osc.py --output ../osc-release-20261012
```

CLI usado para N100000:

```bash
timeout 2460s ../venv/bin/python daphne-server/client/protobuf_acquire_list_channels.py \
  -ip 193.206.157.36 -port 40001 --dma --capture-mode persistent \
  -trigger_source software --pretrigger 4096 -L 32000 -N 100000 -chunk 16 \
  -channel_list 0,1 -foldername ../persistent-100000-disk-20261012 \
  --timeout_ms 10000 --job-timeout-ms 2400000
```

GUI interactiva equivalente al ensayo (quitar offscreen si existe display):

```bash
../venv/bin/python daphne-server/client/osc.py -ip 193.206.157.36 -port 40001 \
  --dma --capture-mode persistent -trigger_source software --pretrigger 4096 \
  -L 32000 --channels 39,0,17 --max_waveforms 37 -period_ms 100 \
  -timeout_ms 10000 --trigger-timeout-ms 30000 --save_dir ../osc-user-run
```

## Recuperación y límites

Backup efectivo `/home/petalinux/dma-persistent-stage-20261011/backup-20261012`, boot `029d9f6e-d17f-46fc-a177-f03e7754f6ee`, contiene unidades/runtime, productos anteriores y evidencia de quiescencia. Los binarios previos al refresco de admisión también se conservaron. `raw_dma_session_activate.py restore-baseline` está preparado para esa sesión/boot: detiene el propietario, exige prueba de reposo y restaura el runtime anterior; después hay que configurar y medir alineación nuevamente. **No se ejecutó restore**, porque se deja la implementación nueva preparada.

UART continúa registrando en daphne-JTAG-server, `/home/ecristal/daphne-tests/persistent-20261011/uart`; interfaz de consola `if01`, 115200 8N1. XSDB/hw_server enumeró los cuatro A53 sin halt/reset antes del cambio. La recuperación JTAG no fue necesaria y no se probaron resets/flasheos durante estos ensayos.

Pendientes expresos: external/timing con estímulos controlados; regresión física spybuffer en su imagen correspondiente (la imagen raw-dma no expone ese backend); diagnóstico independiente CH39; mejoras/aceptación CDC e IRQ. Spybuffer/defaults mantienen sus pruebas offline y no se modificó el perfil de arranque. Polling a HZ250 y parada del proveedor siguen limitando el caudal; el 80% del plan anterior no era un umbral aprobado ni se declara alcanzado.
