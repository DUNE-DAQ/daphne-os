# VGAIN/bias scan con DMA

`daphne-server/bash_scripts/vgain_scan.sh` admite `--dma` para medir el pedestal,
adquirir los datos de cada punto y volver a calibrar el pedestal durante la
restauración final. Sin esa bandera conserva spybuffer.

Ejemplo desde la raíz de `daphne-os`, en Bash; ajustar conexión y parámetros
analógicos a la sesión del operador:

```bash
bash daphne-server/bash_scripts/vgain_scan.sh \
  -folder scan_dma -vgain_list "[1700,1800,1900]" -bias 0 \
  -channel 0 1 -L 2048 -N 1000 \
  -ip 193.206.157.36 -port 40001 -route mezz/0 \
  --dma --force-acq -trigger_source software
```

El script presenta un resumen y pide confirmación como antes; `--yes` permite
aceptarlo por línea de comandos. `DAPHNE_PYTHON` selecciona el intérprete y
`DAPHNE_PROTO_PYTHON_DIR` los bindings. El frontend debe estar preparado por el
operador; el scan no cambia firmware, arranca servicios ni realiza alineación.

## Opciones y separación de adquisiciones

- `--dma` selecciona DMA para datos y pedestal. Los datos usan `persistent` por
  defecto, con una sesión para las N waveforms de cada punto. El chunk de
  transporte sigue siendo 10, acotado además por las capacidades del servidor.
- `--force-acq` (alias `--force_acq`) es explícito y requiere `--dma`. Se pasa
  tanto a la adquisición de datos como a **todas** las calibraciones del pedestal,
  incluida la restauración. No modifica la política de alineación del servidor.
  Con la política actual, las escrituras analógicas borran su aprobación;
  normalmente se necesita esta bandera para completar el scan DMA.
- `--capture-mode finite|triggered|persistent` afecta solamente a los datos.
  Finite requiere fuente software y pretrigger cero. El pedestal siempre usa
  persistent, 500 waveforms, software y P=0, independientemente de estas opciones.
- `--pretrigger P` selecciona el pretrigger de los datos, con `0 <= P < L`.
- `-trigger_source` conserva el default `external`. DMA admite software, external
  y timing; `all` se rechaza antes de configurar hardware. External/timing
  necesitan sus estímulos y requisitos físicos correspondientes.
- `--trigger-timeout-ms` (default 10000), `--job-timeout-ms` (default 0) y
  `--pressure-timeout-ms` (default 0) afectan solamente a los datos. Se conservan
  los rangos del cliente DMA; presión sólo se admite en persistent y un plazo
  total persistent explícito no puede superar siete días. El pedestal conserva
  su timeout de trigger predeterminado de 30000 ms.
- `--timeout-ms` sigue siendo el timeout de transporte de los clientes.

Por ejemplo, `--dma --force-acq --pretrigger 1024 -trigger_source external`
adquiere los datos alrededor de eventos externos, mientras la calibración usa
disparos software. No hay fallback automático entre DMA y spybuffer.

## Archivos, integridad y reanudación

Se conserva la estructura `vbias_<bias>/vgain_<vgain>/`, con `config.txt`,
`channel_<ch>.dat` y exactamente `N * L * 2` bytes por canal. En DMA el manifiesto
de cada punto incluye también `dma_format.json` y su único
`dma_metadata_*.jsonl`, ambos no vacíos. El manifiesto de la raíz incorpora estos
hashes. Los manifiestos admiten los marcadores de archivo de GNU/Linux y Git Bash.

`scan_metadata.txt` usa versión 2 y guarda backend, modo, force-acq, pretrigger y
plazos, además de los parámetros anteriores. Para reanudar:

```bash
bash daphne-server/bash_scripts/vgain_scan.sh -folder scan_dma --resume
```

La reanudación carga todo desde los metadatos y rechaza opciones que intenten
cambiar el plan. Los metadatos antiguos de versión 1 se interpretan como
spybuffer. Los puntos deben formar una secuencia contigua; se conserva la
política de repetir el último punto potencialmente incompleto y de verificar
los checksums de los puntos retenidos. Un scan completo válido no adquiere ni
restaura otra vez. Si los datos están completos pero faltó terminar la
restauración, se ejecuta solamente esa restauración y la verificación final.

## Interrupción y restauración

Se mantiene la restauración existente: bias=0, TRIM=0, VGAIN=1700 y pedestal=8192,
preservando bias-control. También se intenta tras fallo o SIGINT/SIGTERM/SIGHUP.

Los clientes DMA de archivos y pedestal manejan esas señales cooperativamente:
marcan cancelación, dejan terminar el RPC en vuelo y ejecutan la limpieza DMA.
Así evitan interrumpir una respuesta ZMQ antes de enviar CANCEL. El script espera
al proceso hijo antes de empezar la restauración. No es una parada instantánea:
depende de los timeouts de transporte y limpieza. Los errores de restauración
quedan en `default_restore.log` y en el estado del scan.

Validación local: ejecución Bash con clientes simulados para las opciones,
checksums, metadatos antiguos/nuevos, fallos, reanudación e interrupción; pruebas
del adaptador DMA para la cancelación diferida. No se ha ejecutado un scan físico
como parte de esta modificación.
