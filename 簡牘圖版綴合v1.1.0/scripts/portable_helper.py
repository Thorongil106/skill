#!/usr/bin/env python3
"""Local, cross-platform PDF rendering and printed-label OCR.

The CLI mirrors plate_ocr.swift. Rendering uses installed PyMuPDF or Poppler;
OCR uses installed Tesseract. No dependency is downloaded or installed here.
OCR boxes are normalized top-left coordinates in the supplied image.
"""
import argparse
import csv
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


MAX_RENDER_PIXELS = 100_000_000


def executable(name, override=None):
    requested = os.environ.get(override, name) if override else name
    result = shutil.which(requested)
    if not result:
        hint = f' or set {override} to its executable path' if override else ''
        raise ValueError(f'{name} is unavailable. Use an environment with {name} installed{hint}.')
    return result


def parse_tsv(value, width, height):
    """Join Tesseract word rows into lines without losing full printed IDs."""
    if width <= 0 or height <= 0:
        raise ValueError('Invalid OCR image size')
    reader = csv.DictReader(io.StringIO(value), delimiter='\t', quoting=csv.QUOTE_NONE)
    required = {'level', 'page_num', 'block_num', 'par_num', 'line_num',
                'left', 'top', 'width', 'height', 'conf', 'text'}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise ValueError('Tesseract did not return the expected TSV fields')
    lines = {}
    for row in reader:
        if row['level'] != '5' or not (row['text'] or '').strip():
            continue
        try:
            confidence = float(row['conf'])
            x, y, w, h = (float(row[name]) for name in ('left', 'top', 'width', 'height'))
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid coordinates or confidence in Tesseract TSV') from error
        if not all(math.isfinite(n) for n in (confidence, x, y, w, h)):
            raise ValueError('Non-finite values in Tesseract TSV')
        if confidence < 0 or w <= 0 or h <= 0:
            continue
        left, top = max(0, x), max(0, y)
        right, bottom = min(width, x + w), min(height, y + h)
        if right <= left or bottom <= top:
            continue
        key = tuple(row[name] for name in ('page_num', 'block_num', 'par_num', 'line_num'))
        line = lines.setdefault(key, {'words': [], 'bounds': [], 'confidence': []})
        text = row['text'].strip()
        line['words'].append(text)
        line['bounds'].append((left, top, right, bottom))
        line['confidence'].append((min(confidence, 100) / 100, len(text)))
    observations = []
    for line in lines.values():
        left = min(b[0] for b in line['bounds'])
        top = min(b[1] for b in line['bounds'])
        right = max(b[2] for b in line['bounds'])
        bottom = max(b[3] for b in line['bounds'])
        weight = sum(n for _, n in line['confidence'])
        observations.append({
            'text': ' '.join(line['words']),
            # Confidence is a character-weighted aggregate of Tesseract scores,
            # not a probability that an archaeological identification is true.
            'confidence': sum(c * n for c, n in line['confidence']) / weight,
            'box': [left / width, top / height, (right - left) / width, (bottom - top) / height],
        })
    return observations


def ocr(image_path):
    from PIL import Image
    path = Path(image_path).resolve()
    if not path.is_file():
        raise ValueError(f'OCR image does not exist: {path}')
    with Image.open(path) as image:
        width, height = image.size
    language = os.environ.get('SLIP_OCR_LANG', 'eng').strip()
    if not language:
        raise ValueError('SLIP_OCR_LANG must name an installed Tesseract language, e.g. eng')
    command = [executable('tesseract', 'SLIP_TESSERACT'), str(path), 'stdout',
               '-l', language, '--psm', '11', 'tsv']
    run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                         errors='replace', timeout=60)
    if run.returncode:
        detail = (run.stderr or '').strip()
        raise ValueError(f'Tesseract OCR failed; check installed language data for {language!r}. {detail}')
    return parse_tsv(run.stdout, width, height)


def page_size(pdf_path, number, dpi):
    from pypdf import PdfReader
    if not math.isfinite(dpi) or dpi <= 0:
        raise ValueError('DPI must be a finite positive number')
    reader = PdfReader(pdf_path)
    if number < 1 or number > len(reader.pages):
        raise ValueError('PDF page is outside file bounds (pages are one-based)')
    page = reader.pages[number - 1]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    if int(page.rotation) % 180:
        width, height = height, width
    width, height = math.ceil(width * dpi / 72), math.ceil(height * dpi / 72)
    if min(width, height) <= 0 or width * height > MAX_RENDER_PIXELS:
        raise ValueError(f'Invalid or excessive render size: {width} x {height}')
    return width, height


def render(pdf_path, number, dpi, destination):
    from PIL import Image
    source = Path(pdf_path).resolve()
    dest = Path(destination).resolve()
    if not source.is_file():
        raise ValueError(f'PDF does not exist: {source}')
    if dest.exists():
        raise ValueError(f'Output already exists; choose another name: {dest}')
    if dest.suffix.lower() != '.png':
        raise ValueError('Render destination must have a .png extension')
    page_size(source, number, dpi)
    # New PyMuPDF versions provide pymupdf; older ones use the fitz name.
    module_name = next((n for n in ('pymupdf', 'fitz') if importlib.util.find_spec(n)), None)
    if module_name:
        pymupdf = importlib.import_module(module_name)
        if not hasattr(pymupdf, 'open') or not hasattr(pymupdf, 'Matrix'):
            raise ValueError('The installed fitz module is not PyMuPDF; use PyMuPDF or Poppler.')
        with pymupdf.open(str(source)) as doc:
            page = doc[number - 1]
            # Match Poppler's default MediaBox rendering, with page rotation.
            page.set_cropbox(page.mediabox)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
            data = pixmap.tobytes('png')
        renderer = 'PyMuPDF'
    else:
        tool = executable('pdftoppm', 'SLIP_PDFTOPPM')
        with tempfile.TemporaryDirectory(prefix='slip-render-') as folder:
            prefix = Path(folder) / 'page'
            command = [tool, '-f', str(number), '-l', str(number), '-r', str(dpi),
                       '-singlefile', '-png', str(source), str(prefix)]
            run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', timeout=90)
            if run.returncode:
                raise ValueError(f'Poppler PDF rendering failed: {(run.stderr or "").strip()}')
            rendered = prefix.with_suffix('.png')
            if not rendered.is_file():
                raise ValueError('Poppler completed without producing a PNG')
            data = rendered.read_bytes()
        renderer = 'Poppler-pdftoppm'
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if image.format != 'PNG' or width * height > MAX_RENDER_PIXELS:
            raise ValueError('Renderer produced an unexpected image')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('xb') as stream:
        stream.write(data)
    return {'rendered': True, 'renderer': renderer, 'dpi': dpi, 'width': width,
            'height': height, 'coordinateSpace': 'rendered-page-top-left'}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    recognition = commands.add_parser('ocr')
    recognition.add_argument('image')
    rendering = commands.add_parser('render')
    rendering.add_argument('pdf')
    rendering.add_argument('page', type=int)
    rendering.add_argument('dpi', type=float)
    rendering.add_argument('destination')
    args = parser.parse_args()
    try:
        result = ocr(args.image) if args.command == 'ocr' else render(
            args.pdf, args.page, args.dpi, args.destination)
    except (OSError, ValueError, ImportError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
