# Consumidor kernel: sesión DMA persistente

Estado actualizado: el consumidor fue compilado en daphne-dev contra el proyecto
PetaLinux original e instalado en daphne-10. La integración software AUTO de
server y clientes pasó la cualificación física del 2026-10-12, incluida una
sesión de 100000 eventos. External/timing e IRQ Linux siguen pendientes.
El [informe de pruebas físicas](raw-dma-persistent-physical-results-2026-10-12.md)
registra los hashes, la configuración, los resultados y los límites; el
[contrato de server/clientes](raw-dma-persistent-server-client-contract.md)
define staging, ACK, lease y cancelación.

Las secciones siguientes conservan el contrato técnico y la evidencia histórica
de P3/P4 del 2026-10-11. Sus referencias a integración, instalación o pruebas
pendientes corresponden a esa fecha; el informe del 2026-10-12 las actualiza.

El [informe P3 de firmware/driver](../../daphne-firmware/docs/raw-dma-persistent-mmio-driver-2026-10-11.md)
contiene MMIO, semántica, evidencia y gates físicos. El
[diseño P1](../../daphne-firmware/docs/raw-dma-persistent-session-design-2026-10-11.md)
define la protección de bloques DDR. Este documento concreta cómo consumir
la extensión, después de cualificarla en placa.

## Admisión y configuración

Headers canónicos:
[UAPI](../daphne-server/kernel/daphne-afe-dma/daphne_afe_session_uapi.h) y
[helpers](../daphne-server/kernel/daphne-afe-dma/afe_session_contract.h).
Las ABI finita/triggered de `daphne_afe_dma_uapi.h` conservan sus layouts A40..A48.

CAPS (A50) verifica primero identidad y capability bit 7, luego API 1, magic
DSN1, los cinco bits requeridos de features (31) y slots 2..32 potencia de dos. Sin capability devuelve
EOPNOTSUPP antes de tocar los registros nuevos. No hacer fallback silencioso
a un modo que no tiene ownership concurrente.

PREPARE (A51) acepta config de 88 bytes y devuelve session, slots, anillos
normalizados y budget_bytes efectivo. Inicializar todos los campos a cero y
establecer abi=1, flags, length=L, pretrigger=P, period_ticks=D, source,
expected_build_id, channel_mask y target_events=N>0. flags PATTERN=1,
ALIGNED=2, AUTO=4; se exige PATTERN o ALIGNED y AUTO solo para software.
source: software=0, external=1, timing=2; canales normales 0..39.

`trigger_timeout_ms=0` selecciona 30 s sin progreso; se excluye la presión.
`pressure_timeout_ms=0` permite esperar crédito indefinidamente; valores
explícitos entre 10 y 600000 ms. La política de lease/ACK del cliente sigue
siendo responsabilidad de la futura integración del servidor.

Anillos temporales iguales para rutas activas. Cero selecciona una reserva
acotada, independiente de N; mínimo ceil((L+2D)/D)*D y default al menos 8D.
Máximo 512 períodos, 256 MiB/ruta, límite del módulo incluyendo guards y
PAGE_SIZE. `budget_bytes=0` usa el límite del módulo. `slots` y `session`
deben ser cero a la entrada. D=8192 es el período inicial a cualificar;
el mínimo lógico D=8 no tiene aceptación física.

## Secuencia de consumo

Ejemplo conceptual, no un programa ejecutado en placa:

```text
CAPS
PREPARE {abi=1, flags=PATTERN|AUTO, L=32000, P=1000, D=8192,
         source=software, expected_build_id=identidad_real,
         channel_mask=(1<<40)-1, N=100000}
START                             # A52, una sola vez por sesión
while delivered < N:
    GET(capacity=16, count=0)      # A54; evento[] apuntado por entries
    si EAGAIN: esperar poll y volver a intentar
    por cada evento, en orden:
        por cada ruta con valid_bytes > 0:
            READ(ID completo, ruta, offset, length <= 1 MiB)
            conservar o enviar los datos según la política del servidor
        RELEASE(ID)               # A56; no volver a usar el ID
        si EBUSY: esperar salida de DRAINING/copia activa y reintentar
STATUS                            # A53; esperar COMPLETE y released=N
```

GET devuelve registros de 160 bytes. Batch de 24 bytes: abi=1,
capacity=1..16, count=0, reserved=0, entries=puntero de event[]. Devuelve count.
GET tiene un consumidor serializado; EBUSY si ya hay una copia GET en curso.
EFAULT no transfiere ownership: reintentar obtiene los mismos IDs.

READ de 64 bytes: ID de 32 bytes, abi=1, route=0..2, length, copied=0,
offset relativo al inicio del payload válido y buffer=puntero de salida.
Retorna copied=length o error. RAW16 intercalado por canal canónico de cada
ruta; omitir rutas inactivas. Puede cruzar el anillo sin exponer su padding.
La copia mantiene una referencia al slot y deja STATUS accesible.

RELEASE utiliza batch con capacity=count=1..16 y entries apuntando a ID[].
Los IDs deben corresponder a GET exitosos, en orden de sequence desde 1.
Se valida el lote entero antes de liberarlo; ESTALE para ID incorrecto o
duplicado y EBUSY para copia activa o parada en curso. El retorno exitoso
acepta la solicitud asíncrona; STATUS.released avanza al recibir ACK hardware.
No leer ni volver a liberar un ID aceptado. Para red, elegir explícitamente
si el ACK del cliente o una copia acotada del servidor precede al RELEASE;
un puntero a DDR no puede sobrevivir a ese RELEASE.

