# RTLSDR MeshCore LoRa decoder (Windows)

Standalone Windows decoder for MeshCore traffic on 915 MHz / AU915 using an RTL-SDR dongle (NESDR, etc.). IQ is shifted and fed to lorarx for LoRa PHY demod; output is compact JSON with sync word 0x12, full PHY hex, MeshCore packet parse, and optional GRP_TXT decrypt via channels.txt.

Features

- AU915 narrow default (916.575 MHz, 62.5 kHz, SF7) and 915 MHz / 125 kHz preset
- Auto AFC / near-miss IQ tuning
- Pretty JSON capture file (-o captures.json)
- Built from OE5DXL lorarx (Windows port) + OpenWebRX+ demod parameters

```
RTL-SDR  →  Python (IQ shift)  →  lorarx.exe  →  JSON  →  MeshCore + channel decrypt
```

**Defaults (AU915 narrow):** 916.575 MHz, 62.5 kHz BW (`--bw 6`), SF7, MeshCore sync `0x12`.

**Platform:** Windows 10/11 only (RTL-SDR + `lorarx.exe`).

**Quick start:**

```bat
activate_meshcore.bat
meshcore.bat --gain 40 --ppm -15 -o captures.json -v
```

---

## Project layout

```
final/                        ← you are here (copy/share this whole folder)
├── README.md                 This file
├── requirements.txt          pip dependencies
├── environment.yml           conda environment spec
├── pyproject.toml            optional: pip install -e .
├── activate_meshcore.bat     activate conda env + PATH
├── meshcore.bat              run decoder (shortcut)
├── invoke_build.cmd          build lorarx.exe (VS2019)
├── build_lorarx.bat          MSVC compile script
├── channels.example.txt      channel key format
├── channels.txt              your keys (create locally, gitignored)
├── bin/                      lorarx.exe + librtlsdr.dll (see bin/README.md)
└── src/                      Python + lorarx C sources
    ├── meshcore_win.py       main entry (RTL-SDR → lorarx → JSON)
    ├── meshcore_common.py    IQ shift, lorarx cmd, TCP fan-out
    ├── meshcore_packet.py    MeshCore app-layer parse
    ├── meshcore_crypto.py    GRP_TXT channel decrypt
    └── lorarx-src/           OE5DXL lorarx sources (Windows port)
```

---

## Prerequisites

| Item | Purpose |
|------|---------|
| **Windows 10/11** | Target platform |
| **Miniconda or Anaconda** | Python 3.11 env |
| **Visual Studio 2019** (x64) | Build `lorarx.exe` once |
| **Zadig + WinUSB** | RTL-SDR USB driver |
| **NESDR / RTL-SDR** | 915 MHz capable dongle |

---

## 1. Python environment

### Option A — Conda (recommended)

Adjust `MESHCORE_CONDA` if Miniconda is not at `K:\Miniconda3`:

```bat
set MESHCORE_CONDA=C:\Users\You\Miniconda3
```

Create and activate:

```bat
cd D:\meshcore\mc_decode\final
conda env create -f environment.yml
activate_meshcore.bat
```

Or manually:

```bat
conda create -n meshcore-decode python=3.11 numpy scipy pip -y
conda activate meshcore-decode
pip install -r requirements.txt
```

### Option B — pip only (existing Python 3.10+)

```bat
cd D:\meshcore\mc_decode\final
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set PATH=%CD%\bin;%PATH%
```

### Option C — editable install

```bat
conda activate meshcore-decode
pip install -e .
meshcore-decode --gain 40 --ppm -15 -v
```

### Verify Python

```bat
python -c "import numpy, scipy, rtlsdr, cryptography; print('ok')"
```

---

## 2. RTL-SDR driver (Zadig)

