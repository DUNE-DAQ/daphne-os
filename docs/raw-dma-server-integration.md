# Raw DMA en daphneServer: primera integración

## Alcance y compatibilidad

El mismo `daphneServer` admite el backend DMA mediante `--dma --gateware-mode raw-dma`.
El camino spybuffer sigue siendo el predeterminado de los clientes y no se modifican
sus archivos de lectura. El diagnóstico `daphne-dma-diag` continúa separado.

Esta entrega implementa capturas físicas AFE finitas con software trigger:
**N waveforms de L muestras, un START Linux independiente por waveform**.
Los START se emiten en cuanto termina y se libera la captura anterior, sin una
pausa artificial. No se promete adquisición continua, pretrigger ni timestamp
hardware; esos datos se indican expresamente en los metadatos.

El protocolo y los clientes contemplan software, external, timing, self y all.
Por ahora el servidor anuncia únicamente software y rechaza las demás fuentes
antes de START. La espera de un trigger hardware, la ventana de L muestras que
ignora triggers adicionales y el rearme requieren la siguiente versión del
firmware y su validación. No se simulan esas fuentes con START Linux.

La admisión depende de ABI 2.0, variante raw-dma, capability física AFE bit 4,
UAPI AFE ABI 1 y formato raw 1. No se fija un commit de firmware. El build ID
detectado se conserva para trazabilidad y para verificar que no cambia durante
el trabajo. Una restricción adicional de despliegue por build ID es opcional.
Los cinco AFEs y los canales 0–39 reciben el mismo tratamiento.

## Compilación y requisitos

En Linux ARM, con las dependencias de compilación habituales del servidor:

```sh
cmake -S daphne-server -B build/dma-server \
  -DCMAKE_BUILD_TYPE=Release -DDAPHNE_BUILD_DMA_DIAG=ON
cmake --build build/dma-server --parallel 2
ctest --test-dir build/dma-server --output-on-failure
export DAPHNE_PROTO_PYTHON_DIR="$PWD/build/dma-server/srcs/protobuf"
```

CMake genera los protobuf C++ y Python. Usar esos bindings actualizados también
en el PC de los clientes; `DAPHNE_PROTO_PYTHON_DIR` selecciona su directorio.
Los clientes DMA rechazan bindings antiguos sin los RPC necesarios.

La placa necesita el overlay físico AFE DMA cualificado, el proveedor Xilinx
con la modificación de parada acotada y el consumidor que expone
`/dev/daphne-afe-dma`. El firmware de diagnóstico de patrones original no basta
para adquirir AFEs físicos. La preparación del kernel y del device tree está
documentada en [raw-dma-point4-implementation.md](raw-dma-point4-implementation.md) y en los archivos
de `daphne-server/kernel/daphne-afe-dma/`. No sustituirlos por acceso directo a
los registros DMA desde los clientes.

Instalar juntos `daphneServer` y `daphne-afe-dma-quiesce`. El segundo prueba que
los tres canales están detenidos antes de permitir descargar el overlay. El
paquete de runtime debe incluir ambos ejecutables; los bundles antiguos no se
actualizan automáticamente por modificar la receta. El módulo y el firmware
también deben desplegarse y verificarse por separado.

## Perfil de runtime y arranque

El perfil opcional `/etc/daphne-gateware/profiles/raw-dma.conf` requiere ajustar
`APP` al nombre del app instalado y cualificado. Su build ID se obtiene de los
metadatos de ese app. El perfil de arranque predeterminado permanece intacto.
El servicio añade `--dma` solamente para raw-dma; Hermes se omite en ese perfil
para impedir acceso IPBus ajeno al propietario DMA.

Para una sesión manual, una vez verificados el overlay y el módulo y detenidos
los otros propietarios del hardware:

```sh
sudo build/dma-server/daphneServer \
  --dma --gateware-mode raw-dma --bind 'tcp://*:9876'
```

