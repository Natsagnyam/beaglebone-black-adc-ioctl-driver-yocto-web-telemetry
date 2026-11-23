# Technical Manual — `bbb-freq-driver`

**Author:** Natska (Natsagnyam NAMKHAI)  
**License:** GNU General Public License v2.0 (GPL-2.0)  
**Repository:** `github.com/Natsagnyam/beaglebone-black-adc-ioctl-driver`  
**Launchpad PPA:** `ppa:natska/ppa`

---

## 1. Overview

`bbb-freq-driver` is an end-to-end embedded Linux kernel and userspace telemetry stack built for the BeagleBone Black (`armv7l` / `armhf`):

1. **Linux Kernel Character Driver (`freq_driver.ko`)** — Exposes `/dev/bbb_freq` with `read()` and `ioctl()` interfaces (`freq_ioctl.h`) for ADC0-to-frequency conversion (`45.000 Hz` – `65.000 Hz`, 12-bit `0–4095` ADC scale).
2. **Debian/Ubuntu DKMS Package (`bbb-freq-driver-dkms`)** — Automatically rebuilds and installs `freq_driver.ko` across kernel upgrades.
3. **Web Telemetry Server & Virtual POT Dashboard (`web/`)** — Zero-dependency Python 3 server (`simulated-bbb-web-server.py`) and SVG gauge UI (`index.html`) supporting both live hardware reads and interactive software simulation (`MOCK_TELEMETRY=1`).

---

## 2. Installing the Man Page Locally

View the Unix manual page directly from the repository:

```bash
man ./man/bbb-freq-driver.7
Or install it system-wide:Bashsudo install -D -m 0644 man/bbb-freq-driver.7 /usr/local/share/man/man7/bbb-freq-driver.7
sudo mandb
man bbb-freq-driver
3. Kernel Module & DKMS UsageBash# Load module
sudo modprobe freq_driver

# Verify device node and module status
ls -l /dev/bbb_freq
dkms status
4. Telemetry API ReferenceMethodEndpointRequest BodyDescriptionGET/api/frequencyNoneReturns {"adc_raw": int, "frequency_hz": float, "timestamp_ms": int, "mode": str}POST/api/pot{"adc_raw": 0..4095} or {"pot": 0.0..1.0}Sets manual Virtual POT ADC level (mode: "virtual-pot")POST/api/pot/resetNoneResets simulation back to automatic sine wave (mode: "auto-mock")5. License & AttributionCopyright © 2026 Natska (Natsagnyam NAMKHAI).Licensed under the GNU General Public License v2.0 (GPL-2.0) — see LICENSE for full terms.
