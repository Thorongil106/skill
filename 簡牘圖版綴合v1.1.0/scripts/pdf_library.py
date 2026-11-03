#!/usr/bin/env python3
"""Local PDF registry, incremental plate-label OCR, verified crop provenance.

Uses pypdf + Pillow; the portable render/OCR helper is the default.
An explicit macOS Vision/PDFKit helper remains supported.
All page numbers are ONE-based. No source files are modified.
"""
import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

logging.getLogger('pypdf').setLevel(logging.ERROR)


def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def stamp(path):
    s = Path(path).stat()
    return {'size': s.st_size, 'mtimeNs': s.st_mtime_ns}


def stored_path(path, base):
    """Store paths relative to their containing JSON; Windows drives may differ."""
    path = Path(path).resolve()
    try:
        return Path(os.path.relpath(path, Path(base).resolve())).as_posix()
    except ValueError:
        return str(path)


def resolved_path(value, base):
    return (Path(base) / Path(value)).resolve()


def record_paths(record, base, encode=False):
    """The same record has distinct bases in library, page-cache and crop JSON."""
    result = dict(record)
    for key in ('pdfPath', 'image', 'locator', 'provenance'):
        if result.get(key):
            result[key] = stored_path(result[key], base) if encode else str(resolved_path(result[key], base))
    if result.get('sourcePageImage'):
        result['sourcePageImage'] = record_paths(result['sourcePageImage'], base, encode)
    return result


def helper_command(helper=None):
    helper = str(helper or Path(__file__).with_name('portable_helper.py'))
    # Python scripts need an interpreter on Windows; argument arrays preserve spaces.
    return [sys.executable, helper] if Path(helper).suffix.lower() == '.py' else [helper]


