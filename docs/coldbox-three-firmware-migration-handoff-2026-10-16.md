# Handoff: replicar daphne-10 en una DAPHNE de la Coldbox

## Solicitud y alcance autorizado

El usuario quiere replicar el entorno de daphne-10 en otra DAPHNE destinada a
la Coldbox. No dará acceso directo a esa placa; la instalación la ejecutará
otra persona siguiendo instrucciones en PDF y usando un bundle que se
preparará posteriormente.

**La fase actual es sólo brainstorm y handoff.** El usuario dijo explícitamente:
"No modifiques nada ni crees aun el documento. Solo hagamos brainstorm de
como podemos realizarlo." La petición posterior autoriza crear este handoff
y un hilo dedicado; no autoriza todavía crear el PDF, modificar drivers,
instalar perfiles ni alterar daphne-10. Leer contexto, confirmar la propuesta
y esperar las siguientes instrucciones antes de implementar.

El usuario estima con un 90 % de confianza que la única incompatibilidad del
kernel de la Coldbox será vermagic. Acordamos tomar la adaptación de vermagic
como camino principal condicionado a las comprobaciones del destino, no
tratar esa compatibilidad como una verificación ya realizada.

## Tres perfiles requeridos

| Perfil propuesto | Firmware FPGA | Servidor |
| --- | --- | --- |
| factory / default | El que venga con la Coldbox, aún desconocido | El servidor original de esa placa, aún desconocido |
| self-trigger | El actualmente predeterminado de daphne-10 | Nuestro binario de servidor correspondiente a 7da6fd8, configurado para self-trigger |
| dma | Raw DMA 630a9da de daphne-10 | El mismo binario, configurado para raw-dma y con --dma |

El usuario indica que el servidor actual es compatible con los firmwares 2 y
3. La validación final deberá cubrir los dos modos y sus argumentos; un solo
binario no implica usar los mismos flags. El perfil factory debe preservar su
servidor, configuración y servicios propios. Reservar default para factory,
evitando confundirlo con el predeterminado de daphne-10.

Propuesta debatida: conservar el kernel/Linux de la Coldbox, instalar runtimes
separados y evolucionar el selector a tres perfiles. El arranque original se
mantendría por defecto hasta que el usuario solicite otra política. Esta
arquitectura es una propuesta de diseño, todavía no implementada.

## Estado de referencia verificado en daphne-10 el 2026-10-16

- Endpoint: 193.206.157.36:40001. Alias SSH: daphne-10.
- Perfil activo: raw-dma.
- APP: daphne_selftrigger_ol_630a9da.
- Identidad FPGA: magic 0x44415048, ABI 2.0, variant 3, build 0x0630A9DA.
- Kernel: 6.18.10-xilinx-g4f7afe14f724.
- /etc/daphne-gateware/default-profile: self-trigger.
- daphne-dma-manual.service activo; daphne.service y hermes.service inactivos.
- Binario: /opt/daphne-dma-persistent-manual-20261012/daphneServer.
- SHA256 del binario: 61bdf401c915f91c399c978ac60ace3865641e57a7f49cd3069b7a787d7b56c5.
- Código de servidor/clientes de referencia: commit 7da6fd8. Es la
  correspondencia con las fuentes del despliegue, no un hash Git embebido
  que se haya obtenido del ejecutable.
- Selector: /home/petalinux/scripts/daphne-mode, que invoca mediante sudo
  /usr/local/libexec/daphne-manual-mode.py.
- Acciones actuales: dma, default, defecto (alias de default), status.
- No se comprobó en esta consulta si hay una adquisición activa ni se alteró
  firmware, servicios, configuración analógica o estado de alineación.

El selector actual es específico de dos perfiles y de assets con hashes
fijados. NO debe copiarse sin adaptar a una placa cuyo perfil original,
kernel y entorno de arranque todavía desconocemos.

