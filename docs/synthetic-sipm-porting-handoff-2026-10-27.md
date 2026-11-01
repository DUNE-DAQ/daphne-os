# Handoff: portar el generador sintético SiPM a otra FPGA

Fecha: 2026-10-27. Objetivo: reutilizar el generador FBK/HPK y su control software,
adaptando solamente las interfaces y los recursos de la FPGA de destino.
La referencia implementada es de un canal; la FPGA de destino todavía no está especificada.

## Punto de partida reproducible

Firmware de referencia: `daphne-firmware`, commit
`1d54239840a0c30da563ea60514a22a09b59f5ac`, rama histórica
`test/synthetic_sipm_generator`. Incluye las correcciones de empaquetado,
constraints, IDELAYCTRL y compatibilidad VHDL-93 del mux de spy buffers.
Commits de desarrollo: `dae4704` (perfil AFE0), `b4cb920` (núcleo),
`c6e908b` (integración y registros), `1d54239` (correcciones de compilación).

Software de referencia: `daphne-os`, commit
`7da6fd8d504c84d82cd591d9e5878cc2a0858df6`.
Los commits `ec9d186` y `083aedb` introdujeron los RPCs y el cliente sintético.
Ruta del servidor dentro del repositorio: `daphne-server/`.

El paquete adjunto contiene selecciones de fuentes extraídas de esos commits
con `git show`, no copias del árbol de trabajo. `MANIFEST.json` registra origen,
revisión y SHA-256 de cada recurso. Los repositorios actuales tienen trabajo
DMA y otros cambios pendientes; no mezclar ese trabajo con este port.
Las rutas que siguen son relativas a `firmware/` o `software/` dentro del ZIP.

El ZIP es un kit de portabilidad, no un checkout completo de DAPHNE ni un
bitstream. Los wrappers de placa, handlers completos y scripts de build de
referencia documentan la integración; para construir todo DAPHNE se necesita
el repositorio completo y sus dependencias. No contiene binarios cualificados.

## Núcleo mínimo de firmware

Compilar en este orden, como **VHDL-2008**:

1. `rtl/isolated/subsystems/synthetic/synthetic_sipm_coefficients_pkg.vhd`:
   coeficientes FBK/HPK cuantizados, tipos y redondeo con saturación.
2. `rtl/isolated/subsystems/synthetic/synthetic_sipm_sos.vhd`:
   una sección IIR de segundo orden en forma directa I.
3. `rtl/isolated/subsystems/synthetic/synthetic_sipm_generator.vhd`:
   excitación, sincronización de configuración, tres SOS y suma al ADC.

Estos tres archivos usan lógica aritmética IEEE; no instancian primitivas
Xilinx, SERDES, BRAM ni procesador. La indicación `use_dsp="yes"` en los productos
es específica de herramientas Xilinx: comprobar su inferencia, sustituirla o
retirarla según la herramienta del destino.

Interfaz de `synthetic_sipm_generator`:

| Puerto | Dirección/ancho | Contrato |
|---|---|---|
| `clock_i` | entrada, 1 bit | reloj de muestras de 62,5 MHz |
| `resetn_i` | entrada, 1 bit | reset activo bajo; liberación sincronizada internamente |
| `config_i` | entrada, 24 bits | palabra de configuración asíncrona; protocolo descrito abajo |
| `software_trigger_i` | entrada, 1 bit | ya sincronizado a `clock_i`; evento en flanco ascendente |
| `sample_i` | entrada, 16 bits | ADC unsigned de 14 bits en [15:2], bits [1:0] auxiliares |
| `sample_o` | salida, 16 bits | ADC más señal sintética, saturado; [1:0] preservados |

No existe `synthetic_sample_o`, `busy`, status ni FIFO dentro del núcleo.
Puede probarse sin ADC físico alimentando una muestra constante que represente
el pedestal. Para otro formato ADC, adaptar empaquetado, signo, pedestal y límites.

El cuarto archivo, `synthetic_sipm_injection_plane.vhd`, es un **adaptador DAPHNE**:
usa `array_5x9x16_type` de `ip_repo/daphne_ip/rtl/daphne_package.vhd`;
modifica AFE0 CH0 y deja intactos los demás canales y la lane de frame.
No es necesario portar ese array: se puede instanciar el núcleo de tres archivos
directamente sobre el canal de destino.

## Modelo numérico y semántica que deben preservarse

- Frecuencia de los coeficientes digitales: **62,5 MHz**, periodo 16 ns.
  Los cuatro CSV originales están en `tests/data/synthetic_sipm/`.
  Ya están normalizados. `tf2sos` descompone la transferencia; no cambia su
  frecuencia de muestreo ni convierte automáticamente los CSV a otra frecuencia.
