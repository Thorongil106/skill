#!/usr/bin/env python3
"""Read-only capability check. Never installs packages or searches user files."""
import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', help='Optional existing Node executable path')
    parser.add_argument('--sharp-module', help='Optional existing sharp module path')
    args = parser.parse_args()
    packages = {name: importlib.util.find_spec(name) is not None for name in ('pypdf', 'PIL', 'fitz', 'pymupdf')}
    commands = {name: shutil.which(name) for name in ('node', 'tesseract', 'pdftoppm', 'swiftc')}
    if args.node:
        commands['node'] = args.node
    for name, variable in [('tesseract', 'SLIP_TESSERACT'), ('pdftoppm', 'SLIP_PDFTOPPM')]:
        if os.environ.get(variable):
            commands[name] = shutil.which(os.environ[variable])
    sharp = {'available': False}
    if commands['node']:
        probe = "const c=require(process.argv[1]); const s=c.loadSharp(process.argv[2]||undefined); console.log(JSON.stringify(s.versions));"
        try:
            result = subprocess.run([commands['node'], '-e', probe, str(Path(__file__).with_name('compose.cjs')),
                                     args.sharp_module or ''], capture_output=True, text=True, timeout=30)
            sharp = {'available': result.returncode == 0}
            if result.returncode == 0:
                sharp['versions'] = json.loads(result.stdout)
            else:
                sharp['error'] = result.stderr.strip()
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            sharp['error'] = str(error)
    print(json.dumps({'platform': platform.system(), 'python': sys.version.split()[0],
                     'pythonExecutable': sys.executable, 'packages': packages,
                     'commands': commands, 'sharp': sharp,
                     'capabilities': {'composeImages': sharp['available'],
                                      'extractScanPDF': packages['pypdf'] and packages['PIL'],
                                      'portableRender': packages['fitz'] or packages['pymupdf'] or bool(commands['pdftoppm']),
                                      'portableOCR': bool(commands['tesseract'])},
                     'note': 'Capabilities report availability, not OCR accuracy. Missing optional OCR does not block image joining.'},
                    ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
