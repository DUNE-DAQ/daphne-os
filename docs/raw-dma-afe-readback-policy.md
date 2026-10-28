# Politica de readback AFE en raw-DMA

El servidor permite elegir como tratar discrepancias entre el valor esperado
y el valor leido por SPI de cualquier AFE. No contiene excepciones por numero
de placa, AFE o canal.

## Activacion

El comportamiento predeterminado sigue siendo estricto:

```bash
daphneServer --dma --gateware-mode raw-dma \
  --expected-gateware-build-id 0x0630a9da --bind 'tcp://*:40001' \
  --dma-afe-readback-policy strict
```

Para una sesion que tolere discrepancias de readback:

```bash
daphneServer --dma --gateware-mode raw-dma \
  --expected-gateware-build-id 0x0630a9da --bind 'tcp://*:40001' \
  --dma-afe-readback-policy warn
```

Estos ejemplos requieren la preparacion habitual del firmware, proveedores y
consumidor DMA, librerias y permisos del servidor. No ejecutar un segundo
servidor sobre el mismo hardware. El selector local debe mantener el retorno
al servidor anterior; la opcion no instala ni selecciona firmware o drivers.

La opcion `warn` se rechaza en modos distintos de raw-DMA antes de inicializar
hardware. Una politica desconocida tambien se rechaza. Omitir la opcion
equivale a `strict`.

## Alcance

En modo `warn` se registran discrepancias con el AFE logico, el campo, el valor
esperado y el leido. Se toleran exclusivamente comparaciones de valores SPI:

- Configuracion del AFE, incluida la comprobacion inmediata de ganancia PGA.
- Comprobacion del formato y estado ADC previa a adquisicion DMA finita,
  triggered o persistente y previa al barrido de alineacion.
- Escritura y restauracion de patrones ADC durante el barrido de ojo DMA.

Un fallo de formato ya no impide continuar con la configuracion solicitada,
pero el servidor no garantiza mediante readback que el ADC la haya aceptado.
No se ocultan excepciones de SPI, timeouts, fallos de identificacion del
gateware, relojes, powerstate FPGA, IDELAY, controles de timing FPGA,
geometria DMA, ownership, cancelacion o cuarentena.

Tolerar readback no aprueba lanes ni crea una alineacion. El barrido conserva
el analisis fisico de la rampa y su verificacion final. Un AFE sin ojo valido
sigue sin estar alineado. El operador puede usar los mecanismos existentes
de adquisicion forzada o de omision de la verificacion final cuando proceda;
no se activan automaticamente al seleccionar `warn`.

## Respuestas y clientes

No hay cambios en el protocolo protobuf. La politica se selecciona al iniciar
el servidor y las respuestas incluyen un aviso al principio de `message`:

```text
WARNING: DMA AFE readback policy=warn; ADC SPI value mismatches are tolerated; AFE register configuration is not guaranteed by readback.
```

El aviso aparece en configuracion, capabilities, estado del job, fragmentos y
resultado del barrido. Configuracion y barrido incluyen ademas los detalles
de las discrepancias observadas. Los logs del guard de adquisicion deduplican
y limitan esos detalles para evitar un mensaje por cada waveform.

El cliente de configuracion conserva sus comprobaciones de `success`,
`configured` y backend. El servidor solo devuelve configuracion satisfactoria
si el resto de la operacion termina correctamente. El cliente DMA actualizado
muestra el aviso una vez por instancia y anade a los metadatos de capturas
finitas, triggered y persistentes:

```json
{
  "afe_readback_policy": "warn",
  "afe_register_configuration_verified": false,
  "afe_readback_warning": "WARNING: DMA AFE readback policy=warn; ..."
}
```

La marca es conservadora para toda captura hecha con `warn`, incluso cuando
no se observaron discrepancias. Los clientes anteriores pueden comunicarse
sin regenerar bindings, pero no anaden estos metadatos ni muestran
automaticamente los avisos en todos los flujos.

## Validacion

Las pruebas de politica inyectan discrepancias en los cinco indices AFE,
comprueban errores de SPI, deduplicacion concurrente y limites de logs.
Las pruebas del servicio comprueban que `warn` permite una captura simulada
solo con el consentimiento explicito existente para adquirir sin alineacion;
`strict` conserva el rechazo y un timeout sigue impidiendo adquirir.
Las pruebas de cliente comprueban avisos, metadatos finitos/persistentes y
rechazo de fragmentos corruptos aun en presencia de un aviso.

Las pruebas CLI comprueban el rechazo de politicas desconocidas y de `warn`
fuera de raw-DMA antes de cualquier inicializacion de hardware. La compilacion
completa del servidor requiere ARM/NEON; las pruebas del servicio sin hardware
tambien se pueden ejecutar en x86. Los ensayos fisicos de cada entrega se
registran por separado y no se deducen del resultado de estas pruebas.

## Ensayo en daphne-10, 2026-10-28

Se compilo nativamente con GCC 13.4.0, kernel
`6.18.10-xilinx-g4f7afe14f724`, y se probaron ambas politicas con firmware
`630a9da`. Los 30 casos de CTest pasaron; hubo omisiones internas de Qt
opcional. Cuatro casos necesitaron repetir la ejecucion despues de completar
los archivos auxiliares del paquete aislado, sin modificar el servidor.

La configuracion de los cinco AFE paso en ambas politicas. Se midio un ojo
acotado nuevo de AFE0 y se verificaron 32768 muestras de rampa en sus ocho
lanes. Se probaron capturas finitas de 2048 muestras en canales 0 y 7 y
sesiones persistentes de dos eventos. No se hizo una calibracion completa de
los otros cuatro AFE.

Para provocar una discrepancia reversible se activo el patron ADC de AFE0:
el guard de captura normal esperaba `TEST_PATTERN_MODES=0` y leyo `7`.
`strict` rechazo la captura; `warn` registro el detalle y permitio transferir
datos con `afe_register_configuration_verified=false` en sus metadatos.
El patron se restauro y las sesiones DMA se cerraron. No se simulo un fallo
fisico del bus SPI; el ensayo verifica una discrepancia real de valores.

Una primera captura sin alineacion fue rechazada por bits de relleno no
nulos; se conservo el error y se midio el ojo antes de repetir. Esto confirma
que la politica permisiva no se extendio a la integridad del formato.

El ensayo uso una copia privada del binario; no sustituyo `/usr/bin/daphneServer`
ni los binarios DMA existentes. Se restauro el perfil predeterminado
`self-trigger` / `e8faa9a`, con el servidor original verificado por hash y un
unico listener en TCP 40001. Se descargaron ambos modulos DMA y se retiraron
los overrides temporales. daphne-4 no se modifico durante este ensayo.