Al cambiar de default a DMA, ese selector carga el overlay, enlaza los tres
motores al proveedor acotado, carga el consumidor, inicia servicios y ejecuta
frontend prepare/status. Su perfil analógico de preparación usa VGAIN 1700 y
alineación física. Si el perfil DMA ya está activo sólo verifica su estado y
preserva la configuración del experimento. Las pruebas manuales posteriores
del usuario usaron VGAIN 3000; no confundirlo con el perfil de preparación.

## Assets y referencias conocidos

Runtime manual: /opt/daphne-dma-persistent-manual-20261012.

- Consumidor: daphne-afe-dma.ko, SHA256
  d25ab970bb5288e1d419974f63ab92e9427163a34ec68a9d2a3c0f0f5f9a4255.
- Proveedor: daphne_dma_bounded.ko, SHA256
  7d26fcfa954c7ad9b5542087a67c9d29d9e52755896f9a57a65faf6cf0cd89fe.
- Raw-DMA .bin, SHA256
  01a7735f4678e1302ae6534d5ada6c9ea95407ee1cdd29abf10cae69571a623e.
- Raw-DMA DTBO Linux cualificado, SHA256
  3ad11bb16a1718eb0eff6200eb230443ce0a5bcd024eacd0ca4149303e64222d.
- Hay que inventariar y empaquetar también los assets reales del firmware
  self-trigger predeterminado de daphne-10, no sólo su nombre de perfil.

Bundle final existente, sin datos de adquisición:

- Local: build/dma-persistent-transfer/raw-dma-live-scope-committed-20261012.tar.gz.
- SHA256: b9a5cea7807940f6f69052a67f1c7d7bfbea701dfc36b3edf613374c85bd3535.
- daphne-dev: /home/ecristal/daphne-tests/persistent-20261011/live-scope-20261012/.
- daphne-10: /home/petalinux/raw-dma-live-scope-committed-20261012.tar.gz.
- Es un bundle de fuentes y protobufs generados, **no** un instalador completo
  de tres firmwares listo para la Coldbox.

## Compatibilidad del kernel: decisión y límites

Considerar ambos módulos externos, no sólo el consumidor. Necesitamos conocer
el vermagic completo de un módulo propio del destino, arquitectura, release
del kernel, configuración relevante, política de firmas y símbolos/versiones.

Camino preferido por el usuario: adaptar únicamente vermagic en copias de
los módulos, guardar originales y nuevos hashes, y realizar pruebas progresivas
en la Coldbox. Sólo es defendible si el resto de la ABI es compatible. No se
ha hecho ningún parche ni prueba de carga en esa placa.

No sustituir CRCs de símbolos ni eliminar comprobaciones de versiones para
ocultar incompatibilidades. Cargar un módulo no demuestra por sí solo que el
DMA sea correcto. Si aparecen diferencias de ABI, plantear recompilación
contra los artefactos del kernel destino, aunque su imagen no pueda cambiarse.

La compilación anterior de los módulos se hizo en daphne-dev contra el
proyecto PetaLinux que produjo la imagen de daphne-10:
/home/ecristal/daphne/daphne-dual-rc1-work/petalinux-dev.
No compilar el driver nativamente en daphne-10 ni asumir que ese proyecto
PetaLinux corresponde al kernel desconocido de la Coldbox.

Fuentes oficiales consultadas durante el brainstorm:

- https://docs.kernel.org/kbuild/modules.html
  Requiere configuración/headers correspondientes; CONFIG_MODVERSIONS verifica
  CRCs de símbolos y modules_prepare no genera Module.symvers.
- https://docs.kernel.org/admin-guide/module-signing.html
  La política de firmas puede impedir cargar un módulo modificado.

## Otros puntos que el futuro procedimiento debe resolver

1. Inventario de lectura ejecutable por la persona en destino, con un reporte
   que pueda enviarnos sin darnos acceso a la placa. Incluir kernel/config,
   módulos, device tree base y símbolos, firmware/overlays, servicios de arranque,
   bibliotecas del servidor, memoria/CMA, identidad de hardware y red.
2. Respaldo recuperable del firmware y servidor factory, servicios, configuración
   analógica pertinente y política de arranque. Ubicación y nombres desconocidos.