- Tres SOS; coeficientes signed de 26 bits con 24 bits fraccionarios;
  muestras/historia signed de 48 bits con 28 fraccionarios;
  productos de 74 bits, acumuladores de 77 bits. La realimentación resta
  `a1*y1 + a2*y2`. Conservar los signos, el orden y la cuantización del paquete.
- Amplitud de excitación U14.8: 1..10000, incluyendo 8, 15 y 22,5;
  resolución 1/256 de unidad ADC. Es la amplitud del impulso de entrada al
  filtro, no una promesa de pico final en el ADC. La saturación y el pedestal
  pueden limitar la salida.
- Cada flanco ascendente del trigger produce **una sola muestra de excitación**.
  Un trigger mantenido alto no repite pulsos. La historia se conserva entre
  eventos: el pileup se acepta, sin esperar a que la señal vuelva a cero.
- Deshabilitar borra la historia de las SOS y hace bypass. La historia del
  trigger sigue avanzando para no reproducir un evento al habilitar con trigger alto.
  Los parámetros se capturan solamente mientras está deshabilitado.
- Primer aporte sintético no nulo: tres clocks de adquisición, 48 ns desde el
  flanco de trigger **ya sincronizado**. La muestra física no recibe ese retardo:
  la salida suma la contribución sintética a la muestra física del ciclo actual.
- Redondeo y saturación del estado, y saturación ADC final a 0..16383.
  Conservar los bits bajos de la muestra incluso en saturación.
- No se implementaron trenes autónomos, ruido Poisson, dark counts ni cósmicos.
  Son extensiones futuras, no requisitos implícitos de este port mínimo.

Si el reloj de destino es distinto, obtener/recalcular un modelo válido para
esa frecuencia y volver a validar estabilidad, forma temporal y error.
Otra opción de diseño es un clock-enable de muestras a 62,5 MHz con adaptación
coherente de todos los estados. **No usar `run_i` como clock-enable**: en la SOS,
`run_i=0` borra el estado, no lo congela. No insertar registros arbitrarios en
la realimentación: se alteraría la función de transferencia.

## Integración en la nueva FPGA

Conectar una sola ruta compartida:

```text
ADC / muestra de pedestal -> generador -> muestra modificada -> captura / trigger
                                     ^
                         registro config + evento software sincronizado
```

La inserción de referencia está después de deserializar y antes de bifurcar
hacia spy buffers y selftrigger. Así ambos observan la misma señal. No conectar
el trigger de excitación a la salida del selftrigger: crearía una realimentación.
El selector/inhibit de captura spy no debe inhibir la excitación sintética.

El perfil reducido AFE0 de DAPHNE es una opción de recursos, **no una dependencia
del generador**. No hace falta eliminar otros canales para portar el núcleo.
El SPI y los relojes compartidos del diseño original no apagan físicamente los
AFE deshabilitados. Si se eliminan canales en el destino, fijar a valores
definidos las señales consumidas y mantener respuestas de bus válidas.

Adaptaciones pendientes que debe resolver el hilo receptor antes de cerrar RTL:
parte exacta de FPGA, herramienta/versión, reloj disponible, formato ADC,
canal de inserción, presupuesto DSP/LUT, transporte de control y mapa de direcciones.
Si no dispone de CPU o AXI, basta un registro de 24 bits y un mecanismo fiable
de evento software. Evitar perder un pulso estrecho al cruzar dominios; emplear
el mecanismo CDC adecuado y garantizar un nivel bajo entre eventos.

## Registro y CDC

Referencia: `ip_repo/daphne_ip/rtl/config/stuff.vhd`, `SYN_CONFIG` en offset
`0x50` del bloque STUFF, dirección física original **0x94000050**.

| Bits | Campo | Valor |
|---|---|---|
| 21:0 | amplitud | `amplitude_q8 = round(A*256)`, válido 256..2560000 |
| 22 | modelo | 0 FBK, 1 HPK |
| 23 | enable | 0 bypass/borrado, 1 aceptar eventos |
| 31:24 | reservados | escritura ignorada, lectura cero |

Reset: `0x00000100` (FBK, A=1, deshabilitado). En STUFF las escrituras requieren
`WSTRB=1111`. No hay `SYN_STATUS`, máscara de canales, APPLY ni ACK de aplicación.
En el perfil original sin generador la dirección lee cero e ignora escrituras.

El núcleo sincroniza la palabra con dos etapas, pero el bus multibit requiere
**estabilidad por protocolo software**. No es un handshake atómico general:

1. Leer la configuración anterior; quitar enable conservando sus parámetros.
2. Esperar al menos 80 ns con el reloj de adquisición funcionando.
3. Escribir amplitud/modelo nuevos con enable=0; esperar al menos 80 ns.
4. Si se solicita habilitar, escribir los mismos parámetros con enable=1;
   esperar al menos 80 ns antes de disparar.