1. Plug in the RTL-SDR.
2. Run [Zadig](https://zadig.akeo.ie/).
3. Options → list all devices → select **Bulk-In, Interface 0** (RTL2832).
4. Install **WinUSB** driver.

---

## 3. `librtlsdr.dll` (Windows)

`pyrtlsdr` needs `librtlsdr.dll` on `PATH`.

1. Download [rtlsdr-bin-w64_static.zip](https://github.com/librtlsdr/librtlsdr/releases/download/v0.9.0/rtlsdr-bin-w64_static.zip).
2. Extract `librtlsdr.dll` → copy to:

   ```
   bin\librtlsdr.dll
   ```

`activate_meshcore.bat` and `meshcore.bat` add `bin\` to `PATH` automatically.

---

## 4. Build `lorarx.exe` or use included binary

One-time build with **VS 2019 x64** (not required when using included binary):

```bat
invoke_build.cmd
```

Or open **x64 Native Tools Command Prompt for VS 2019** and run:

```bat
cd D:\meshcore\mc_decode\final
build_lorarx.bat
```

Output: `bin\lorarx.exe`

Test:

```bat
bin\lorarx.exe -h
```

---

## 5. Channel keys (GRP_TXT decrypt)

Copy the example and add your keys:

```bat
copy channels.example.txt channels.txt
notepad channels.txt
```

Format (hash = `SHA256(key)[0]`):

```
11:8b3387e9c5cdea6ac9e5edbaa115cd72
```

`channels.txt` is gitignored — do not commit secrets.
11 : is the Meshcore public channel

---

## 6. Run

### AU915 narrow (default)

MeshCore narrow channel — **916.575 MHz**, **62.5 kHz**, SF7. No extra flags needed:

```bat
activate_meshcore.bat
meshcore.bat --gain 40 --ppm -15 -v
```

Save to a formatted JSON file:

```bat
meshcore.bat --gain 40 --ppm -15 -o captures.json -v
```

### AU915 / Custom example 915.8 MHz (125 kHz)

Custom MeshCore traffic at **915.800 MHz**, **125 kHz**, SF7:

```bat
meshcore.bat --freq 915800000 --bw 7 --gain 40 --ppm -15 -o captures.json -v
```

### Other useful commands

Console only, compact one-line JSON (default):

```bat
python src\meshcore_win.py --gain 40 --ppm -15 -v
```

Indented JSON on console:

```bat
meshcore.bat --gain 40 --ppm -15 --pretty-console -v
```

Near-miss tuning (sync OK, LoRa CRC bad — PHY only, no MeshCore parse):

```bat
meshcore.bat --gain 40 --ppm -15 --analyze -v
```

Show all lorarx frames including bad CRC:

```bat
meshcore.bat --no-strict -v
```

Raw lorarx JSON (no MeshCore app parse):

```bat
meshcore.bat --raw-json -v
```

Manual AFC offset (Hz) from a near-miss `afc=` value in the log:

```bat
meshcore.bat --gain 40 --ppm -15 --shift-hz -11000 -v
```

---

## 7. Output format

Each decoded packet is **one JSON object**.

### Example: GRP_TXT (decrypted)

```json
{
  "ts": "2026-06-30T12:00:00Z",
  "freq_hz": 916575000,
  "region": "AU915",
  "phy": {
    "sync_hex": "12",
    "hex": "1220031e...a1b2",
    "header_hex": "20031e",
    "lora_crc_hex": "a1b2",
    "sf": 7,
    "bw": 62500,
    "cr": 5,
    "snr_db": 8.6,
    "afc_hz": -11024,
    "preamb": 17,
    "crc_ok": true
  },
  "packet": {
    "len": 37,
    "hex": "..."
  },
  "meshcore": {
    "route": "FLOOD",
    "type": "GRP_TXT",
    "path": ["CD", "89", "..."],
    "channel_hash": "11",
    "encrypted": false,
    "message": "TestUser: hello"
  }
}
```


### Field reference

| Field | Meaning |
|-------|---------|
| **`ts`** | UTC capture time (ISO 8601) |
| **`freq_hz`** | RX centre frequency |
| **`phy.sync_hex`** | LoRa sync word (`12` = MeshCore net 18) |
| **`phy.hex`** | Full PHY dump: sync + LoRa header + payload + LoRa CRC (from lorarx) |
| **`phy.header_hex`** | 3-byte LoRa explicit header (`20` = len 32, `03` = CRC on + CR 4/5, …) |
| **`phy.lora_crc_hex`** | 2-byte LoRa payload CRC |
| **`phy.crc_ok`** | LoRa payload CRC passed |
| **`packet.hex`** | MeshCore app bytes (after LoRa demod) — flags, path, body |
| **`meshcore`** | Parsed route / type / path / decrypt |

### `phy.hex` vs `packet.hex`

```
phy.hex:     12 | 20031e | aa....67 | 9d1c
             sync  header    app payload    LoRa CRC

packet.hex:  aa....67
             └── MeshCore frame only (byte 0 = route/type flags)
```



### Capture file (`-o`)

`captures.json` is a pretty-printed JSON **array**. Each new packet appends and rewrites the whole file:

```json
[
  { "ts": "...", "freq_hz": 916575000, "phy": { ... }, "packet": { ... }, "meshcore": { ... } },
  { "ts": "...", ... }
]
```

Safe to stop and restart — existing records are kept.

---

## 8. Common options

### Frequency / LoRa

| Option | Default | Description |
|--------|---------|-------------|
| `--freq` | `916575000` | Centre frequency (Hz) |
| `--bw` | `6` | lorarx BW index: `6` = 62.5 kHz, `7` = 125 kHz |
| `--spreading` | `7` | SF list, e.g. `--spreading 7 8` |
| `--cr` | `0` | Coding rate 5–8; `0` = from LoRa header |
| `--net` | `18` | MeshCore sync filter (`0x12`) |

### RTL-SDR / tuning

| Option | Description |
|--------|-------------|
| `--gain 40` | RF gain (`auto` if omitted) |
| `--ppm -15` | RTL freq correction + lorarx `-P` |
| `--shift-hz` | Manual IQ offset (Hz) |
| `--auto-shift` / `--no-auto-shift` | Tune from near-miss frames (default: on) |
| `--track-afc` | Also tune from good-CRC frames (default: off) |

### Output

| Option | Description |
|--------|-------------|
| `-o FILE` / `--output FILE` | Pretty JSON array capture file |
| `--pretty-console` | Indented JSON on console |
| `--packet-gap` / `--no-packet-gap` | Blank line between packets (default: on) |
| `--strict` / `--no-strict` | Only `net=18` + `crc=1` (default: strict on) |
| `--analyze` | Also show net=18 / bad CRC (PHY only) |
| `--raw-json` | lorarx JSON only, no MeshCore parse |
| `-v` | Verbose logging |

### Decrypt

| Option | Description |
|--------|-------------|
| `--channel-key HASH:HEX` | GRP_TXT / GRP_DATA key (repeatable) |
| `--channels-file path` | Key file (default: `channels.txt`) |

### Other

| Option | Description |
|--------|-------------|
| `--tcp-out PORT` | Mirror JSON lines to TCP clients |
| `--device-index N` | RTL-SDR device index |
| `--lorarx path` | Path to `lorarx.exe` |

Full help:

```bat
python src\meshcore_win.py --help
```

### BW index quick reference

| `--bw` | Bandwidth |
|--------|-----------|
| 6 | 62.5 kHz (AU narrow default) |
| 7 | 125 kHz |

---

## 9. Troubleshooting

### No output / only `DEBUG: drop frame`

- Need **`crc:1`** and **`net:18`** for valid MeshCore.
- `near-miss` = sync OK, tuning off → auto-shift converges in ~10–20 s, or use `--shift-hz` from the `afc=` value in the log.
- Try `--ppm -15` (or nudge ±5).

### `Found Rafael Micro R820T/2` but no device

- Zadig WinUSB not installed, or wrong USB port.
- Check `librtlsdr.dll` is in `bin\`.

### `lorarx not found`

Run `invoke_build.cmd` and confirm `bin\lorarx.exe` exists.

### `cryptography` / import errors

```bat
pip install cryptography scipy pyrtlsdr
```

### `frame deleted, wrong sync word 12` in lorarx stderr

Harmless for JSON output — lorarx UDP-raw path message. JSON still has `phy.sync_hex: "12"` and `crc_ok: true`.

### Wrong path / empty `message`

Ensure `channels.txt` has the correct `HASH:hexkey` for the packet's `channel_hash`.

---

## 10. Rebuild lorarx (after C changes)

If you modify `src\lorarx-src\` (e.g. `phy_hex` in JSON):

```bat
invoke_build.cmd
```

---

## Credits and licenses

This project combines several upstream works. Please respect their licenses and attribution when redistributing.

### LoRa PHY demodulator — lorarx

- **Author:** OE5DXL
- **Site:** [oe5dxl.hamspirit.at](http://oe5dxl.hamspirit.at:8025/)
- **What we use:** `lorarx` C sources in `src/lorarx-src/` (LoRa chirp demod, JSON output, `decodemeshcore()` in `loraprotocols.c`)
- **Windows port:** `port_win.c`, `build_lorarx.bat`, `invoke_build.cmd` in this repo
- **Modification:** JSON output extended with `phy_hex`, `phy_header_hex`, `phy_lora_crc_hex` fields

### MeshCore protocol parsing

- **Reference:** OE5DXL `mcd.py` and `loraprotocols.c` `decodemeshcore()` (path encoding, packet types, ADVERT layout)
- **MeshCore:** Liam Cottle [liamcottle.net](https://liamcottle.net/) — LoRa mesh firmware and app protocol (sync word `0x12`, AU915 parameters)
- **Python:** `meshcore_packet.py`, `meshcore_crypto.py` — app-layer parse and GRP_TXT decrypt (HMAC + AES-128-ECB)

### OpenWebRX+ demod parameters

- **Project:** [OpenWebRX+](https://github.com/luarvique/openwebrx)
- **What we use:** Default MeshCore AU915 narrow settings (916.575 MHz, 62.5 kHz BW, SF7, lorarx `-H 5`, `-X 18`)

### RTL-SDR stack

- **librtlsdr:** [osmocom rtl-sdr](https://osmocom.org/projects/rtl-sdr/wiki) — USB driver library (`librtlsdr.dll` on Windows)
- **pyrtlsdr:** [pyrtlsdr](https://github.com/pyrtlsdr/pyrtlsdr) — Python bindings for RTL-SDR

### Other dependencies

- **NumPy / SciPy** — IQ processing, resampling
- **cryptography** — channel key decrypt (AES-ECB, HMAC)

### This repository

Windows-only MeshCore LoRa decoder glue: RTL-SDR → Python IQ pipeline → lorarx → JSON → MeshCore parse. Not affiliated with the MeshCore firmware authors; community tooling for monitoring and research.