3. Compatibilidad de overlays con el DT base de la Coldbox. El DTBO de daphne-10
   no es automáticamente compatible con otro BSP, aunque el bitstream coincida.
4. Dependencias userspace del servidor (glibc, libstdc++, protobuf, ZeroMQ y
   demás dependencias reales). Evitar sustituir globalmente bibliotecas o
   sobrescribir el servidor factory; considerar dependencias privadas por runtime.
5. Selector con perfiles explícitos y configuración parametrizable, sin fijar
   IPs/rutas/versiones de kernel de daphne-10 para el destino. Reposo DMA y
   ownership antes de descargar overlay, módulos o cambiar enlaces de drivers.
6. Ruta de recuperación disponible a la persona en destino (consola serie,
   acceso físico/JTAG si aplica); no asumir el servidor JTAG del laboratorio
   como recuperación de la Coldbox.
7. Validación de factory -> self-trigger -> dma -> factory y reinicio. Captura
   mínima, sesión persistente, cierre/cancelación, reposo, guards y archivos.
8. PDF posterior: instrucciones autocontenidas con resultados esperados,
   resolución de fallos y retorno a factory; debe acompañar al bundle real.

## Semántica de clientes ya implementada y probada

- osc.py --dma mantiene una sesión persistente, N infinito por defecto hasta
  cierre; acepta el antiguo --capture-mode triggered convirtiéndolo a persistent.
  El N lógico sin límite se traduce al máximo uint64 anunciado por el servidor.
- --max_waveforms positivo termina normalmente al llegar a N.
- osc.py y protobuf_acquire_list_channels.py aceptan --force_acq / --force-acq.
  No concede aprobación de alineación ni omite controles físicos.
- El cliente de archivos mantiene N positivo y usa --capture-mode persistent
  para una sola sesión por adquisición.
- scan_afe_delay_eye.py admite repetición sin reconfigurar tras fallo.
- --skip-ramp-verification omite la verificación larga, deja timing no verificado
  y la adquisición requiere force si el canal no tiene aprobación.
- Se conservan reportes de alineación parcial/fallida y aviso de --force_acq.
- CH39 tuvo errores físicos de rampa larga; no declarar que se resolvieron ni
  extrapolar ese comportamiento a otra placa.

Resultados de referencia: 29/29 CTest local y ARM, 41 pruebas de clientes/Qt en
PC y daphne-dev, sesión física con 525 eventos/6 s en cuatro canales L10000/P1024,
un START, cierre limpio; archivo N8 con un START/STOP. No son mediciones de
la Coldbox ni garantizan aceptar todos los pulsos externos.

## Archivos de lectura para el nuevo hilo

- docs/raw-dma-live-scope-results-2026-10-12.md
- docs/raw-dma-persistent-server-client-contract.md
- docs/raw-dma-manual-mode-switch.md
- docs/raw-dma-manual-overrides-results-2026-10-12.md
- docs/raw-dma-persistent-physical-results-2026-10-12.md
- scripts/deploy/daphne-mode
- scripts/deploy/daphne_manual_mode.py
- scripts/deploy/daphne_dma_frontend.py
- scripts/deploy/raw_dma_session_bundle.py
- scripts/deploy/raw_dma_session_driver_build.sh
- daphne-server/kernel/daphne-afe-dma/

Workspace Windows: raíz del checkout daphne-os/.
Python preparado: intérprete python del entorno activo, con las dependencias instaladas.
En daphne-server, DAPHNE_PROTO_PYTHON_DIR puede fijarse a srcs/protobuf para
evitar bindings antiguos. El loader también descarta esquemas DMA obsoletos.

Al iniciar este handoff, HEAD era 7da6fd8 y había un directorio no seguido
daphne-server/captures/ creado por las adquisiciones del usuario. Preservarlo:
no borrarlo, añadirlo a Git ni confundirlo con material de empaquetado.
Este archivo de handoff es documentación nueva; no se ha creado el PDF.
