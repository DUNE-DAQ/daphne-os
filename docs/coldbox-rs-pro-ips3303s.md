# Control de la fuente RS PRO de la coldbox

Controlador: `scripts/remote/rs_pro_ips3303s.py`. Python 3, sin paquetes externos,
en Linux. Controla las salidas DC comunes de la fuente, no su interruptor de red.
El script no configura tensiones, corrientes, modo, memorias, baud rate ni bloqueo
del panel. No incluye comandos arbitrarios ni opciones para saltarse la protección.

## Configuración exigida por DAPHNE

Ambos canales deben tener **24.000 V y límite de 1.000 A**, con el modo interno
**independiente**. Los canales se conectan externamente en serie mediante el
cable descrito por el operador para obtener 48 V nominales. La conexión externa
no puede verificarse mediante USB. La corriente disponible en serie es 1 A.

`on` comprueba la identidad, obtiene dos lecturas completas de configuración y
solo entonces permite `OUT1`. Compara los valores con decimales exactos, sin
tolerancias que admitan otra configuración. Si una lectura falla, el modo no es
independiente o cualquier consigna difiere, termina con código 1 sin enviar
`OUT1`. No corrige automáticamente los ajustes.

Después de `OUT1` verifica nuevamente configuración y estado. Si falla esa
verificación, intenta `OUT0` y devuelve error, sin afirmar que el apagado esté
confirmado. `off` permite apagar incluso con consignas o modo incorrectos, y
comprueba el estado después. Ambos comandos afectan al control OUTPUT común;
no proporcionan conmutación individual de CH1/CH2.

La protección comprueba la configuración durante el comando `on`; no es un
monitor continuo de cambios posteriores en el panel o por otro programa. El
puerto se reserva durante la operación para evitar accesos concurrentes. No
reintenta consultas con timeout: una respuesta tardía no debe atribuirse a otro
canal.

## Identidad y protocolo verificados

Lectura de la fuente el 22 de octubre de 2026, desde AlmaLinux-9 en WSL mediante
`ssh rpi-coldbox`:

```text
*IDN?  -> RS PRO  ,IPS-3303S,SN:725D240G2,V2.10
STATUS? -> 00011010
VSET1? -> 24.000V
ISET1? -> 1.000A
VSET2? -> 24.000V
ISET2? -> 1.000A
STATUS? -> 00011010
```

Dispositivo persistente:

```text
/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A505EMDH-if00-port0
```

Correspondía a `/dev/ttyUSB4`. Se usa la ruta persistente para evitar depender
del orden de enumeración USB. La identidad, serie y firmware están fijados al
equipo anterior; cualquier diferencia impide ejecutar acciones.

Comunicación: **9600 baudios, 8N1, sin control de flujo**. Consultas terminadas
en CR (`\r`); `OUT0`/`OUT1` terminados en LF (`\n`). Respuestas terminadas en
CRLF. No se envían `BAUD`, `TRACK`, `REMOTE` ni `LOCAL`.

La respuesta observada contiene ocho caracteres ASCII en orden bit0 a bit7:

| Posición | Significado |
| --- | --- |
| 0, 1 | Regulación CH1/CH2: 0=CC, 1=CV |
| 2, 3 | Modo: 01=independiente, 11=serie, 10=paralelo |
| 4 | Beep |
| 5 | OUTPUT: 0=deshabilitado, 1=habilitado |
| 6, 7 | Baud: 10=9600 |

Así, `00011010` indica modo **independiente**, OUTPUT **OFF** y 9600 baudios.
El orden ASCII se identifica por el campo de baud `10`, coherente con la
velocidad comprobada. No se convierte la cadena en un entero binario.

La tabla antigua del [manual IPS X303, página 45](https://docs.rs-online.com/8d5c/0900766b81409dec.pdf)
coloca OUTPUT en bit6 y solo documenta 57600/115200. Esa variante no describe el
equipo observado. La variante de tres velocidades y OUTPUT en bit5 está
documentada en el [manual GPD-X303S del fabricante, páginas 50–51](https://www.gwinstek.com/en-global/download/downloadFile/7837).
La combinación observada de identificación, baud y respuesta se usa para
seleccionar esta variante; el controlador rechaza estados cuyo campo baud no
coincida. CV/CC describe la regulación, no el modo independiente/serie/paralelo.

## Probar en la Raspberry

Los archivos se copian a `~/coldbox-control/`. Desde AlmaLinux-9 en WSL:

```bash
ssh rpi-coldbox
cd ~/coldbox-control
```

Consultas de solo lectura:

```bash
python3 rs_pro_ips3303s.py config
python3 rs_pro_ips3303s.py status
python3 rs_pro_ips3303s.py measure
```

- `config`: muestra `channels` con tensión y límite de corriente, junto con
  `status.mode` (`independent`, `series`, `parallel`).
- `status`: muestra `output_enabled`, estado lógico de las salidas. No representa
  el interruptor físico. Una fuente sin alimentación o sin USB produce error;
  no se interpreta un timeout como OUTPUT OFF.
- `measure`: muestra tensión y corriente medidas en cada canal. Son lecturas
  sucesivas, no una adquisición simultánea ni la medición directa de la entrada
  de DAPHNE.

Acciones para ejecutar manualmente cuando se quiera cambiar las salidas:

```bash
# Habilitar: solo se acepta 24 V / 1 A en ambos canales, modo independiente.
python3 rs_pro_ips3303s.py on
python3 rs_pro_ips3303s.py status
python3 rs_pro_ips3303s.py measure

# Deshabilitar y comprobar.
python3 rs_pro_ips3303s.py off
python3 rs_pro_ips3303s.py status
```

Salida JSON con `simulation: false`. Código de salida 0 si la operación se
verifica, 1 ante fallo; los errores se escriben en stderr. No se han ejecutado
`on` ni `off` contra el equipo durante la implementación.

## Simulación sin hardware

```bash
python3 rs_pro_ips3303s.py on --simulate
python3 rs_pro_ips3303s.py off --simulate
python3 rs_pro_ips3303s.py config --simulate
python3 rs_pro_ips3303s.py status --simulate
python3 rs_pro_ips3303s.py measure --simulate
```

Cada invocación crea un simulador nuevo con OUTPUT OFF; no persiste el estado
entre procesos. Todos los resultados llevan `simulation: true`. En ese modo no
se abre ningún dispositivo. Las mediciones simuladas son datos sintéticos.

Desde la raíz del repositorio, en Linux/WSL:

```bash
python3 -m unittest discover -s tests/remote -p test_rs_pro_ips3303s.py -v
```

Las pruebas incluyen una secuencia ON/medición/OFF en memoria, los bloqueos por
consignas y modos incorrectos, fallo de identidad/firmware, estado malformado,
lecturas incompletas, cambios durante la comprobación, apagado con configuración
incorrecta y fallo después de habilitar. Un emulador independiente con
pseudoterminal POSIX verifica el transporte de producción y los terminadores,
incluidas respuestas fragmentadas. Estas pruebas no conectan con la Raspberry.
