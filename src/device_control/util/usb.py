from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_USB_SYSFS = Path("/sys/bus/usb/devices")
DEVICE_NODE_PREFIXES = ("ttyUSB", "ttyACM", "usbtmc", "hidraw", "cdc-wdm")


@dataclass(frozen=True)
class UsbDevice:
    """Information read from Linux USB sysfs."""

    sysfs_name: str
    busnum: str | None
    devnum: str | None
    vendor_id: str
    product_id: str
    manufacturer: str | None
    product: str | None
    serial: str | None
    speed: str | None
    device_nodes: tuple[str, ...]
    drivers: tuple[str, ...]

    def asdict(self) -> dict:
        return asdict(self)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _driver_name(path: Path) -> str | None:
    try:
        return path.resolve().name
    except OSError:
        return None


def _sorted_unique(values: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))


def _belongs_to_device(root: Path, path: Path) -> bool:
    for parent in path.parents:
        if parent == root:
            return True
        if (parent / "idVendor").exists() and (parent / "idProduct").exists():
            return False
    return True


def _device_nodes(root: Path) -> tuple[str, ...]:
    names = []
    try:
        paths = root.rglob("*")
    except OSError:
        return ()

    for path in paths:
        if not _belongs_to_device(root, path):
            continue
        if path.name.startswith(DEVICE_NODE_PREFIXES):
            node = Path("/dev") / path.name
            if node.exists():
                names.append(str(node))
    return _sorted_unique(names)


def _drivers(root: Path) -> tuple[str, ...]:
    paths = []
    try:
        paths = list(root.rglob("driver"))
    except OSError:
        return ()
    return _sorted_unique(_driver_name(path) for path in paths if _belongs_to_device(root, path))


def _usb_device_from_sysfs(path: Path) -> UsbDevice | None:
    vendor_id = _read_text(path / "idVendor")
    product_id = _read_text(path / "idProduct")
    if vendor_id is None or product_id is None:
        return None

    return UsbDevice(
        sysfs_name=path.name,
        busnum=_read_text(path / "busnum"),
        devnum=_read_text(path / "devnum"),
        vendor_id=vendor_id,
        product_id=product_id,
        manufacturer=_read_text(path / "manufacturer"),
        product=_read_text(path / "product"),
        serial=_read_text(path / "serial"),
        speed=_read_text(path / "speed"),
        device_nodes=_device_nodes(path),
        drivers=_drivers(path),
    )


def list_usb_devices(sysfs_root: Path = DEFAULT_USB_SYSFS) -> list[UsbDevice]:
    """List USB devices visible through Linux sysfs."""

    if not sysfs_root.exists():
        return []

    devices = []
    for path in sorted(sysfs_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir():
            continue
        device = _usb_device_from_sysfs(path)
        if device is not None:
            devices.append(device)

    return sorted(
        devices,
        key=lambda item: (
            int(item.busnum or 0),
            int(item.devnum or 0),
            item.vendor_id,
            item.product_id,
        ),
    )


def _format_device(device: UsbDevice) -> dict[str, str]:
    return {
        "bus": device.busnum or "-",
        "dev": device.devnum or "-",
        "vid:pid": f"{device.vendor_id}:{device.product_id}",
        "name": " ".join(part for part in (device.manufacturer, device.product) if part) or "-",
        "serial": device.serial or "-",
        "nodes": ",".join(device.device_nodes) or "-",
        "drivers": ",".join(device.drivers) or "-",
    }


def _print_table(devices: list[UsbDevice]) -> None:
    rows = [_format_device(device) for device in devices]
    columns = ("bus", "dev", "vid:pid", "name", "serial", "nodes", "drivers")
    widths = {
        column: max(len(column), *(len(row[column]) for row in rows))
        for column in columns
    }

    header = "  ".join(column.upper().ljust(widths[column]) for column in columns)
    print(header)
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(row[column].ljust(widths[column]) for column in columns))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List connected USB devices")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--sysfs-root",
        type=Path,
        default=DEFAULT_USB_SYSFS,
        help="USB sysfs root for testing or nonstandard systems",
    )
    args = parser.parse_args(argv)

    devices = list_usb_devices(args.sysfs_root)
    if args.json:
        print(json.dumps([device.asdict() for device in devices], indent=2))
    else:
        if devices:
            _print_table(devices)
        else:
            print(f"No USB devices found under {args.sysfs_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
