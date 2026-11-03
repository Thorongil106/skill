#!/usr/bin/env python3
"""Portable helper checks use synthetic pages and printed-label TSV only."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from portable_helper import parse_tsv, page_size, render, executable
from pdf_library import Library


def main():
    tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
           '5\t1\t1\t1\t1\t10\t20\t30\t10\t95\tII90DXT\n'
           '5\t1\t1\t1\t1\t40\t20\t45\t10\t85\t0215S:416A\n')
    rows = parse_tsv(tsv, 100, 200)
    assert rows[0]['text'] == 'II90DXT 0215S:416A'
    assert rows[0]['box'] == [0.1, 0.1, 0.75, 0.05]
    assert .85 <= rows[0]['confidence'] <= .95
    for bad in ['not TSV', tsv.replace('\t95\t', '\tnan\t')]:
        try:
            parse_tsv(bad, 100, 200)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid TSV accepted')
    try:
        executable('slip-deliberately-missing-executable')
    except ValueError as error:
        assert 'unavailable' in str(error)
    else:
        raise AssertionError('Missing dependency not reported')
    with tempfile.TemporaryDirectory(prefix='slip-portable-test-') as folder:
        root = Path(folder).resolve() / '中文 path with spaces';root.mkdir()
        source = root / 'vector.pdf'
        writer = PdfWriter();page = writer.add_blank_page(width=72, height=144)
        stream = DecodedStreamObject();stream.set_data(b'1 0 0 rg 0 0 36 72 re f')
        page[NameObject('/Contents')] = writer._add_object(stream)
        page.rotate(90)
        with source.open('wb') as out: writer.write(out)
        assert page_size(source, 1, 72) == (144, 72)
        for number, dpi in [(0, 72), (2, 72), (1, -1)]:
            try: page_size(source, number, dpi)
            except ValueError: pass
            else: raise AssertionError('Invalid page or DPI accepted')
        available = any(importlib.util.find_spec(n) for n in ('pymupdf', 'fitz')) or shutil.which('pdftoppm')
        if available:
            destination = root / 'output.png'
            result = render(source, 1, 72, destination)
            with Image.open(destination) as im:
                assert im.size == (144,72)
                pixels = im.convert('RGB').tobytes()
                assert any(pixels[i] > 200 and pixels[i+1] < 30 and pixels[i+2] < 30 for i in range(0,len(pixels),3))
            try: render(source, 1, 72, destination)
            except ValueError as error: assert 'exists' in str(error)
            else: raise AssertionError('Existing output overwritten')
            library = Library(root / 'library.json')
            library.register(SimpleNamespace(id='vector', pdf=str(source), title='Synthetic', kind='infrared', pages='1'))
            meta = library.image('vector',1,dpi=72)
            assert meta['method'] == result['renderer'] + '-render'
            assert (meta['width'],meta['height']) == (144,72)
            print('PASS: real '+result['renderer']+' render and default Python helper integration; rotated page, vector content, spaced/Unicode paths, bounds and non-overwrite checks.')
        else:
            print('SKIP: live rendering needs installed PyMuPDF or Poppler.')
    print('PASS: OCR TSV line grouping, top-left boxes, confidence, malformed input and missing dependency handling.')
    print('NOTE: TSV fixtures test OCR conversion, not live Tesseract recognition accuracy.')


if __name__ == '__main__': main()
