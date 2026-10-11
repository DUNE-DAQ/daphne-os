# Traspaso: performance de raw DMA en servidor y clientes

Fecha: 2026-10-11. Destinatario: hilo nuevo encargado de daphneServer, protobuf
y clientes del PC. Este documento permite continuar sin leer todo el historial.

## Instrucción vigente: planificar, no desarrollar todavía

El usuario quiere pasar de funcionalidad demostrada a maximizar throughput.
Solicitó documentos de coordinación y traspaso, **no autorizó comenzar el nuevo
desarrollo**. Leer este documento y el handoff de firmware/driver, revisar el
código y proponer el contrato/plan. Esperar su orden antes de implementar.
No cargar productos nuevos ni cambiar la sesión de DAPHNE para preparar el plan.

Reparto acordado:

- Otro hilo: firmware, proveedor DMA y consumidor kernel/UAPI, aunque estos
  últimos archivos estén en daphne-os.
- Este nuevo hilo: servidor, protobuf, clientes de archivos/osc y su integración.
- Ambos: acordar ownership de buffers, créditos, publicación de eventos,
  pretrigger, estados y versiones antes de desarrollar. No modificar las partes
  del otro hilo sin coordinación explícita.

Documento principal enviado para el trabajo de firmware/driver:
[raw-dma-performance-firmware-driver-handoff-2026-10-11.md](raw-dma-performance-firmware-driver-handoff-2026-10-11.md).
Contiene la propuesta completa, alternativas pendientes y pruebas de aceptación.
Fue creado en commit `371b642`. Los nombres de operaciones y el objetivo
provisional de 80% del baseline son propuestas, no una ABI ni un objetivo
numérico aprobado.

## Intención del usuario y restricciones que deben persistir

La sesión DMA debe empezar una vez, adquirir N waveforms y descargar eventos
en paralelo, manteniendo los motores preparados entre eventos. Si el consumidor
no libera espacio, suspender la aceptación de nuevos eventos entre ventanas y
continuar al recuperar créditos. Parar al completar N o al cancelar/fallar.
Optimizar solo el reset por waveform no cumple el objetivo.

Ejemplo del usuario: N=100000, L=32000. **N=0 fue un typo; la corrección es N=1**
para referirse al comienzo con la primera waveform. N es el total objetivo
positivo; no se pidió un modo indefinido con N=0.

- L es la longitud de cada waveform, N su cantidad; no son bloques arbitrarios
  de datos continuos. Cada ventana está sincronizada con un trigger.
- Con pretrigger P, devolver [T-P, T-P+L), 0 <= P < L, trigger en la muestra P.
  Los triggers durante la ventana se ignoran, sin replay en el evento siguiente.
- Admitir software, external y timing. En software se quiere disparar tan rápido
  como permitan las ventanas y recursos, como se hacía con spybuffer. La propuesta
  de una secuencia autónoma autorizada desde Linux debe acordarse con firmware.
- No sobrescribir eventos no consumidos. Bajo presión, los eventos físicos no
  aceptados deben contarse; N cuenta waveforms completas, no todos los pulsos.
- No tocar el camino spybuffer ni cambiar el backend predeterminado. Conservar
  DMA finito para configuración/alineación y compatibilidad actual.
- No ligar compatibilidad a un commit de firmware: negociar ABI/capacidades.
  Las identidades concretas de los informes son evidencia de ensayo.
- Todos los AFEs se tratan normalmente, incluido AFE4. CH39 tiene un problema
  independiente y su diagnóstico no pertenece a este scope.
- Mantener presentación de usuario próxima a spybuffer, cuya redacción prefiere
  el usuario, con solo referencias necesarias a DMA. No volver a divergencias
  gratuitas en los mensajes de adquisición/scan.
- La implementación futura debe distribuirse en commits prudentes; no un
  commit único. Separar contrato, motor/servicio, clientes, pruebas/documentación.

## Estado del repositorio

