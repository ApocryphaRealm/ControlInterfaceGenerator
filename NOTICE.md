# Control Interface Generator - copyright and licence

Copyright (C) 2026 ApocryphaRealm

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program (`LICENSE`). If not, see
<https://www.gnu.org/licenses/>.

SPDX-License-Identifier: GPL-3.0-or-later

## What it builds on

CIG's own code (`cig/`, `bridges/`, `library/`, `config/`, `tools/`) is written for this project. `cig.exe` is a
PyInstaller bundle that also carries the Python runtime (Python Software Foundation License) and the packages CIG
imports - among them the Model Context Protocol Python SDK (`mcp`, MIT), `uiautomation` (Apache-2.0), `comtypes`
(MIT), `pywinauto` (BSD-3-Clause), `pywin32` (PSF), `psutil` (BSD-3-Clause), `Pillow` (MIT-CMU), `websockets`
(BSD-3-Clause) and `jsonschema` (MIT). Every bundled package, its version and its licence text are listed in
`THIRD-PARTY-NOTICES.txt`, which `tools/third_party_notices.py` writes from the build environment at each build and
which ships beside `cig.exe`. PyInstaller's bootloader is GPL-2.0-or-later with an exception that allows distributing
the bundles it builds.

Source code: https://github.com/ApocryphaRealm/ControlInterfaceGenerator