Los ejemplos siguientes usan ese puerto. El servicio empaquetado usa 40001;
ajustar todos los clientes al puerto del servidor elegido. No cargar otro
overlay con el servidor o un trabajo activo. Al detener el servidor se cancela
y recoge su worker; detener solo el servidor conserva el overlay. La descarga
de firmware exige además la prueba de reposo del helper. Un fallo o una
cuarentena impide la descarga automática.

## Primera prueba física, realizada por el operador

Configurar primero, sin el alineamiento legacy:

```sh
python daphne-server/client/configure_fe_min_v2.py \
  -ip 193.206.157.36 -port 9876 --dma --skip-alignment
```

Revisar los parámetros analógicos y de bias antes de ejecutarlo. La respuesta
de configuración DMA indica que aún se requiere alineamiento. Un cliente no
puede declarar un AFE alineado mediante un flag.

Medir y aplicar el ojo físico:

```sh
python daphne-server/client/scan_afe_delay_eye.py \
  --ip 193.206.157.36 --port 9876 --dma --afes 0,1,2,3,4 \
  --samples 2048 --waveforms 1 --coarse-step 16 --tap-step 4 \
  --verification-samples 1048576 --apply-best --summary
```

El scanner recorre los 16 bitslips, busca un ojo común sin errores y refina los
taps usando 2048 muestras por punto por defecto. La verificación final usa
1048576 muestras por defecto (mínimo configurable 32768), para cubrir todos
los bits y detectar errores más raros sin repetir esa longitud en todo el
barrido. Un candidato que falla la verificación se restaura y no queda aprobado. Comprueba rampa
raw de 16 bits, bits bajos y continuidad entre paquetes, incluido el wrap.
Restaura el patrón, sincronización y ajustes temporales cuando corresponde.
`--accept-partial-config` permite explícitamente un subconjunto de lanes;
sin esa opción deben pasar las ocho. El número de paquetes de calibración es
un parámetro metrológico y no sustituye los N triggers de producción.
`--summary` genera JSON, CSV y, si está disponible matplotlib, gráficos de ojo.

Visualizar waveforms largas:

```sh
python daphne-server/client/osc.py \
  -ip 193.206.157.36 -port 9876 --dma --trigger-source software \
  --channels 0,8,16,24,32 -L 32768 -timeout_ms 5000
```

Adquirir exactamente N waveforms a archivos por canal:

```sh
python daphne-server/client/protobuf_acquire_list_channels.py \
  -ip 193.206.157.36 -port 9876 --dma --trigger-source software \
  -channel_list 39,0,17 -N 10 -L 32768 -chunk 5 -foldername dma_run
```

Se conserva el orden de canales solicitado. El transporte utiliza palabras
raw de 16 bits little endian; los archivos `channel_<id>.dat` contienen ADC14
en offset-binary en palabras de 16 bits little endian. Con el AFE configurado
en complemento a dos (`ADC_OUTPUT_FORMAT=0`), el cliente desplaza dos bits,
extrae los 14 bits e invierte su MSB (`^ 0x2000`). Así el cero analógico queda
cerca de 8192, como en el camino spybuffer. También rechaza bits de padding
no nulos. Los archivos anteriores a esta corrección contienen los códigos
en complemento a dos sin normalizar; no mezclarlos con los nuevos al anexar.
Los metadatos JSON registran el backend, build ID y límites de cada waveform.
`dma_format.json` identifica la codificación de los archivos y bloquea append
sobre datos existentes con codificación desconocida.
La FFT de `osc.py` usa todas las L muestras, aunque el dibujo reduzca puntos.
Se negocian capacidades una vez por sesión y STATUS se consulta de inmediato;
solo un trabajo aún activo introduce backoff, de 2 a 20 ms. El protocolo finito
todavía necesita varios viajes de red por waveform, frente al único dump
legacy. Las mejoras no convierten esta entrega en un stream continuo.

## Mensajes y gráficos de los clientes