PC Windows, PowerShell. Raíz:
`C:/Users/e_cri/Documents/DAPHNE/daphne-os`.
Firmware hermano: `C:/Users/e_cri/Documents/DAPHNE/daphne-firmware`.
Rama al redactar: `codex/afe0-synthetic-config`; base documental anterior a este
traspaso: `371b642`. El nombre de rama es histórico, no limita el scope a AFE0.

Cambios presentes del usuario/otras tareas, ajenos a este traspaso:

```text
 M docs/raw-dma-local-verification.md
?? docs/raw-dma-board-bringup-2026-10-09.md
?? daphne-server/dma_run/
?? daphne-server/triggered_test_01/
```

Revisar git status al retomar; no limpiar, sobrescribir ni incluir estos cambios
en commits propios. Los productos build/ de diagnóstico están ignorados.

Serie de integración triggered ya completada:

| Commit | Cambio |
|---|---|
| `b433994` | Protobuf: modos, negociación y metadatos de trigger |
| `df8c4b3` | Motor de sesión triggered reutilizable y validación |
| `7fcc6c6` | Worker del servidor, progreso cacheado y jobs triggered |
| `bc09f95` | Adaptador cliente, adquisición de archivos y contratos de append |
| `b8f458c` | osc.py: eje relativo, pretrigger y cierre asíncrono |
| `f58aa3b` | Documentación y verificación ARM inicial |
| `c896e7f` | Corregir interpretación del snapshot retenido anterior a halt |
| `4d3810a` | GUI: conservar error DMA visible y detener reintentos automáticos |
| `0dddde4` | Pruebas físicas posteriores y diagnóstico de latencia |
| `371b642` | Propuesta de sesión persistente para firmware/driver |

La extensión kernel anterior está en `7dc5466`; el trabajo de performance aún
no comenzó. No confundir commits de funcionalidad con implementación persistente.

## Qué hace actualmente el software

Protocolo de control: protobuf dentro de EnvelopeV2 sobre ZeroMQ; RPC describe
el patrón petición/respuesta, no otro formato que reemplace protobuf.
Capabilities negocia revisión 2 si el cliente la solicita; conservar rechazo
explícito de servidor/bindings/capacidades incompatibles, sin fallback silencioso.

Modos actuales:

- Finite: START desde Linux, software, P=0; scanner/configuración usan este camino.
- Triggered: PREPARE una vez por lote; ARM/evento/COMPLETE/lectura por waveform.
  Buffers se reutilizan después de copiar la anterior. El kernel termina DMA
  para cada evento. Todavía no hay cola de slots con producción concurrente.

El servidor retiene el lote completo, finaliza la sesión y publica DMA_JOB_READY.
DMA_READ requiere ese estado; ACK libera el job completo. El cliente de archivos
divide N en jobs de tamaño min(chunk, límite anunciado), espera cada job, escribe,
ACK y empieza el siguiente. osc.py usa el mismo adaptador DMA y adquiere eventos
sucesivos; los errores DMA ahora quedan visibles y detienen su adquisición.

Límites actuales: 64 MiB de staging/job, 256 waveforms/job, fragmentos <=1 MiB,
pool de anillos <=448 MiB, período 8192 ticks y lease 30 s. La geometría del
historial es independiente de N. No elevar el límite de staging como sustituto
de una cola acotada que permita N grande.

RAW16 LE contiene ADC14 two's complement desplazado 2 bits. DmaClient valida
fragmentos y metadatos, desplaza, enmascara y XOR 0x2000 para devolver ADC14
offset binary. Archivos por canal: u16 LE, compatibilidad y append comprobados.
No perder la corrección de codificación que devuelve baseline cercano a 8192.

## Mapa del código que debe leer el nuevo hilo

