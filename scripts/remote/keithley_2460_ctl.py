#!/usr/bin/env python3
"""Verified Keithley 2460 USBTMC control helper.

This script is intended for hosts like `np04-onl-004` where the Keithley 2460
is directly attached as `/dev/usbtmc0`. The device is currently reliable for
write-only SCPI commands when each transaction uses a fresh open/close cycle.
The flaky case is cycling output OFF then ON inside one long-lived USBTMC
session, so `cycle` intentionally recovers the USBTMC transport between legs
and verifies the observed output state after each transition.
"""

import argparse
import math
import os
import pathlib
import time
from typing import Callable, List, Optional


_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS

_IOC_NONE = 0
_USBTMC_IOC_NR = 91


def _io(nr: int) -> int:
    return (
        (_IOC_NONE << _IOC_DIRSHIFT)
        | (_USBTMC_IOC_NR << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
    )


USBTMC_IOCTL_CLEAR = _io(2)
USBTMC_IOCTL_ABORT_BULK_OUT = _io(3)
USBTMC_IOCTL_ABORT_BULK_IN = _io(4)
USBTMC_IOCTL_CLEAR_OUT_HALT = _io(6)
USBTMC_IOCTL_CLEAR_IN_HALT = _io(7)
USBTMC_IOCTL_CANCEL_IO = _io(35)
USBTMC_IOCTL_CLEANUP_IO = _io(36)

RECOVERY_IOCTLS = (
    USBTMC_IOCTL_CLEAR,
    USBTMC_IOCTL_ABORT_BULK_OUT,
    USBTMC_IOCTL_ABORT_BULK_IN,
    USBTMC_IOCTL_CLEAR_OUT_HALT,
    USBTMC_IOCTL_CLEAR_IN_HALT,
    USBTMC_IOCTL_CANCEL_IO,
    USBTMC_IOCTL_CLEANUP_IO,
)


def _best_effort_ioctl(fd: int, code: int) -> None:
    import fcntl

    try:
        fcntl.ioctl(fd, code, 0)
    except OSError:
        pass


def _prep_fd(fd: int) -> None:
    for code in RECOVERY_IOCTLS:
        _best_effort_ioctl(fd, code)


class SupplyStatus:
    def __init__(
        self,
        *,
        output_enabled: bool,
        source_volts: float,
        measured_volts: float,
        measured_amps: float,
    ) -> None:
        self.output_enabled = output_enabled
        self.source_volts = source_volts
        self.measured_volts = measured_volts
        self.measured_amps = measured_amps

    def format_lines(self) -> List[str]:
        def _fmt(label: str, value: float) -> str:
            if math.isnan(value):
                return "{}=n/a".format(label)
            return "{}={:.6f}".format(label, value)

        return [
            "output={}".format("ON" if self.output_enabled else "OFF"),
            _fmt("source_volts", self.source_volts),
            _fmt("measured_volts", self.measured_volts),
            _fmt("measured_amps", self.measured_amps),
        ]


class Keithley2460:
    def __init__(self, device: str) -> None:
        self.device = pathlib.Path(device)
        self.usbmisc_name = self.device.name
        self._sysfs_interface = self._resolve_sysfs_interface()
        self._interface_name = self._sysfs_interface.name
        self._usb_device_name = self._sysfs_interface.parent.name

    @property
    def sysfs_interface(self) -> pathlib.Path:
        return self._sysfs_interface

    @property
    def interface_name(self) -> str:
        return self._interface_name

    @property
    def usb_device_name(self) -> str:
        return self._usb_device_name

    def _resolve_sysfs_interface(self) -> pathlib.Path:
        usbmisc_path = pathlib.Path(
            "/sys/class/usbmisc/{}/device".format(self.usbmisc_name)
        )
        if usbmisc_path.exists():
            return usbmisc_path.resolve()

        for dev_dir in pathlib.Path("/sys/bus/usb/devices").iterdir():
            id_vendor = dev_dir / "idVendor"
            id_product = dev_dir / "idProduct"
            if not id_vendor.exists() or not id_product.exists():
                continue
            if (
                id_vendor.read_text().strip().lower() == "05e6"
                and id_product.read_text().strip().lower() == "2460"
            ):
                interface = pathlib.Path("{}:1.0".format(dev_dir))
                if interface.exists():
                    return interface.resolve()

        raise FileNotFoundError("Could not locate Keithley 2460 USB interface in sysfs")

    def _transact(
        self,
        command: str,
        *,
        expect_reply: bool,
        attempts: int = 3,
        pause_s: float = 0.2,
    ) -> str:
        last_error = None  # type: Optional[BaseException]
        payload = (command.rstrip() + "\n").encode()

        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    self.recover_transport()
                    time.sleep(0.5)
                fd = os.open(self.device, os.O_RDWR)
                try:
                    os.write(fd, payload)
                    if not expect_reply:
                        if pause_s:
                            time.sleep(pause_s)
                        return ""
                    time.sleep(pause_s)
                    reply = os.read(fd, 4096)
                finally:
                    os.close(fd)
                text = reply.decode("utf-8", "replace").strip()
                if not text:
                    raise TimeoutError("empty reply for {!r}".format(command))
                return text
            except (OSError, TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt == attempts:
                    break

        assert last_error is not None
        raise last_error

    def write_only(self, command: str, *, attempts: int = 3, pause_s: float = 0.0) -> None:
        self._transact(command, expect_reply=False, attempts=attempts, pause_s=pause_s)

    def query_text(self, command: str, *, attempts: int = 3, pause_s: float = 0.3) -> str:
        return self._transact(command, expect_reply=True, attempts=attempts, pause_s=pause_s)

    def query_float(self, command: str, *, attempts: int = 3, pause_s: float = 0.3) -> float:
        return float(self.query_text(command, attempts=attempts, pause_s=pause_s))

    def query_optional_float(
        self, command: str, *, attempts: int = 2, pause_s: float = 0.3
    ) -> float:
        try:
            return self.query_float(command, attempts=attempts, pause_s=pause_s)
        except Exception:
            return float("nan")

    def recover_transport(self) -> None:
        """Reset the USBTMC transport without assuming a healthy read path."""
        self._unbind_bind_interface()
        self._wait_for_device()

    def _unbind_bind_interface(self) -> None:
        unbind = pathlib.Path("/sys/bus/usb/drivers/usbtmc/unbind")
        bind = pathlib.Path("/sys/bus/usb/drivers/usbtmc/bind")
        try:
            unbind.write_text(self.interface_name)
        except OSError:
            pass
        time.sleep(0.5)
        try:
            bind.write_text(self.interface_name)
        except OSError:
            pass

    def _wait_for_device(self, timeout_s: float = 5.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.device.exists():
                return
            time.sleep(0.1)
        raise TimeoutError(f"{self.device} did not reappear after transport reset")

    def status(self) -> SupplyStatus:
        output_text = self.query_text(":OUTP?")
        return SupplyStatus(
            output_enabled=output_text.strip() == "1",
            source_volts=self.query_optional_float(":SOUR:VOLT?"),
            measured_volts=self.query_float(":MEAS:VOLT?"),
            measured_amps=self.query_optional_float(":MEAS:CURR?"),
        )

    def _wait_for_status(
        self,
        *,
        describe: str,
        predicate: Callable[[SupplyStatus], bool],
        timeout_s: float,
        poll_s: float = 0.5,
    ) -> SupplyStatus:
        deadline = time.time() + timeout_s
        last_status = None  # type: Optional[SupplyStatus]
        last_error = None  # type: Optional[BaseException]
        while time.time() < deadline:
            try:
                last_status = self.status()
                if predicate(last_status):
                    return last_status
            except Exception as exc:
                last_error = exc
            time.sleep(poll_s)

        if last_status is not None:
            raise RuntimeError(
                "timed out waiting for {} (last status: {})".format(
                    describe,
                    ", ".join(last_status.format_lines()),
                )
            )
        if last_error is not None:
            raise RuntimeError(
                "timed out waiting for {} (last error: {})".format(describe, last_error)
            )
        raise RuntimeError("timed out waiting for {}".format(describe))

    def on(
        self,
        *,
        verify_timeout_s: float = 10.0,
        min_measured_volts: float = 10.0,
    ) -> SupplyStatus:
        self.write_only(":OUTP ON", pause_s=0.2)
        return self._wait_for_status(
            describe="output ON with measured voltage >= {:.1f} V".format(
                min_measured_volts
            ),
            predicate=lambda s: s.output_enabled and s.measured_volts >= min_measured_volts,
            timeout_s=verify_timeout_s,
        )

    def off(
        self,
        *,
        verify_timeout_s: float = 12.0,
        max_measured_volts: float = 1.0,
        max_measured_amps: float = 0.05,
    ) -> SupplyStatus:
        self.write_only(":OUTP OFF", pause_s=0.2)
        return self._wait_for_status(
            describe="output OFF with measured voltage <= {:.1f} V and current <= {:.3f} A".format(
                max_measured_volts, max_measured_amps
            ),
            predicate=lambda s: (
                not s.output_enabled
                and s.measured_volts <= max_measured_volts
                and (
                    math.isnan(s.measured_amps)
                    or abs(s.measured_amps) <= max_measured_amps
                )
            ),
            timeout_s=verify_timeout_s,
        )

    def cycle(
        self,
        *,
        off_delay_s: float,
        settle_s: float,
        verify_timeout_s: float = 12.0,
    ) -> SupplyStatus:
        self.off(verify_timeout_s=verify_timeout_s)
        time.sleep(off_delay_s)
        # The driver tends to wedge across OFF->ON. Reset the transport before ON.
        self.recover_transport()
        status = self.on(verify_timeout_s=verify_timeout_s)
        time.sleep(settle_s)
        return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("status", "on", "off", "cycle"),
        help="SCPI action to perform",
    )
    parser.add_argument(
        "--device",
        default="/dev/usbtmc0",
        help="USBTMC character device path",
    )
    parser.add_argument(
        "--off-delay",
        type=float,
        default=2.5,
        help="Seconds to hold output OFF during cycle",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=0.5,
        help="Seconds to wait after final ON",
    )
    parser.add_argument(
        "--verify-timeout",
        type=float,
        default=12.0,
        help="Seconds to wait for verified state changes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ctl = Keithley2460(args.device)

    if args.action == "status":
        status = ctl.status()
    elif args.action == "on":
        status = ctl.on(verify_timeout_s=args.verify_timeout)
    elif args.action == "off":
        status = ctl.off(verify_timeout_s=args.verify_timeout)
    else:
        status = ctl.cycle(
            off_delay_s=args.off_delay,
            settle_s=args.settle,
            verify_timeout_s=args.verify_timeout,
        )

    for line in status.format_lines():
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
