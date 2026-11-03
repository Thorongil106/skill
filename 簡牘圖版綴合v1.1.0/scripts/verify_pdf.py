#!/usr/bin/env python3
"""Check ID/face distinctions, source-pixel crops, provenance and stale caches."""
import tempfile
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from pdf_library import Library, normalize, ids, match_id, digest, helper_command


def main():
    assert normalize('Ⅱ 90DXT0216②：14') == 'II90DXT0216[2]:14'
    assert not match_id('Ⅱ90DXT0216②:14', 'II90DXT02162:14')
    assert ids('II90DXT02162:14', ocr=True) == ['II90DXT0216[2]:14']
    assert not match_id('Ⅱ90DXT0215S:416A', 'Ⅱ90DXT0215S:416B')
    assert not match_id('Ⅱ90DXT0215S:416', 'Ⅱ90DXT0215S:4160')
    assert match_id('Ⅱ90DXT0215S:416', 'Ⅱ90DXT0215S:416A')
    assert helper_command('tools with spaces/helper.py')[-1] == 'tools with spaces/helper.py'
    with tempfile.TemporaryDirectory(prefix='slip-pdf-test-') as folder:
        root = Path(folder)
        pdf = root / 'scan.pdf'
        im = Image.new('RGB', (120, 160), 'white')
        for x in range(20, 100):
            for y in range(30, 140):
                im.putpixel((x, y), (x * 2, y, 80))
        im.save(pdf, 'PDF')
        original_hash = digest(pdf)
        library = Library(root / 'library.json')
        for key, kind in [('ir', 'infrared'), ('color', 'color')]:
            library.register(SimpleNamespace(id=key, pdf=str(pdf), title='Fixture', kind=kind, pages='1'))
        page = library.image('ir', 1)
        args = SimpleNamespace(pdf_id='ir', page=1, helper=None, box=[10, 20, 80, 100],
                               slip='Ⅱ90DXT0215S:416A', label='Ⅱ90DXT0215S:416A',
                               printed_page='1', output=str(root / 'crop.png'))
        result = library.crop(args)
        with Image.open(page['image']) as source, Image.open(result['image']) as crop:
            assert source.crop((10, 20, 90, 120)).tobytes() == crop.tobytes()
        assert result['pdfSha256'] == original_hash == digest(pdf)
        assert result['imageSha256'] == digest(result['image'])
        assert library.search(args.slip, 'infrared')['matches'][0]['status'] == 'visually-verified'
        assert not library.search(args.slip, 'color')['matches']
        assert not Path(library.data['pdfs']['ir']['path']).is_absolute()
        provenance = json.loads((root / 'crop.source.json').read_text(encoding='utf-8'))
        assert provenance['image'] == 'crop.png'
        # Move the entire project, including relative registry, page cache and crop.
        with tempfile.TemporaryDirectory(prefix='slip-relocate-') as moved_folder:
            moved = Path(moved_folder).resolve() / '新設備 with spaces'
            shutil.copytree(root, moved)
            moved_pdf = moved / 'scan.pdf'
            os.utime(moved_pdf, ns=(1_000_000_000, 2_000_000_000))
            migrated = Library(moved / 'library.json')
            assert Path(migrated.source('ir')['path']) == moved_pdf
            assert Path(migrated.image('ir', 1)['image']).is_relative_to(moved)
            found = migrated.search(args.slip, 'infrared')['matches'][0]
            assert Path(found['image']) == moved / 'crop.png'
            assert Path(found['provenance']).is_file()
            assert not found.get('stale')
            # Relink a same-content PDF, but reject a different scan.
            relocated_pdf = moved / '書籍 elsewhere.pdf'
            moved_pdf.rename(relocated_pdf)
            migrated.relink(SimpleNamespace(pdf_id='ir', pdf=str(relocated_pdf)))
            assert migrated.search(args.slip, 'infrared')['matches'][0]['pdfPath'] == str(relocated_pdf)
            different = moved / 'different.pdf'
            different.write_bytes(relocated_pdf.read_bytes() + b'\n')
            try:
                migrated.relink(SimpleNamespace(pdf_id='ir', pdf=str(different)))
            except ValueError as error:
                assert 'Different PDF' in str(error)
            else:
                raise AssertionError('Relink must reject changed scan')
            # Existing absolute-path libraries remain readable; relink normalizes them.
            migrated.data['pdfs']['ir']['path'] = str(relocated_pdf)
            migrated.save()
            assert migrated.source('ir')['sha256'] == original_hash
            migrated.relink(SimpleNamespace(pdf_id='ir', pdf=str(relocated_pdf)))
            assert not Path(migrated.data['pdfs']['ir']['path']).is_absolute()
        try:
            library.crop(args)
        except ValueError as error:
            assert 'exists' in str(error)
        else:
            raise AssertionError('Must not overwrite prior crop')
        args.output = str(root / 'invalid.png')
        args.box = [100, 100, 80, 80]
        try:
            library.crop(args)
        except ValueError as error:
            assert 'bounds' in str(error)
        else:
            raise AssertionError('Out-of-bounds crop accepted')
        pdf.write_bytes(pdf.read_bytes() + b'\n')
        try:
            library.search(args.slip, 'infrared')
        except ValueError as error:
            assert 'changed' in str(error)
        else:
            raise AssertionError('Stale PDF accepted')
    print('PASS: registry, ID distinctions, exact crop, relative provenance, moved workspace/cache, changed timestamp with identical bytes, relink identity check, legacy absolute path, image-kind and changed-source rejection.')


if __name__ == '__main__':
    main()