| Archivo relativo a la raíz | Papel / punto a cambiar posteriormente |
|---|---|
| daphne-server/srcs/protobuf/daphneV3_high_level_confs.proto | Capabilities, jobs, control/read, modos, fases y metadatos |
| daphne-server/srcs/server_controller/dma_service.hpp y dma_service.cpp | Ownership, worker, staging, READ solo en READY, ACK del job |
| daphne-server/srcs/server_controller/dma_service_hardware.cpp | Admisión/guardas de hardware y frontend |
| daphne-server/dma/afe_capture.hpp | Interfaces de engine/backend/sesión |
| daphne-server/dma/afe_trigger_capture.cpp | next() hace un ARM por waveform; finish() comprueba limpieza |
| daphne-server/dma/afe_capture.cpp | Motor finito y adaptación Linux/UAPI, incluido LinuxTriggerBackend |
| daphne-server/client/dma_client.py | Negociación, espera completa, lectura estricta, ACK/cancel/lease |
| daphne-server/client/dma_acquire_cli.py | Fraccionamiento actual de N en jobs y escritura por lote |
| daphne-server/client/dma_options.py y dma_output.py | Opciones, contrato/append y metadatos |
| daphne-server/client/protobuf_acquire_list_channels.py | Entrada del cliente de archivos; spybuffer separado |
| daphne-server/client/osc.py | Worker Qt, render limitado, eje (j-P)/Fs y cierre asíncrono |
| daphne-server/client/configure_fe_min_v2.py y scan_afe_delay_eye.py | Preservar configuración/alineación; scanner DMA finito |
| daphne-server/srcs/server_controller/dma_eye_scan.cpp | Scan y verificación física final de rampa |
| daphne-server/kernel/daphne-afe-dma/ | UAPI/consumidor/parche del proveedor; responsabilidad del otro hilo |

Revisar rutas con rg --files; no asumir nombres de helpers no existentes.
Router ZMQ conserva su socket; no pasar una llamada kernel bloqueante de STATUS
al router. Sus fases/contadores provienen del worker. Mantener CANCEL/KEEPALIVE
responsivos durante espera, descarga y limpieza.

## Diagnóstico de performance y fallo GUI ya corregido

Medido directamente en C++: ~1,31 s/evento con una ruta y ~3,94 s con tres.
No incluye red/protobuf. El proveedor intenta stop, agota polling atómico con
espera nominal de 1 s por ruta y luego resetea; las rutas son secuenciales.
El usuario recibió 1000/1000 eventos CH0/1, L=2048, P=1024, chunk=10 en 22:23.
Reducir L/aumentar chunk no elimina esa parada por evento.

El gráfico vacío anterior se debía a validación equivocada del snapshot retenido
antes del halt. COMPLETE del kernel se publica después de la barrera DDR/parada,
pero conserva monitor IDLE/RUN del instante previo. c896e7f admite ese snapshot
completado sin RESET o uno ya HALTED; conserva geometría/guards/errores/fence y
la comprobación final de reposo vivo. No exigir que cada evento de la futura
sesión persistente deje el motor detenido para demostrar que sus datos son válidos.

Ver detalles y resultados exactos en
[raw-dma-trigger-snapshot-fix-2026-10-11.md](raw-dma-trigger-snapshot-fix-2026-10-11.md).
No confundir corrección funcional cerrada con performance resuelta.

## Pruebas completadas y aceptación pendiente

- Integración inicial: build Release ARM, 25/25 entradas CTest; 18 pruebas Python
  de cliente y 5 Qt en PC. La ejecución ARM omite Qt si no está instalado.
- Corrección posterior: build ARM, afe_trigger_unit y dma_service_unit 2/2;
  pruebas Qt actualizadas 6/6. No se afirma que se repitió toda la suite tras
  esos dos cambios.
- Servidor corregido: finite CH0/1 L=2048, triggered CH0/1 L=2048/P=1024 y
  L=65536/P=8192; dos eventos CH0 P=0 y dos de los 40 canales P=8192.
- Cancelación en curso y captura finita posterior aprobadas. osc.py real contra
  DAPHNE, Qt offscreen: dos waveforms recibidas/renderizadas, 2048 puntos,
  x[1024]=0 y cierre del worker confirmado. Baselines ~8193/8208 cuentas.
- Ensayo de 1000 eventos informado por el usuario; no se repitió esa campaña larga.

