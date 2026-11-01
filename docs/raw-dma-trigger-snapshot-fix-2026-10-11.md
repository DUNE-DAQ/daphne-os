# Verificación del fallo de osc.py y latencia de DMA triggered

## Resultado

El servidor corregido está instalado y activo en la sesión manual de daphne-10.
El cliente osc.py del PC adquirió y dibujó dos eventos reales de CH0/CH1 con
L=2048, P=1024 y fuente software. La lentitud de entrega permanece pendiente
como T6; esta corrección no modifica el proveedor kernel ni el firmware.

La identidad observada en esta prueba fue build 0x01d17a11, ABI 0x20000,
capabilities 0x570 y protocolo 2. Estos valores identifican el ensayo; el cliente
negocia capacidades y no queda ligado a esa revisión de firmware.

## Causa del gráfico vacío

El servidor rechazaba las capturas con `Triggered DMA stream bytes/beats/halt
mismatch`. El consumidor conserva los contadores y registros del monitor
muestreados antes de halt/reset, aunque publica COMPLETE después de comprobar
la barrera DDR y terminar los motores. La validación C++ exigía HALTED/RUN=0
en ese snapshot retenido y rechazaba datos correctos.

El registro de la ruta activa era DMASR=0x11008 (IDLE) y DMACR=0x14013
(RUN y CYCLIC), sin errores DMA. Ahora se acepta un snapshot completado IDLE
sin RESET, o uno ya detenido HALTED sin RUN/RESET. Se mantienen la comprobación
de COMPLETE/DONE, errores, guards, geometría, conteos e índices. La comprobación
final de reposo usa estado vivo después de ABORT; no se sustituye por el snapshot.

Además, osc.py detiene la adquisición DMA y conserva el error visible cuando
falla una captura, en lugar de volver a intentarla automáticamente y sobrescribir
el mensaje con `Capturing`. El camino spybuffer conserva su comportamiento.

Cambios separados: `c896e7f` (validador y pruebas), `4d3810a` (GUI y pruebas).
Compilación Release ARM aprobada; CTest `afe_trigger_unit` y `dma_service_unit`
2/2; pruebas Qt de cliente 6/6.

## Pruebas físicas del servidor y cliente corregidos

| Prueba | Resultado |
|---|---|
| Finite software, CH0/1, L=2048, N=1 | PASS, 0,078 s |
| Triggered software, CH0/1, L=2048, P=1024, N=1 | PASS, 1,406 s |
| Triggered software, CH0/1, L=65536, P=8192, N=1 | PASS, 1,500 s |
| Triggered software, CH0, L=2048, P=0, N=2 | PASS, 2,703 s por lote |
| Triggered software, 40 canales, L=65536, P=8192, N=2 | PASS, 10,282 s por lote, incluido transporte/lectura |
| Cancelar un lote triggered en curso | PASS, limpieza 1,406 s; captura finita posterior PASS |
| osc.py real en Qt offscreen, CH0/1, L=2048, P=1024, N=2 | PASS, dos eventos adquiridos y renderizados; cierre del worker confirmado |

La GUI recibió 2048 puntos por curva, con x[1024]=0. Baselines del último
evento: CH0 media 8193,05, RMS 2,12 cuentas; CH1 media 8207,86, RMS 2,15.
Se inspeccionaron las imágenes de la GUI con las dos curvas visibles.
La prueba verifica adquisición y dibujo, no una señal analógica inyectada.

El usuario informó además una ejecución de `protobuf_acquire_list_channels.py`
con N=1000, L=2048, P=1024, CH0/1 y chunk=10: recibió 1000/1000 en 22:23,
aproximadamente 1,34 s por waveform. No se repitió esa adquisición larga.

Evidencia local regenerable en `build/dma-trigger-diagnostic/`:
`capture_probe.py`, `server_closure_probe.py`, `server-closure.json`,
`osc_live_probe.py`, `osc-live.json` y capturas PNG. La prueba directa C++
anterior queda en `/tmp/dma-trigger-server-review-20261011/engine-probe.log`
en la placa.

## Configuración y sesión conservada

Durante el despliegue se reaplicaron los parámetros indicados por el usuario:
vgain=1700, ch_offset=2275, lpf_cutoff=10, PGA clamp=-2 dBFS, PGA gain=24 dB,
LNA gain=12 dB, LNA input clamp=1.15 Vpp, adc_resolution=0 y biasctrl-dac=1300,
mediante `configure_fe_min_v2.py --dma --skip-alignment`, ruta mezz/0.

El barrido de cinco AFEs con 2048 muestras falló en la verificación física final;
no se marcó ese ensayo como alineación aprobada. En la sesión posterior a la
adquisición comunicada por el usuario, capabilities informó los cinco AFEs
ALIGNED, máscara aprobada 0xff y generación 4. Las pruebas anteriores usaron
esa sesión sin reconfigurar ni modificar taps/slips. No se diagnostica CH39.

Servicio activo: `daphne-dma-manual.service`; ejecutables en
`/opt/daphne-dma-trigger-manual-20261011/`. Se conservaron los binarios anteriores
con sufijo `.pre-snapshot-fix`. No se modificaron firmware, módulos, unidades ni
perfil de arranque. Las copias ARM del PC en `build/dma-trigger-arm64/` coinciden
con los ejecutables instalados:

```text
daphneServer: 1b38fe32f0dacaab52157a87a809d697ce931dac39b1543cba85572c841e5d64
daphne-afe-dma-quiesce: 7d516137d6e53a9a9eb1b98c37f2e1f87ac410afc827b53003fa128a83ad6434
```

## Por qué tarda 1,34 s por waveform

El proveedor cíclico cualificado intenta detener cada ruta antes del reset.
Su polling atómico de RUNSTOP/HALTED agota una espera nominal de 1.000.000 µs
por ruta; en la placa, la entrega directa C++ midió aproximadamente 1,31 s para
una ruta y 3,94 s para tres. Esas mediciones no incluyen protobuf ni red.
CH0/1 ocupan una sola ruta. Las tres rutas se terminan secuencialmente.

Esto coincide con el diagnóstico del proveedor en el
informe físico del firmware (`docs/afe-dma-trigger-1d17a11-board-test-2026-10-11.md`
del repositorio hermano `daphne-firmware`)
y la etapa T6 del
plan de integración (`docs/daphne-os-trigger-pretrigger-integration-instructions.md`
de ese repositorio). Son referencias externas a este checkout OS.
La atribución dominante a stop/reset se apoya en código, logs y tiempos;
no se ha realizado un perfil por función en este ensayo.

L=2048 representa una ventana de 32,768 µs a 62,5 MS/s; no explica un segundo
de entrega. Reducir L o aumentar chunk no suprime la terminación por evento:
chunk agrupa un lote, cada waveform conserva ARM/evento/parada/copia.
Los timeouts son límites máximos y no una pausa programada de 30 s.

T6 requiere optimizar y cualificar la terminación cíclica conservando la barrera
DDR antes de parar, la prueba de HALTED/RUN/RESET y la cuarentena ante fallo.
No se ha aplicado esa optimización. También permanecen pendientes la
cualificación física controlada de external/timing y la parte de T5 de timeout
de trigger y regresión spybuffer con cambio de sesión. No se recargó gateware
para esos ensayos durante la resolución del gráfico vacío.
