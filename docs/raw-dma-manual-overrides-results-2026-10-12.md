# DMA: verificación de candidatos y opciones manuales

Se implementaron y desplegaron `scan_afe_delay_eye.py --skip-ramp-verification`
y `osc.py --force_acq` (alias `--force-acq`). Las capacidades anuncian soporte
explícito y el trabajo confirma `force_acquisition`; un servidor anterior se
rechaza antes de usar la opción. El [contrato](raw-dma-persistent-server-client-contract.md)
define sus límites y el registro de datos forzados.

Sin omitir la verificación, se prueban los mejores candidatos de hasta 16
bitslips, por orden de canales admitidos y ancho de ventana, con toda la
longitud solicitada y cero errores por canal admitido. El presupuesto incluye
el peor caso antes de MMIO. Los errores identifican AFE, tap, bitslip y lane.
El scan puede reintentarse después de un fallo sin reescribir configuración;
la adquisición normal conserva su exigencia de alineación aprobada.

## Despliegue

Placa: `193.206.157.36:40001`, boot
`d029e578-9ef3-4921-93e9-9fb1f6c5f7f3`. Servidor activo en
`/opt/daphne-dma-persistent-manual-20261012/daphneServer`, SHA256
`d273defd534d3b3fb5f14d16db4de966f47e8ab05cb6094a366cb729d4bb0698`.
El firmware sigue en `630a9da`, kernel `6.18.10-xilinx-g4f7afe14f724`, sesión
ABI 1/features 31. No cambió la UAPI ni se recompiló el módulo kernel.

Antes de sustituir el servidor se detuvo su unidad y pasó la prueba viva de
reposo. Copias de servidor, bindings, clientes y helper anterior en
`/home/petalinux/manual-overrides-stage-20261012`. El helper de
`~/scripts/daphne-mode` se actualizó al hash nuevo. El perfil de arranque
continuó en `self-trigger`; no se descargó el overlay durante esta actualización.

El reinicio vacía la cache de configuración y VGAIN del servidor. Se reaplicó
la configuración proporcionada por el usuario: VGAIN **3000** en los cinco
AFEs, offset 2275, trim/bias 0, LPF 10 MHz, PGA 24 dB/clamp -2 dBFS,
LNA 12 dB/clamp 1,15 Vpp, ADC14 unsigned y bias-control 1300. La lectura
posterior de VGAIN confirmó 3000 en las cinco entradas de la cache.

Bindings ARM instalados y copiados al PC:

- High-level SHA256 `15821930e35c3468ec484bfd572c9cb2296806e937b7774cdb0aeb0e623cf7de`.
- Low-level SHA256 `da1fbafe0a60208ad80c7f4801c2f18199f21909564d236161922ad0cae1867a`.

## Resultados

- CTest local y ARM: **28/28 PASS**; Qt opcional se verifica por separado.
- PC y daphne-dev/Python 3.9: **26 pruebas de cliente + 8 Qt PASS**.
- Admisión normal de canal 0 sin alineación: rechazo `ALIGNMENT_REQUIRED`.
- Forzada triggered/software: una waveform L2048/P1024, datos ADC14 recibidos.
- Forzada persistent/software: N2/L2048/P1024, todos los contadores en 2,
  un START/STOP, guards válidos y errores cero. Las dos capturas no conceden
  aprobación de alineación al frontend.
- Scan completo con `--skip-ramp-verification`: PASS de la opción; timing
  aplicado en los cinco AFEs y marcado `ramp_verification_skipped`. La cache
  conserva `FRONTEND_CONFIGURED_UNALIGNED`, máscaras de admisión cero.
- `osc.py` forzado con trigger externo, canal 0: ventana visible y una
  waveform adquirida durante la observación. Close retornó inmediatamente y
  la cancelación terminó en **1,328 s**. No se controló ni caracterizó el
  generador externo: esto verifica el recorrido manual, no una cualificación
  temporal de la fuente.
- Prueba final de reposo: driver liberado, los tres motores HALTED; servidor
  permanece activo para adquisición manual con `--force_acq`.

### Fallo físico que permanece

La repetición del comando original con verificación de **1048576 muestras**
y `--accept-partial-config` siguió fallando en **AFE4/lane7 = CH39**.
Los dos candidatos disponibles dieron:

| Bitslip | Tap | Errores delta | Errores low | Errores boundary |
|---|---:|---:|---:|---:|
| 10 | 392 | 26 | 0 | 0 |
| 11 | 80 | 2 | 0 | 0 |

No se declaró resuelto ni se atribuyó una causa. La captura larga rechazó ambos
candidatos y restauró el timing anterior del lote. Las opciones manuales
permiten continuar el experimento con evidencia explícitamente no verificada;
no convierten ese resultado en una validación de CH39.

## Evidencia

En el PC, bajo `build/dma-persistent-transfer/`:

- `manual-overrides-physical-20261012.json`: admisión normal/forzada y contadores.
- `osc-force-external-20261012.json`: GUI, waveform observada y cancelación.
- `manual-overrides-skipped-scan-20261012/dma-eye-20261012-130931-4acc457e/`:
  CSV, JSON y plots del scan con verificación omitida.
- `raw-dma-manual-overrides-final-20261012.tar.gz`: snapshot de fuentes y
  bindings para reproducción; copia en daphne-dev bajo
  `/home/ecristal/daphne-tests/persistent-20261011/manual-overrides-20261012`.

En daphne-10: `manual-overrides-build-20261012.log` y
`manual-overrides-ctest-20261012.log` en `/home/petalinux`.
En daphne-dev: `client-tests.log` y `qt-tests.log` en el directorio del bundle.
Las capturas del usuario en `daphne-server/triggered_test_02/` se conservaron
y se excluyeron de Git como datos del experimento.