Pendientes anteriores: external controlado, timing positivo/jitter, timeout de
trigger de extremo a extremo y regresión spybuffer con cambio de sesión. Se
observaron eventos external sin pulsos habilitados en otra campaña: resolver
el origen antes de atribuirlos a estímulos deliberados. Ninguno de estos ensayos
se considera aprobado por haber anunciado una capacidad en el protocolo.

Pendiente nuevo: toda la adquisición persistente, créditos, solapamiento y
benchmark sostenido. El alcance supera T6 de optimizar terminación.

## Sesión manual de DAPHNE: último estado observado, no garantía futura

Acceso SSH que funcionó: `ssh daphne-10`, alias hacia petalinux@193.206.157.36.
La conexión por IP rechazaba la clave usada inicialmente; usar el alias. Se puede
compilar en DAPHNE. Para sudo interactivo por herramientas, usar ssh -tt y PTY;
sin PTY quedó una petición de contraseña esperando. No almacenar credenciales
en scripts, comandos ni este documento.

Última sesión verificada:

```text
servicio: daphne-dma-manual.service, active
binario: /opt/daphne-dma-trigger-manual-20261011/daphneServer
args: --dma --gateware-mode raw-dma --expected-gateware-build-id 0x01D17A11 --bind tcp://*:40001
unidad transitoria: /run/systemd/system/daphne-dma-manual.service
firmware observado: 0x01d17a11; ABI 0x20000; capabilities 0x570
protocolo negociado: 2
kernel: 6.18.10-xilinx-g4f7afe14f724
dispositivo: /dev/daphne-afe-dma, root 0600
frontend: cinco AFEs ALIGNED, máscaras 0xff, generación 4
```

No inferir que sigue igual al retomar. Revalidar capabilities/servicio antes de
pruebas autorizadas y evitar clientes simultáneos. No cambiar firmware por
defecto ni servicios de arranque como parte de la integración experimental.

El despliegue de la corrección conservó firmware, módulos y unidad. Binarios
anteriores: sufijo .pre-snapshot-fix en el directorio /opt anterior. El helper
build/dma-trigger-diagnostic/deploy_snapshot_fix.py ya fue ejecutado y rechaza
backups existentes; no rerun como una rutina de arranque.

La copia compilada aislada está en /tmp/dma-trigger-server-review-20261011/build
en DAPHNE; no es un checkout git. Logs iniciales y engine-probe.log están allí.
Copias ARM actualizadas en build/dma-trigger-arm64/ del PC coinciden con /opt;
los SHA256 figuran en el informe de la corrección. /tmp puede desaparecer tras
reinicio; los fuentes/commits del repositorio son la referencia recuperable.

## Parámetros analógicos del usuario: conservarlos

El usuario dio este comando. Ejemplo desde la raíz del repositorio; **no ejecutar
al leer este traspaso ni reconfigurar una sesión alineada sin necesidad**:

```powershell
$taskPython = 'C:/Users/e_cri/miniconda3/python.exe'
$env:DAPHNE_PROTO_PYTHON_DIR = "$PWD/build/dma-server/srcs/protobuf"
& $taskPython .\daphne-server\client\configure_fe_min_v2.py `
  -ip 193.206.157.36 -port 40001 --route mezz/0 `
  --dma --skip-alignment `
  -vgain 1700 -ch_offset 2275 -lpf_cutoff 10 `
  -pga_clamp_level '-2 dBFS' -pga_gain_control '24 dB' `
  -lna_gain_control '12 dB' -lna_input_clamp '1.15 Vpp' `
  --adc_resolution 0 --biasctrl-dac 1300 `
  --timeout 30000 --cfg-timeout-ms 30000
