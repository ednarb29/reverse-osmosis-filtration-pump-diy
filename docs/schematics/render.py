#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Renders the schematics: SVG -> PNG (for the README) and SVG -> PDF (for print).

generate.py writes the SVGs; this script turns them into the derived files that
are also checked in, so a contributor does not have to reconstruct the exact
chromium invocations. Run generate.py first, or pass --generate to do both.

    python3 docs/schematics/render.py --generate

Needs a headless Chromium or Chrome. Set CHROME to point at one if it is not on
PATH under a name this script already tries.

The PDFs are A3 landscape: the hydraulic drawing is too dense to stay legible
when it is squeezed onto A4, and printing A3 down to A4 is a checkbox away
whereas scaling up is not.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
IMAGES = os.path.join(REPO, 'images')

# name -> (width, height) of the SVG viewBox, which the PNG render needs as its
# window size. Keep in step with build_hydraulic / build_electrical.
DRAWINGS = {'hydraulic': (1740, 1640), 'electrical': (1740, 1320)}
LANGS = ('en', 'de')
PNG_SCALE = '1.25'

CHROME_CANDIDATES = ('chromium', 'chromium-browser', 'google-chrome',
                     'google-chrome-stable', 'chrome')


def find_chrome():
    env = os.environ.get('CHROME')
    if env:
        return env
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    sys.exit('No Chromium found. Set CHROME=/path/to/chromium and retry.')


def run_chrome(chrome, args, cwd):
    cmd = [chrome, '--headless', '--disable-gpu', '--no-sandbox',
           '--hide-scrollbars'] + args
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit('chromium failed:\n%s' % (res.stderr.strip() or res.stdout.strip()))


def wrap(svg_path, tmpdir, page_css=''):
    """Chromium sizes a bare .svg unpredictably, so always render it in a page."""
    with open(svg_path) as f:
        svg = f.read()
    # Drop the fixed width/height so the CSS below controls the scale.
    for attr in ('width', 'height'):
        svg = svg.replace(' %s="%s"' % (attr, svg.split('%s="' % attr, 1)[1].split('"', 1)[0]),
                          '', 1)
    html = ('<!doctype html><html><head><meta charset="utf-8"><style>'
            'html,body{margin:0;padding:0;background:#fff}'
            'svg{display:block}%s</style></head><body>%s</body></html>'
            % (page_css, svg))
    out = os.path.join(tmpdir, os.path.basename(svg_path) + '.html')
    with open(out, 'w') as f:
        f.write(html)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--generate', action='store_true',
                    help='run generate.py before rendering')
    args = ap.parse_args()

    if args.generate:
        subprocess.check_call([sys.executable, os.path.join(HERE, 'generate.py')])

    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        for lang in LANGS:
            # --- PNGs, one per drawing, referenced from the README ---
            for name, (w, h) in DRAWINGS.items():
                svg = os.path.join(HERE, '%s-%s.svg' % (name, lang))
                page = wrap(svg, tmp, 'svg{width:%dpx;height:%dpx}' % (w, h))
                png = os.path.join(IMAGES, '%s-%s.png' % (name, lang))
                run_chrome(chrome, ['--screenshot=%s' % png,
                                    '--window-size=%d,%d' % (w, h),
                                    '--force-device-scale-factor=%s' % PNG_SCALE,
                                    page], tmp)
                print('wrote images/%s' % os.path.basename(png))

            # --- one two-page PDF per language, hydraulic then electrical ---
            parts = []
            for name in ('hydraulic', 'electrical'):
                with open(os.path.join(HERE, '%s-%s.svg' % (name, lang))) as f:
                    body = f.read()
                for attr in ('width', 'height'):
                    body = body.replace(
                        ' %s="%s"' % (attr, body.split('%s="' % attr, 1)[1].split('"', 1)[0]),
                        '', 1)
                parts.append('<div class="page">%s</div>' % body)
            html = ('<!doctype html><html><head><meta charset="utf-8"><style>'
                    '@page{size:A3 landscape;margin:8mm}'
                    'html,body{margin:0;padding:0;background:#fff}'
                    '.page{page-break-after:always;height:281mm;display:flex;'
                    'align-items:center;justify-content:center;overflow:hidden}'
                    '.page:last-child{page-break-after:auto}'
                    'svg{max-width:100%%;max-height:281mm;width:auto;height:auto;display:block}'
                    '</style></head><body>%s</body></html>' % ''.join(parts))
            src = os.path.join(tmp, 'schematics-%s.html' % lang)
            with open(src, 'w') as f:
                f.write(html)
            pdf = os.path.join(HERE, 'schematics-%s.pdf' % lang)
            run_chrome(chrome, ['--no-pdf-header-footer', '--print-to-pdf=%s' % pdf, src], tmp)
            print('wrote docs/schematics/%s' % os.path.basename(pdf))


if __name__ == '__main__':
    main()