El servidor usa readback y una espera conservadora de **1 us por escritura**.
Readback verifica el registro del bus, no confirma aplicación en el dominio ADC.
Recalcular el margen CDC si se cambia el reloj. No editar parámetros en ejecución.
Cada llamada de configuración, incluso con valores idénticos, borra la historia.

Ejemplos: FBK A=22,5 deshabilitado `0x00001680`, habilitado `0x00801680`;
HPK deshabilitado `0x00401680`, habilitado `0x00C01680`.

Trigger software original: registro físico **0x88000008**, escritura `0xBABA`
a través de `FrontEnd::doTrigger()`, convertido por el frontend al evento
sincronizado. Ver los wrappers frontend y `FrontEnd.cpp` incluidos como referencia.
No asumir que escribir 1 a cualquier registro produzca ese evento. Las direcciones
son las de DAPHNE K26; remapear explícitamente en otro sistema. En `FpgaReg`,
el diccionario usa offsets y una base 0x80000000; el controlador sintético usa
direcciones físicas completas a través de `Mmio32`.

## Recursos de software incluidos

| Ruta bajo `software/daphne-server/` | Uso |
|---|---|
| `srcs/server_controller/synthetic_sipm.hpp/.cpp` | codificación, validación y secuencia disable/write/enable |
| `srcs/server_controller/gateware.hpp` | interfaz `Mmio32`: `read32(address)` y `write32(address,value)` |
| `srcs/server_controller/devmem_mmio.hpp/.cpp` | backend Linux `/dev/mem`; referencia, sustituible |
| `srcs/server_controller/handlers.cpp` | integración RPC, buscar `MT2_CONFIGURE_SYNTHETIC_SIPM_REQ` |
| `srcs/protobuf/daphneV3_high_level_confs.proto` | mensajes, enums y tipos V2 |
| `srcs/protobuf/daphneV3_low_level_confs.proto` | segunda definición requerida por el loader del cliente |
| `client/synthetic_sipm.py` | CLI configure/read/disable; Decimal con redondeo de empate hacia arriba |
| `client/v2_client.py`, `client/protobuf_loader.py` | transporte ZeroMQ y carga de bindings |
| `tests/synthetic_sipm_tests.cpp` | controlador con MMIO falso, sin placa |
| `tests/test_synthetic_sipm_client.py` | CLI, cuantización, readback y fallos de transporte |
| `docs/synthetic-sipm-generator.md` | contrato software completo |

Para un host distinto, reutilizar el controlador implementando `Mmio32` con
el transporte del destino (PCIe, UART, SPI, bus local, etc.) y remapear las
direcciones. Usar escrituras de 32 bits completas y ordenadas, readback, las
esperas requeridas y exclusión de escritores concurrentes. Ante un error, el
controlador intenta dejar deshabilitado el generador; no restaura enable.
`/dev/mem`, el servidor AArch64, ZeroMQ y protobuf **no son dependencias del RTL**.
Los handlers completos se incluyen como contexto; no son un servidor autónomo
compilable con solamente los archivos seleccionados del ZIP.

RPCs V2: configure 332/333, read 334/335; software trigger 262/263.
Campos configure: `amplitude_q8`, `model`, `enable`. Respuesta:
`success`, `message`, `amplitude_q8`, `model`, `enable`, `raw_register`.
El cliente no dispara ni captura automáticamente. Regenerar los bindings;
no reutilizar módulos protobuf antiguos. Su ruta por defecto es `mezz/0`
y su puerto por defecto es 9876; adaptarlos al servicio de destino.

## Comprobaciones reproducibles del kit

Requiere Python con NumPy/SciPy para la referencia numérica; XSim para HDL.
Ejecutar desde la raíz extraída del kit:

```bash
python firmware/scripts/validation/simulate_synthetic_sipm.py --vectors-only
python firmware/scripts/validation/simulate_synthetic_sipm.py --bin-dir /ruta/Vivado/bin
python firmware/scripts/validation/validate_synthetic_integration.py --bin-dir /ruta/Vivado/bin
python software/daphne-server/tests/test_synthetic_sipm_client.py
cmake -S portable-software-tests -B build/software-tests
cmake --build build/software-tests
ctest --test-dir build/software-tests --output-on-failure
```

La receta CMake mínima añadida al kit compila solamente el controlador y su
test C++17 con Threads; no enlaza I2C, NEON, el servidor ni `/dev/mem`.
Para reconstruir el servidor DAPHNE completo, usar el checkout completo de
`daphne-os` y su `scripts/server/build_native.sh` dentro de la imagen AArch64.

Generación independiente de bindings Python (protoc instalado):