```

Los bindings locales actualizados están en build/dma-server/srcs/protobuf/;
protobuf_loader.py usa DAPHNE_PROTO_PYTHON_DIR para evitar bindings obsoletos.
Regenerar C++/Python juntos cuando se autorice cambiar el .proto.

Tras reiniciar el servidor corregido se reaplicó esta configuración. Un scan
de los cinco AFEs con samples=2048/verification=32768 falló al final; no se
declaró alineado ese resultado. El scan deja FAILED al fallar y un scan nuevo
puede exigir reconfiguración primero. En la sesión posterior del usuario los
cinco AFEs aparecieron ALIGNED; las pruebas finales no modificaron esa sesión.
No reemplazar los parámetros por defaults ni aplicar taps/slips de un informe
como calibración persistente. La alineación debe ser medida y verificada.

Comando GUI funcional verificado, adaptado a cwd raíz:

```powershell
& $taskPython .\daphne-server\client\osc.py `
  -ip 193.206.157.36 -port 40001 `
  --dma --capture-mode triggered --trigger-source software `
  --pretrigger 1024 -L 2048 --channels 0,1 `
  --trigger-timeout-ms 30000 -timeout_ms 10000
```

La prueba automática limitó la GUI a dos eventos. No confundir esperar un
trigger con un gráfico de datos faltantes; conservar errores DMA visibles.

## Evidencia local y compilación posterior

build/dma-trigger-diagnostic/ contiene capture_probe.py, server_closure_probe.py,
osc_live_probe.py, JSON, NPY y PNG de ensayos; también logs de configure/scan
fallidos. Son scripts de diagnóstico del estado actual, no tests de performance
de la arquitectura futura. No ejecutarlos en paralelo con los clientes del usuario.

Build Linux ARM de referencia, para cuando se autorice desarrollar:

```sh
cmake -S daphne-server -B build/dma-server -DCMAKE_BUILD_TYPE=Release -DDAPHNE_BUILD_DMA_DIAG=ON
cmake --build build/dma-server --parallel 2
ctest --test-dir build/dma-server --output-on-failure
```

En PC se usó C:/Users/e_cri/miniconda3/python.exe con numpy, PyQt6/pyqtgraph,
protobuf y ZeroMQ. Qt puede probarse offscreen; verificar con datos simulados
y después con capturas reales. Hardware, builds e instalaciones son pasos
distintos; un binario compilado no prueba integración física.

## Primer trabajo del siguiente hilo

1. Leer handoff firmware/driver, este documento y código relevante; confirmar
   estado git y distinguir funcionalidades actuales de propuestas.
2. Obtener la respuesta de arquitectura/UAPI del hilo receptor a través del
   usuario o autorización explícita de comunicación. No asumir qué implementó.
3. Proponer contrato servidor: lectura mientras RUNNING, secuencias y ACK por
   lote, ownership de DDR/staging/transporte, presión, fin adquirido vs entregado,
   contadores y tiempos. Revisar anchos/rangos para N grande y plazo total.
4. Acordar significado de índices/timestamps tras pausas, pretrigger fresco,
   disparos software repetidos y errores; no diseñar READ concurrente sobre
   slots que el driver pueda sobrescribir.
5. Planificar commits y pruebas: colas acotadas con wrap/reuso, consumidor lento,
   stale ACK, último lote, cancel/lease, separación entre render y adquisición,
   compatibilidad/append y regresión finito/spybuffer.
6. Dimensionar benchmark con almacenamiento real. N=100000/L=32000 son 12,8 GB
   para dos canales o 256 GB para 40, antes de overhead. No iniciar esa campaña
   como primer ensayo. Medir captura, copias, red y disco por separado.
7. Presentar el plan y esperar la orden del usuario. No comenzar desarrollo
   basándose solamente en que el handoff propone operaciones o tests.

## Mensaje inicial sugerido para el hilo nuevo

> Continúa la planificación de performance de raw DMA para daphneServer y los
> clientes. Lee docs/raw-dma-server-client-performance-handoff-2026-10-11.md y
> docs/raw-dma-performance-firmware-driver-handoff-2026-10-11.md. Otro hilo se
> encarga del firmware y driver. Queremos una sesión DMA persistente para N
> waveforms, con descarga concurrente y presión por créditos; N=0 fue un typo,
> no pedimos adquisición indefinida. Preserva spybuffer, DMA finito y parámetros
> analógicos. Revisa el contrato y propón el plan; no implementes ni modifiques
> DAPHNE hasta mi orden.
