# Osciloscopio DMA hasta cierre y adquisición forzada

`osc.py --dma` mantiene una sola sesión persistente hasta que el usuario cierre
la ventana. `--max_waveforms 0` es el default; un N positivo conserva el fin
automático. El antiguo `--capture-mode triggered` también selecciona la sesión
persistente en el scope. No se repiten PREPARE/START/STOP por waveform.
El cliente consume y valida todos los eventos entregados, limitando la tasa
de plots para que la interfaz pueda seguir respondiendo.

La ABI vigente exige un objetivo positivo. El cliente representa el modo
sin límite con `UINT64_MAX` anunciado por el servidor; no abre otra sesión
por rollover. Memoria de ring, staging y cliente permanece acotada. Esto es
una sesión abierta de ventanas por trigger; las ventanas no se declaran
adyacentes en el tiempo. Los deadlines de trigger y las comprobaciones físicas
siguen activos. El contrato y JSONL registran `unbounded_session` cuando procede.

`protobuf_acquire_list_channels.py` acepta `--force_acq` y `--force-acq` en DMA,
con N positivo. Negocia soporte antes de abrir archivos, transmite la opción
en finite/triggered/persistent y registra `force_acquisition` en el contrato.
Los controles de hardware, ownership, framing y reposo permanecen activos.

La calibración ya no exige un Configure RPC previo en la cache del servidor.
Tras un scan fallido puede repetirse sin reescribir la configuración analógica.
Se conserva el reporte de fallos y se avisa del uso de `--force_acq` en canales
no verificados. El fallo de CH39 reportado anteriormente no se declara resuelto.

## Validación

- CTest local y ARM: **29/29 PASS**.
- Windows y daphne-dev/Python 3.9: **41 pruebas de loader/clientes/Qt PASS**, incluyendo sesión sin
  límite, cancelación, contador Qt mayor que 2^31 y archivo forzado.
- Helper de transición manual: **4 PASS**.
- Regresión C++: tres scans fallidos consecutivos y un nuevo scan admitidos
  sin Configure RPC, conservando el rechazo normal de adquisición sin aprobación.
- Scope físico en este PC, trigger externo, canales 32..35, L10000/P1024:
  una prueba recibió 724 eventos en 6 s. La comprobación final tras dos scans
  fallidos recibió **525 eventos en 6 s** (87,5 eventos/s), con **un DMA_ACQUIRE
  y un START**, N infinito y ventana aún visible. El último `acquireMs` fue
  2,63 ms; es una muestra de tiempo de lectura, no el periodo de adquisición.
  El cierre retornó inmediatamente y completó la cancelación en **1,297 s**,
  incluyendo la comprobación de driver liberado y motores HALTED del backend.
  El snapshot de progreso del servidor se conserva antes de la cancelación;
  no se usa para afirmar un contador STOP final del caso cancelado.
- Cliente de archivos físico con `--force_acq`, misma geometría, N8: **8/8**,
  **un START/STOP**, guards válidos, 160000 bytes por canal y contrato forzado.
- Dos scans físicos AFE4 limitados a tap511 fallaron por ausencia de eye común
  y se completaron sin Configure entre ellos. Ambos observaron delay original
  **376**, bitslip **10**, no aplicaron timing y lo restauraron. La adquisición
  forzada posterior funcionó. Este test acotado no repite el barrido completo.

La fuente externa no fue controlada por estas pruebas. Los resultados validan
el consumo, la sesión y el cierre, sin cualificar eficiencia de aceptación de
todos los pulsos externos. El staging alcanzó su límite de 16 eventos y hubo
pausas por crédito; omitir plots afecta sólo la visualización.

## Despliegue

Servidor instalado en `/opt/daphne-dma-persistent-manual-20261012/daphneServer`,
SHA256 `61bdf401c915f91c399c978ac60ace3865641e57a7f49cd3069b7a787d7b56c5`.
El helper `~/scripts/daphne-mode` está fijado al nuevo hash. Runtime anterior
preservado en `/home/petalinux/live-scope-stage-20261012`.
El despliegue detuvo el servidor, probó reposo y lo reinició; no descargó el
overlay, no cambió el driver/firmware ni reconfiguró ganancias o DACs.
La cache del servidor se reinició; el hardware analógico se conservó.

Prueba manual desde `daphne-server/`:

```powershell
& $taskPython .\client\osc.py `
  -ip 193.206.157.36 -port 40001 `
  --dma --trigger-source external --pretrigger 1024 `
  -L 10000 --channels 32,33,34,35 `
  --trigger-timeout-ms 30000 -timeout_ms 10000 --force_acq
```

El cierre de la ventana cancela la sesión y espera su limpieza.