```bash
mkdir -p build/proto
protoc -I software/daphne-server/srcs/protobuf --python_out=build/proto \
  software/daphne-server/srcs/protobuf/daphneV3_high_level_confs.proto \
  software/daphne-server/srcs/protobuf/daphneV3_low_level_confs.proto
export DAPHNE_PROTO_PYTHON_DIR="$PWD/build/proto"
# Requiere pyzmq y un runtime protobuf compatible con protoc.
python software/daphne-server/client/synthetic_sipm.py --ip <IP_DESTINO> \
  configure --amplitude 22.5 --model fbk --enable
python software/daphne-server/client/synthetic_sipm.py --ip <IP_DESTINO> read
python software/daphne-server/client/synthetic_sipm.py --ip <IP_DESTINO> disable
```

La referencia verifica 28.929 palabras de muestra y regenera los coeficientes
desde CSV. Casos: ambos modelos, A=1/8/15/22,5/10000, trigger prolongado,
pileup, saturación, reset, amplitud inválida, disable/rearm. El test de integración
usa AXI a 100 MHz y adquisición a 62,5 MHz y comprueba los canales sin modificar.

Resultados históricos en K26, Vivado 2024.1, núcleo standalone: 36 DSP,
2.433 LUT, 242 registros de fabric, sin BRAM/URAM; WNS +3,556 ns a 16 ns.
Error máximo respecto del pico float a A=22,5: FBK 0,00730%, HPK 0,01907%.
Son referencias, no estimaciones garantizadas para otra FPGA ni validación de
placa nueva. Los 12 productos no triviales de 48x26 pueden necesitar varios
DSP físicos cada uno. No confundir 12 multiplicaciones con 12 DSP.

`firmware/scripts/validation/synthesize_synthetic_sipm.tcl` fija la parte K26:
modificarla para el destino antes de usarlo. Sus excepciones de timing OOC no
sustituyen los constraints CDC/I/O del diseño completo ni una revisión post-route.

## Errores anteriores que no deben repetirse

- `process(all)` requiere VHDL-2008. Los tres módulos del núcleo deben conservar
  ese tipo tanto en el proyecto como en IP-XACT y en la copia exportada al BD.
  Otros archivos heredados DAPHNE se empaquetan como VHDL-93: el mux de
  `spybuffers.vhd` usa una lista explícita de sensibilidad por ese motivo.
  Forzar 2008 a todo en un test puede ocultar un fallo real del paquete.
- El HDL top y `MODEL_NAME` deben coincidir aunque el nombre comercial/VLNV
  del IP sea diferente. Verificar generics y jerarquía elaborada, no solo el wrapper.
- Los paths de constraints cambian al empaquetar en BD. Validar que cada
  búsqueda devuelve el objeto esperado y que el constraint se aplicó.
- IDELAYCTRL, ODDRE1, IBUFDS, SERDES y relojes del frontend son recursos de placa,
  no del núcleo. Elegir primitivas y `SIM_DEVICE` según FPGA y versión de herramienta.
  K26/Vivado 2026.1 requiere IDELAYCTRL `ULTRASCALE_PLUS`; el modelo 2024.1
  admite `ULTRASCALE`. No trasladar uno de esos ajustes ciegamente a otro dispositivo.
- No llevar los cambios DMA pendientes ni hacer cherry-pick masivo del top de
  placa si solamente se necesita este canal sintético.

## Criterio de entrega del port

Cerrar con: selección explícita de FPGA/herramienta/reloj; simulación equivalente
al modelo entero; respuesta temporal FBK/HPK; control de amplitud y modelo con
CDC probado; trigger único y pileup; bypass y saturaciones; consumidores que
observan la misma muestra; recursos reales, DRC y timing post-route; prueba de
configuración/trigger/captura en la placa destino. Identificar las pruebas aún
pendientes y no presentar la validación original K26 como cualificación del port.

## Mensaje para pegar en el hilo receptor

> Implementa el generador sintético SiPM en la FPGA de este hilo usando este
> handoff y el ZIP de recursos. Empieza por los tres archivos VHDL portables,
> conserva FBK/HPK a 62,5 MHz, amplitud U14.8 de 1..10000, un impulso por flanco
> de software trigger y pileup permitido. Adapta el formato ADC, la inserción
> del canal y el control a la plataforma destino. Reutiliza el controlador
> `synthetic_sipm.cpp` o su secuencia si el bus es distinto. Confirma FPGA,
> herramienta, reloj y transporte antes de fijar la integración; verifica el
> estándar VHDL real del IP, los coeficientes, CDC, simulación y timing del destino.
> No importes el frontend K26 ni los cambios DMA pendientes como dependencias.

La creación de este handoff no modifica RTL, software existente, ramas, commits,
servicios ni hardware. La comprobación realizada al preparar el kit se registra
en `VALIDATION.json` dentro de la entrega.
