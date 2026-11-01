# Calibración de pedestal mediante DMA

`protobuf_configure_pedestal_level.py --dma` mide el pedestal mediante una sesión
DMA persistente de **500 waveforms por medición**, con fuente software y
pretrigger cero. Sin `--dma` conserva el camino spybuffer.

Ejemplo desde la raíz de `daphne-os` en PowerShell; ajustar IP y puerto a la
sesión del operador:

```powershell
python .\daphne-server\client\protobuf_configure_pedestal_level.py `
  -ip 193.206.157.36 -port 40001 -route mezz/0 `
  --dma --force-acq `
  -channel 0 1 --use-current-offset `
  -target_pedestal 8192 -method regula_falsi --auto `
  -L 2048 --timeout-ms 30000
```

## Contrato y compatibilidad

- Requiere numpy, bindings DMA actualizados y servidor/driver/firmware que
  anuncien sesiones persistentes de protocolo 3. No hay fallback a spybuffer,
  finite ni triggered. `DAPHNE_PROTO_PYTHON_DIR` permite seleccionar los bindings.
- `--force-acq` (alias `--force_acq`) requiere `--dma` y se transmite en **cada
  sesión de medición**, incluidas las nuevas mediciones después de escribir
  OFFSET. Su soporte se negocia antes de escribir OFFSET y el servidor debe
  confirmar su aceptación. Sin la bandera se conserva la admisión normal.
- La bandera permite medir sin aprobación de alineación almacenada. No concede
  aprobación ni modifica la política del servidor; conserva las comprobaciones
  físicas y de integridad de `DmaClient`.
- El cliente comprueba capacidades, geometría y soporte de 500 eventos antes de
  ajustar OFFSET. En DMA no envía operaciones de trigger ni dump de spybuffer.
- `--timeout-ms` sigue siendo el timeout del transporte RPC. La sesión usa el
  timeout de trigger predeterminado del adaptador DMA (30000 ms), sin plazo
  total explícito y con la renovación de lease del adaptador.

## Estimador y ciclo de vida

Se conservan los algoritmos regula falsi/bisección, el modo automático, la opción
de partir de los OFFSET actuales y la verificación final por lectura.

El estimador sigue siendo la **moda de la waveform media** de las 500 waveforms,
por canal. Acumula sumas enteras de 64 bits por muestra entre lotes y divide
después de encontrar la moda; los empates eligen la suma menor. No promedia
pedestales calculados por lote. El adaptador DMA convierte RAW16 a ADC14 offset
binary una sola vez, antes de esta reducción.

Cada medición abre una sesión con objetivo 500, lee lotes acotados por las
capacidades y por 48 MiB de datos decodificados, procesa antes de ACK y finaliza
la sesión antes de devolver el pedestal. Además de los datos del lote, retiene
un acumulador de `8 * canales * muestras` bytes y temporales de reducción;
no almacena las 500 waveforms completas. No escribe OFFSET con una sesión activa.
Ante error o interrupción Python cancela la sesión; un fallo de limpieza se
informa y aborta la calibración.

## Alcance y validación

La integración de estas opciones en `bash_scripts/vgain_scan.sh` y su
restauración final es un paso posterior. Esta modificación no cambia scripts de
scan, servidor, protobuf, driver ni firmware.

Pruebas offline: estimador con lotes desiguales y último lote parcial, 500
eventos, orden de canales entre rutas, decodificación ADC, propagación y
confirmación de force-acq, cierre entre mediciones, rechazo de datos corruptos,
cancelación, negociación antes de escrituras y regresión de spybuffer.
El 2026-11-01 el usuario confirmó que la calibración funciona en su prueba.
No se registraron aquí parámetros ni métricas de esa ejecución; no equivale a
una campaña física completa realizada por el agente.