Los clientes de archivos y de barrido usan el estilo de mensajes spybuffer
para ambos backends: solicitudes, progreso en waveforms, ventanas por canal,
ojo común y aplicación de IDELAY/BITSLIP. Una referencia identifica el backend;
DMA también informa la longitud de su verificación final. Los errores reales
de protocolo, verificación o limpieza conservan su diagnóstico específico.
Esta presentación no modifica la adquisición ni el alineamiento del servidor.

Con `scan_afe_delay_eye.py --dma --summary`, cada AFE produce:

- `afe<id>_delay_eye.png`: errores por canal en el BITSLIP seleccionado,
  tap elegido y tramo medido que pasa alrededor de ese tap.
- `afe_<id>_eye.png`: vista complementaria de los 16 BITSLIPs,
  conservando el nombre anterior del gráfico agregado.
- `summary.json`: incluye `channel_margins`, además de los resultados previos.

El mapa distingue verde (cero errores observados), una escala logarítmica
para errores y gris (tap no medido). La fracción dibujada es la mayor de los
controles de rampa, padding y fronteras, cada uno con su propio denominador.
El CSV conserva todos los contadores separados.

El span es la distancia entre los extremos muestreados del tramo que contiene
el tap elegido. El margen es la distancia al extremo muestreado más cercano;
un margen menor o igual a un paso de scan se resalta en naranja para todos los
canales. Un asterisco indica que el tramo llega al límite de cobertura: no se
conoce su anchura completa. Los taps intermedios no medidos no se califican
como válidos, y este margen no sustituye la verificación final ni demuestra
estabilidad del ADC normal. El diagnóstico o reparación de CH39 queda fuera
de esta mejora de presentación.

## Ciclo de vida y límites

La primera integración limita cada trabajo a 64 MiB y 256 waveforms, con
fragmentos de transporte de hasta 1 MiB que contienen ticks completos. El
cliente de archivos divide N en trabajos acotados; no existe aún un ring de
producción. Cada trabajo pertenece a la identidad del cliente que lo abrió.
Durante una captura los controles de hardware devuelven BUSY.

STATUS, READ, CANCEL, KEEPALIVE y ACK mantienen el servidor receptivo. La lease
es de 30 segundos. Los clientes verifican geometría, secuencia, canal, formato,
build ID y finales de fragmento; ACK se envía después de consumir los datos y,
cuando se guardan, después de escribirlos. Un error o una cancelación intenta
ABORT y prueba de parada; si esta no se confirma, se informa cuarentena y se
conserva el overlay. No se debe recuperar ese estado descargándolo a ciegas.

Un cambio en un AFE invalida su alineamiento. Los cambios globales de reloj,
alimentación y reset invalidan configuración y alineamiento de todos. Una
nueva configuración o un scan no aplicado tampoco habilita capturas sin la
evidencia de alineamiento correspondiente.

## Validación y pasos pendientes

La compilación completa y las pruebas offline se ejecutan tanto en el host
Linux como en daphne-10. La prueba Qt local verifica waveforms de 32769 muestras,
FFT, escritura y ACK con un servidor simulado. Esto no prueba el camino físico.
La siguiente validación en placa debe revisar configuración, ojo de los cinco
AFEs, adquisición en `osc.py`, archivos multicanal, cancelación/desconexión y
regresión del modo spybuffer antes de habilitar el perfil de producción.

La compilación SSH de revisión está aislada en
`/tmp/dma-server-review-20261010/build/`; no reemplaza el checkout ni los
ejecutables instalados. Es almacenamiento temporal y se pierde al reiniciar.
No se han ejecutado capturas, cambios de servicios, insmod ni recargas de PL
como parte de esa validación de compilación.

La investigación física posterior se documenta en
[offset, alineación y latencia DMA](raw-dma-alignment-investigation-2026-10-11.md).
Corrige el formato y reduce esperas de cliente, pero detecta errores
intermitentes de CH39 incluso después de pasar rampas largas. Esa sesión no
cualifica la captura estable de los 40 canales ni habilita producción.