Para software manual, TRIGGER (A58) devuelve EAGAIN si no está listo. Una
solicitud descartada al cruzar CDC no se guarda para replay. AUTO permite la
serie por hardware sin un ioctl/RPC por waveform. External/timing dependen
de sus eventos físicos y requisitos de salud; no se sustituyen por software.

## Estado, fin y errores

STATUS copia exclusivamente el cache; no hace MMIO ni espera halt/reset.
Contadores u64: accepted, completed, delivered y released son independientes.
Al fin normal accepted=completed=N; COMPLETE puede preceder a delivered=N.
El driver espera a recoger los registros finales, sin esperar GET, antes de
ordenar la parada. poll informa IN para eventos READY aun con HUP de productor
terminado. Consumir los pendientes antes de interpretar HUP como fin de descarga.
GET sin eventos da EAGAIN mientras corre y ENODATA al terminar.

CANCEL (A57) solicita la parada al worker y vuelve inmediatamente. No invalida
silenciosamente referencias ni reutiliza memoria. GET rechaza sesiones canceladas;
READ de un ID ya OWNED se permite si no hay error/poison, y RELEASE espera reposo
cuando corresponde. Un fallo de DMA/fence/guard se publica como error y no
se rellena con otro evento. Sin prueba viva de reposo hay QUARANTINED:
reservas retenidas y no descarga segura del módulo/overlay.

Otra PREPARE requiere productor en reposo y ningún slot/lector/GET pendiente.
Cerrar el último FD solicita parada; no es un ACK por evento. La futura
integración debe cubrir cancelación con consumidores activos y desconexiones.

## Evidencia y performance pendiente

- Driver ARM64 compilado W=1 contra kernel
  `6.18.10-xilinx-g4f7afe14f724`, proveedor cíclico API 1; no instalado.
- Once layouts Linux y offsets UAPI de 32/64 bits verificados compile-only.
- Helpers reales: 50000 codecs aleatorios, ownership/IDs y lecturas circulares PASS.
- Función service real con MMIO/scheduler simulados: llegada final después de
  FIFO vacía, snapshot anterior al último evento, contadores >2^32 y STOP
  inconsistente PASS. No demuestra concurrencia kernel ni coherencia física.
- MMIO/control/CDC firmware: 15 eventos en dos sesiones y token software sin replay PASS.

El driver usa polling de delayed_work; CONFIG_HZ=250 impone mínimo 4 ms para
msecs_to_jiffies(1). IRQ agregada existe en el RTL, pero falta binding IRQ/DT
y manejo IRQ Linux. La parada final todavía usa el proveedor que puede agotar
1 s por ruta; se eliminó esa parada por waveform, no se aceleró el proveedor.
Todavía no hay medición de throughput de esta sesión en placa.

Pruebas desde `daphne-server/kernel/daphne-afe-dma` en Linux:

```bash
python3 test_session_contract.py --output /tmp/session-contract
python3 test_session_service.py --output /tmp/session-service
gcc -Wall -Wextra -Werror -m32 -I/usr/include/x86_64-linux-gnu -c session_layout_test.c -o /tmp/session-layout32.o
gcc -Wall -Wextra -Werror -m64 -c session_layout_test.c -o /tmp/session-layout64.o
```

Build ARM y logs temporales: `/tmp/daphne-session-p3-20261011/` en daphne-dev.
El informe P3 conserva SHA256 y copia local del módulo/logs en daphne-firmware.
P4 integra fence, packers, quiet/reset, identidad y XPM/timing; P5 cualifica
kernel/placa y mide sin red; P6 adapta servidor/protobuf/clientes y ACK/lease.

## Actualización P4: integración de placa

El [informe de integración firmware/driver](../../daphne-firmware/docs/raw-dma-persistent-board-integration-2026-10-11.md)
registra el candidato preparado para síntesis. Se habilita explícitamente con
raw-dma + DAPHNE_DMA_SESSION=1; todavía no está desplegado. FEATURES bits 3/4
acreditan límites físicos verificados y prueba viva de reposo, además de los
bits 0/1/2 de prefix, ownership e IRQ. El driver exige todos antes de acceder
al nuevo banco de límites AFEC+0x380..0x3ac.

START programa base/final exclusivo de cada reserva coherente real; no acepta
límites físicos de userspace. El firmware verifica tamaño, alineación, DDR y
anillos sin solapamiento, y observa AW/W/B reales. STOP conserva los eventos
terminados para READ/RELEASE. El driver refresca CR/SR de los tres motores para
comprobar la parada final; un snapshot retenido no sirve como prueba. El cierre
normal sin referencias devuelve el ownership al firmware con RESET antes de
permitir otro trabajo legacy.

Driver P4 compilado ARM64 con W=1, sin warnings, para el mismo kernel. SHA256:
`d25ab970bb5288e1d419974f63ab92e9427163a34ec68a9d2a3c0f0f5f9a4255`.
Fuentes/build remotos: `/tmp/daphne-session-p4-integrated-20261011/source/consumer`.
El candidato de firmware `a1c15bd` identifica una huella de fuentes, no un commit
Git; base Git 1d17a11. La integración/XPM y el BD/XSA previo a síntesis pasaron.
Timing de placa, kernel/DDR reales y throughput requieren los gates siguientes.
No se instalaron módulos ni se cargó firmware. El servidor y clientes existentes
continúan con el contrato anterior.