def run_helper(helper, *args, timeout=90):
    try:
        return subprocess.run(helper_command(helper) + list(args), check=True,
                              capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise ValueError(f'Render/OCR helper failed: {detail}') from error


def normalize(value):
    # Protect layer markers BEFORE NFKC, which would erase their distinction.
    for i, char in enumerate('①②③④⑤⑥⑦⑧⑨', 1):
        value = value.replace(char, f'[{i}]')
    value = unicodedata.normalize('NFKC', value).upper()
    return re.sub(r'\s+', '', value).replace('：', ':')


ID = re.compile(r'(?<![A-Z0-9])I{1,3}90DXT\d{4}(?:S|\[\d\])(?:C)?[:：]\d+[AB]?')


def ids(text, ocr=False):
    normalized = normalize(text)
    if ocr:
        # OCR can drop the circle/bracket around a layer numeral. Repair only
        # the fixed trench+layer position; these remain unverified candidates.
        normalized = re.sub(r'(90DXT\d{4})[（(]?([1-9])[)）]?(?=:)', r'\1[\2]', normalized)
    return ID.findall(normalized)


def match_id(query, candidate):
    q, c = normalize(query), normalize(candidate)
    return c == q or (not q.endswith(('A', 'B')) and c in (q + 'A', q + 'B'))


def pages(spec, total):
    result = set()
    for term in spec.split(','):
        bounds = [int(n) for n in term.split('-')]
        if len(bounds) == 1:
            result.add(bounds[0])
        elif len(bounds) == 2 and bounds[0] <= bounds[1]:
            result.update(range(bounds[0], bounds[1] + 1))
        else:
            raise ValueError('Invalid page range')
    if not result or min(result) < 1 or max(result) > total:
        raise ValueError('PDF page outside file bounds')
    return sorted(result)


class Library:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.data = read(self.path, {'schema': 1, 'defaultKind': 'infrared', 'pdfs': {}, 'verified': []})

    def save(self):
        write(self.path, self.data)

    def source(self, key):
        source = self.data['pdfs'][key]
        path = resolved_path(source['path'], self.path.parent)
        if not path.is_file():
            raise ValueError(f'PDF unavailable: {path}. Use relink --pdf-id {key} --pdf NEW_PATH for the same file.')
        if stamp(path) != source['fingerprint']:
            if digest(path) != source['sha256']:
                raise ValueError(f'PDF changed; re-register and recheck cached locations: {path}')
            # Copies can have new timestamps without changing the scan or coordinates.
            source['fingerprint'] = stamp(path)
            self.save()
        return dict(source, path=str(path))

    def cache(self, key, page):
        source = self.source(key)
        tag = source['sha256'][:16]
        return self.path.parent / 'index' / key / tag / f'p{page:04d}'

    def image(self, key, page, helper=None, dpi=400):
        from pypdf import PdfReader
        from PIL import Image
        source = self.source(key)
        if page < 1 or page > source['pageCount']:
            raise ValueError('Page out of bounds')
        stem = self.cache(key, page)
        meta_path = stem.with_suffix('.image.json')
        meta = read(meta_path)
        if meta:
            cached = record_paths(meta, meta_path.parent)
            # Legacy cache records contain absolute paths. Prefer this cache's sibling
            # image after a workspace move; never silently read the old workspace.
            if Path(meta['image']).is_absolute():
                cached['image'] = str(stem.with_suffix(Path(meta['image']).suffix))
            if Path(cached['image']).is_file():
                if cached.get('pdfSha256') != source['sha256'] or digest(cached['image']) != cached['imageSha256']:
                    raise ValueError('Cached source page changed')
                cached['pdfPath'] = source['path']
                return cached
        stem.parent.mkdir(parents=True, exist_ok=True)
        p = PdfReader(source['path']).pages[page - 1]
        images = p.images
        # Scanned page with one correctly oriented full-page raster.
        # When labels/vector text are separate, render the PDF page instead.
        simple = len(images) == 1 and not (p.extract_text() or '').strip()
        if simple:
            im = images[0].image
            a = im.width / im.height
            b = float(p.mediabox.width / p.mediabox.height)
            simple = abs(a / b - 1) < .03
        if simple:
            raw = images[0]
            ext = Path(raw.name).suffix.lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.jp2', '.tif', '.tiff'):
                ext = '.png'
                dest = stem.with_suffix(ext)
                im.save(dest)
                method = 'decoded-embedded-image'
            else:
                dest = stem.with_suffix(ext)
                dest.write_bytes(raw.data)
                method = 'embedded-image'
            meta = {'image': str(dest), 'method': method, 'imageIndex': 0,
                    'width': im.width, 'height': im.height, 'pageRotation': p.rotation,
                    'coordinateSpace': 'raw-embedded-image-top-left'}
        else:
            dest = stem.with_suffix('.png')
            run = run_helper(helper, 'render', source['path'], str(page), str(dpi), str(dest))
            try:
                renderer = json.loads(run.stdout).get('renderer', 'external-helper')
            except (ValueError, AttributeError):
                renderer = 'external-helper'
            with Image.open(dest) as im:
                meta = {'image': str(dest), 'method': f'{renderer}-render', 'dpi': dpi,
                        'width': im.width, 'height': im.height, 'pageRotation': p.rotation,
                        'coordinateSpace': 'rendered-page-top-left'}
        meta.update({'pdfPage': page, 'pdfPath': source['path'], 'pdfSha256': source['sha256'],
                     'imageSha256': digest(dest)})
        write(meta_path, record_paths(meta, meta_path.parent, encode=True))
        return meta

    def register(self, args):
        from pypdf import PdfReader
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', args.id):
            raise ValueError('Use a simple ASCII registry id')
        path = Path(args.pdf).expanduser().resolve()
        reader = PdfReader(path)
        entry = {'path': stored_path(path, self.path.parent), 'title': args.title, 'kind': args.kind,
                 'pageCount': len(reader.pages), 'sha256': digest(path), 'fingerprint': stamp(path)}
        if args.pages:
            entry['platePages'] = pages(args.pages, len(reader.pages))
        old = self.data['pdfs'].get(args.id)
        if old and old['sha256'] != entry['sha256']:
            for record in self.data['verified']:
                if record['pdfId'] == args.id:
                    record['stale'] = True
        self.data['pdfs'][args.id] = entry
        self.save()
        return entry

    def relink(self, args):
        """Bind an existing source ID to the very same bytes at a new location."""
        source = self.data['pdfs'][args.pdf_id]
        path = Path(args.pdf).expanduser().resolve()
        if digest(path) != source['sha256']:
            raise ValueError('Different PDF content; use register and recheck cached locations, not relink')
        source.update(path=stored_path(path, self.path.parent), fingerprint=stamp(path))
        self.save()
        return dict(source, path=str(path))

    def index(self, args):
        from PIL import Image
        source = self.source(args.pdf_id)
        numbers = pages(args.pages, source['pageCount'])
        if source.get('platePages') and not set(numbers) <= set(source['platePages']):
            raise ValueError('Requested page lies outside registered plate range')
        for number in numbers:
            dest = self.cache(args.pdf_id, number).with_suffix('.ocr.json')
            if dest.exists() and not args.refresh:
                print(json.dumps({'page': number, 'cached': True}), flush=True)
                continue
            meta = self.image(args.pdf_id, number, args.helper)
            observations = []
            for angle in args.rotations:
                with Image.open(meta['image']) as original:
                    im = original.convert('RGB').rotate(angle, expand=True)
                    im.thumbnail((args.max_side, args.max_side))
                    with tempfile.TemporaryDirectory(prefix='slip-label-') as folder:
                        temp = Path(folder) / 'ocr.png'
                        im.save(temp)
                        run = run_helper(args.helper, 'ocr', str(temp), timeout=60)
                        rows = json.loads(run.stdout)
                for row in rows:
                    row.update({'rotationCCW': angle, 'ocrImageSize': list(im.size),
                                'candidateIds': ids(row['text'], ocr=True)})
                    observations.append(row)
            record = {'pdfId': args.pdf_id, 'pdfPage': number, 'kind': source['kind'],
                      'image': record_paths(meta, dest.parent, encode=True), 'observations': observations,
                      'candidateIds': sorted({v for row in observations for v in row['candidateIds']})}
            write(dest, record)
            print(json.dumps({'page': number, 'candidateIds': record['candidateIds']}, ensure_ascii=False), flush=True)

    def search(self, query, kind):
        matches, coverage = [], []
        for key, source in self.data['pdfs'].items():
            if source['kind'] != kind:
                continue
            current_source = self.source(key)
            records = list(self.cache(key, 1).parent.glob('p*.ocr.json'))
            coverage.append({'pdfId': key, 'indexedPages': len(records),
                             'platePages': len(source.get('platePages', [])) or None})
            for entry in self.data['verified']:
                if entry['pdfId'] == key and not entry.get('stale') and match_id(query, entry['slip']):
                    resolved = record_paths(entry, self.path.parent)
                    resolved['pdfPath'] = current_source['path']
                    if resolved.get('sourcePageImage'):
                        resolved['sourcePageImage']['pdfPath'] = current_source['path']
                    matches.append(dict(resolved, status='visually-verified'))
            for path in records:
                record = read(path)
                for row in record['observations']:
                    if any(match_id(query, value) for value in row['candidateIds']):
                        matches.append({'pdfId': key, 'pdfPage': record['pdfPage'],
                                        'status': 'OCR-candidate', 'observation': row})
        return {'query': query, 'kind': kind, 'matches': matches, 'coverage': coverage,
                'note': 'Partial OCR coverage is not evidence of absence. OCR hits require original-label verification.'}

    def crop(self, args):
        from PIL import Image, ImageDraw
        source = self.source(args.pdf_id)
        meta = self.image(args.pdf_id, args.page, args.helper)
        if digest(meta['image']) != meta['imageSha256']:
            raise ValueError('Cached source page changed')
        x, y, width, height = args.box
        if min(x, y) < 0 or min(width, height) <= 0 or x + width > meta['width'] or y + height > meta['height']:
            raise ValueError('Crop exceeds original page-image bounds')
        if not ids(args.slip) or normalize(args.slip) not in ids(args.slip):
            raise ValueError('Supply complete slip ID, including trench, layer and number')
        if normalize(args.slip) not in ids(args.label):
            raise ValueError('Transcribed label does not match requested full slip ID')
        output = Path(args.output).expanduser().resolve()
        check = output.with_name(output.stem + '-locator.jpg')
        prov = output.with_suffix('.source.json')
        if output.suffix.lower() != '.png':
            raise ValueError('Use PNG for lossless crop output')
        for dest in (output, check, prov):
            if dest.exists():
                raise ValueError(f'Output exists; use a new name: {dest}')
            if dest == Path(source['path']) or dest == Path(meta['image']):
                raise ValueError('Cannot overwrite a source')
        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(meta['image']) as im:
            im.crop((x, y, x + width, y + height)).save(output)
            locator = im.convert('RGB')
            ImageDraw.Draw(locator).rectangle((x, y, x + width, y + height), outline='red', width=max(3, im.width // 600))
            locator.thumbnail((1800, 1800))
            locator.save(check, quality=95)
        record = {'slip': args.slip, 'pdfId': args.pdf_id, 'kind': source['kind'],
                  'title': source['title'], 'pdfPath': source['path'], 'pdfSha256': source['sha256'],
                  'pdfPage': args.page, 'printedPage': args.printed_page,
                  'labelVerified': True, 'labelTranscription': args.label,
                  'sourcePageImage': meta, 'cropBoxXYWH': args.box,
                  'image': str(output), 'imageSha256': digest(output), 'locator': str(check)}
        write(prov, record_paths(record, prov.parent, encode=True))
        self.data['verified'] = [r for r in self.data['verified'] if not (
            normalize(r['slip']) == normalize(args.slip) and r['pdfId'] == args.pdf_id and r['pdfPage'] == args.page)]
        self.data['verified'].append(record_paths(dict(record, provenance=str(prov)), self.path.parent, encode=True))
        self.save()
        return record


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', default='.slip-join-plate/library.json')
    commands = parser.add_subparsers(dest='command', required=True)
    register = commands.add_parser('register')
    register.add_argument('--id', required=True)
    register.add_argument('--pdf', required=True)
    register.add_argument('--title', required=True)
    register.add_argument('--kind', choices=['infrared', 'color', 'mixed'], required=True)
    register.add_argument('--pages', help='Verified plate-page range, one-based PDF pages')
    relink = commands.add_parser('relink', help='Relocate an identical PDF, preserving verified page records')
    relink.add_argument('--pdf-id', required=True)
    relink.add_argument('--pdf', required=True)
    index = commands.add_parser('index')
    index.add_argument('--pdf-id', required=True)
    index.add_argument('--pages', required=True)
    index.add_argument('--helper', help='Optional executable or Python helper; defaults to portable_helper.py')
    index.add_argument('--rotations', type=int, nargs='+', default=[270], choices=[0, 90, 180, 270])
    index.add_argument('--max-side', type=int, default=3200)
    index.add_argument('--refresh', action='store_true')
    search = commands.add_parser('search')
    search.add_argument('--slip', required=True)
    search.add_argument('--kind', default='infrared', choices=['infrared', 'color', 'mixed'])
    image = commands.add_parser('page')
    image.add_argument('--pdf-id', required=True)
    image.add_argument('--page', type=int, required=True)
    image.add_argument('--helper')
    crop = commands.add_parser('crop')
    crop.add_argument('--pdf-id', required=True)
    crop.add_argument('--page', type=int, required=True)
    crop.add_argument('--slip', required=True)
    crop.add_argument('--printed-page', required=True)
    crop.add_argument('--label', required=True, help='Visible printed ID, transcribed after visual inspection')
    crop.add_argument('--box', type=int, nargs=4, required=True, metavar=('X', 'Y', 'WIDTH', 'HEIGHT'))
    crop.add_argument('--output', required=True)
    crop.add_argument('--helper')
    crop.add_argument('--label-verified', action='store_true', required=True)
    args = parser.parse_args()
    library = Library(args.library)
    if args.command == 'register':
        result = library.register(args)
    elif args.command == 'relink':
        result = library.relink(args)
    elif args.command == 'index':
        library.index(args)
        return
    elif args.command == 'search':
        result = library.search(args.slip, args.kind)
    elif args.command == 'page':
        result = library.image(args.pdf_id, args.page, args.helper)
    else:
        result = library.crop(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
