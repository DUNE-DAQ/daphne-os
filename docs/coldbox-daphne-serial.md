# Consola serie de DAPHNE en la coldbox

Script: `scripts/remote/daphne_serial_console.py`. Abre **la interfaz estable
`if01` a 115200 baudios, 8N1, sin control de flujo**. Prefiere `minicom` si está instalado;
si no, usa una consola Python 3 sin dependencias externas.

El 22 de octubre de 2026 no había `minicom`, `picocom` ni `screen` en la
Raspberry. No se instalaron paquetes. El identificador USB de esta placa es
`Xilinx DAPHNE Mezzanine 004`, serie `DAPHNE004`. Su consola se selecciona por:

```text
/dev/serial/by-id/usb-Xilinx_DAPHNE_Mezzanine_004_DAPHNE004-if01-port0
```

Se aplica el mapeo proporcionado por el operador: A/if00=JTAG, B/if01=consola
ARM PS UART1, C/if02 y D/if03 sin destino documentado. El script rechaza rutas
basadas únicamente en `ttyUSB` y las interfaces distintas de `if01`. No se ha
confirmado un prompt ARM mediante una conexión real durante esta entrega.

Desde WSL AlmaLinux-9:

```bash
ssh -t rpi-coldbox 'python3 /home/rpi-coldbox/coldbox-control/daphne_serial_console.py'
```

O, desde una sesión SSH interactiva en la Raspberry:

```bash
python3 /home/rpi-coldbox/coldbox-control/daphne_serial_console.py
```

Para la DAPHNEMezz de daphne-10, desde el host que tenga conectada esa placa:

```bash
python3 daphne_serial_console.py --port /dev/serial/by-id/usb-Xilinx_DAPHNEMezz_FNALDMezz10-if01-port0
```

Los números `ttyUSB0/1/2/3` pueden cambiar con la enumeración. La referencia
estable es el identificador USB completo y la interfaz `if01`.

Para salir:

- Consola Python: **Ctrl-]**.
- Minicom: **Ctrl-A**, después **Q** y confirmar la salida sin reiniciar el
  módem. Su [manual](https://manpages.debian.org/bookworm/minicom/minicom.1.en.html)
  documenta `-o` para omitir inicialización y Ctrl-A Q para salir sin reset.

Con `minicom` se crea un perfil temporal privado que fija los parámetros serie
y desactiva RTS/CTS y XON/XOFF. No se modifica la configuración personal de
minicom. El perfil se elimina al salir.

El script no envía un retorno de carro ni comandos al iniciar. Lo que escriba
el operador se transmite a DAPHNE; en la consola Python Ctrl-C también se
transmite al equipo. La consola Python restaura la configuración del terminal
local y del puerto al salir normalmente o por una excepción.

Se puede comprobar la disponibilidad **sin abrir el puerto**:

```bash
python3 /home/rpi-coldbox/coldbox-control/daphne_serial_console.py --check
```

Durante la entrega solo se ejecutó esta comprobación en la Raspberry. La consola
no se abrió y no se enviaron datos a DAPHNE. El backend Python se verificó con
pseudoterminales locales y la selección de minicom con una llamada simulada.
