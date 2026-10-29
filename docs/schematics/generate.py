#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generates the hydraulic and electrical schematics as standalone SVG files.

The schematics document the physical build inside the carry case: which parts
carry water and how they are connected, and how the Pico drives the valves and
the pump. Both are emitted in English and German from the same layout code —
only the STRINGS table differs per language, so the two versions can never
drift apart geometrically.

Usage:
    python3 docs/schematics/generate.py

Writes hydraulic-<lang>.svg and electrical-<lang>.svg next to this script.
See docs/schematics.md for how to re-render the PNGs in images/.
"""

import os

FONT = '"DejaVu Sans","Liberation Sans",Arial,sans-serif'
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Shared palette. The hydraulic and electrical drawings deliberately use
# different hues so the two pages are never confused for one another.
INK = '#16211c'
GREY = '#5a6b62'
H_FEED, H_PRESS, H_PERM, H_WASTE = '#1e88e5', '#0d47a1', '#2e7d32', '#9c5a2d'
E_24V, E_GND, E_5V, E_SIG = '#d32f2f', '#212121', '#f9a825', '#00897b'


# --------------------------------------------------------------------------
# SVG primitives
# --------------------------------------------------------------------------

def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def defs(colors):
    """One arrow marker per pipe colour; markers inherit no stroke in SVG 1.1."""
    out = []
    for name, c in colors.items():
        out.append(
            '<marker id="arw-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5.5" '
            'markerHeight="5.5" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="%s"/></marker>' % (name, c))
    return '<defs>%s</defs>' % ''.join(out)


def text(x, y, s, size=15, anchor='middle', weight='400', fill=INK):
    return ('<text x="%g" y="%g" font-family=%s font-size="%g" font-weight="%s" '
            'text-anchor="%s" fill="%s">%s</text>'
            % (x, y, FONT, size, weight, anchor, fill, esc(s)))


def box(x, y, w, h, title, sub='', fill='#ffffff', stroke=INK, dash=False,
        tsize=16, ssize=12):
    """Rounded box. `title` may contain newlines when `sub` is empty."""
    d = ' stroke-dasharray="7 5"' if dash else ''
    out = ['<rect x="%g" y="%g" width="%g" height="%g" rx="8" fill="%s" stroke="%s" '
           'stroke-width="2.5"%s/>' % (x, y, w, h, fill, stroke, d)]
    cx, cy = x + w / 2.0, y + h / 2.0
    if sub:
        out.append(text(cx, cy - 3, title, tsize, 'middle', '700', stroke))
        for i, line in enumerate(sub.split('\n')):
            out.append(text(cx, cy + 15 + i * 14, line, ssize, 'middle', '400', '#4a5a52'))
    else:
        lines = title.split('\n')
        for i, line in enumerate(lines):
            off = (len(lines) - 1) * -9 + i * 18
            out.append(text(cx, cy + 6 + off, line, tsize, 'middle', '700', stroke))
    return ''.join(out)


def pipe(pts, color, w=5, arrow=False, name='feed'):
    a = ' marker-end="url(#arw-%s)"' % name if arrow else ''
    p = ' '.join('%g,%g' % (x, y) for x, y in pts)
    return ('<polyline points="%s" fill="none" stroke="%s" stroke-width="%g" '
            'stroke-linejoin="round" stroke-linecap="round"%s/>' % (p, color, w, a))


def junction(x, y, color, r=7):
    return '<circle cx="%g" cy="%g" r="%g" fill="%s"/>' % (x, y, r, color)


def tag(x, y, s, color, size=12, anchor='middle', weight='700'):
    """Caption sitting on top of a pipe; the white halo keeps it readable."""
    return ('<text x="%g" y="%g" font-family=%s font-size="%g" font-weight="%s" '
            'text-anchor="%s" fill="%s" stroke="#ffffff" stroke-width="4" '
            'paint-order="stroke" stroke-linejoin="round">%s</text>'
            % (x, y, FONT, size, weight, anchor, color, esc(s)))


def page(width, height, body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %g %g" width="%g" '
            'height="%g"><rect width="%g" height="%g" fill="#ffffff"/>%s</svg>'
            % (width, height, width, height, width, height, body))


def valve_table(s, x, y, L, width_cols):
    """Renders the valve truth table; identical in both drawings."""
    cols = [L['t_mode'], 'V1', 'V2', 'V3', 'V4', L['t_pump']]
    rows = [(L['t_idle'], 'c', 'c', 'c', 'c', 'off'),
            (L['t_flush'], 'o', 'o', 'c', 'c', 'on'),
            (L['t_discard'], 'o', 'c', 'c', 'o', 'on'),
            (L['t_filter'], 'o', 'c', 'o', 'c', 'on'),
            (L['t_bleed'], 'c', 'o', 'c', 'c', 'off')]
    words = {'o': (L['t_open'], '#1b7a4b', '700'),
             'c': (L['t_closed'], '#8a9a93', '400'),
             'on': (L['t_on'], '#b36b00', '700'),
             'off': (L['t_off'], '#8a9a93', '400')}
    rh, tw = 30, sum(width_cols)
    s.append(text(x, y, L['t_title'], 15, 'start', '700', INK))
    s.append('<rect x="%g" y="%g" width="%g" height="%g" rx="6" fill="#2e7d5b"/>'
             % (x, y + 14, tw, rh))
    xc = x
    for i, c in enumerate(cols):
        s.append(text(xc + width_cols[i] / 2.0, y + 34, c, 13, 'middle', '700', '#ffffff'))
        xc += width_cols[i]
    for r, row in enumerate(rows):
        yy = y + 14 + rh * (r + 1)
        s.append('<rect x="%g" y="%g" width="%g" height="%g" fill="%s" stroke="#dde7e2" '
                 'stroke-width="1"/>' % (x, yy, tw, rh, '#ffffff' if r % 2 == 0 else '#f4f9f6'))
        xc = x
        for i, cell in enumerate(row):
            if i == 0:
                s.append(text(xc + 12, yy + 20, cell, 13, 'start', '600', INK))
            else:
                label, col, wt = words[cell]
                s.append(text(xc + width_cols[i] / 2.0, yy + 20, label, 13, 'middle', wt, col))
            xc += width_cols[i]


# --------------------------------------------------------------------------
# Hydraulic schematic
# --------------------------------------------------------------------------

def build_hydraulic(L):
    W, H = 1740, 1640
    CX, MX, MW = 320, 160, 320
    s = [defs({'feed': H_FEED, 'press': H_PRESS, 'perm': H_PERM, 'waste': H_WASTE})]

    s.append(text(50, 52, L['h_title'], 30, 'start', '700', INK))
    s.append(text(50, 80, L['h_subtitle'], 15, 'start', '400', GREY))

    def vline(y1, y2, col):
        s.append(pipe([(CX, y1), (CX, y2)], col, 6))

    # Main column: inlet at the top, membrane at the bottom.
    s.append(box(MX, 120, MW, 76, L['h_inlet'], L['h_inlet_s'], '#ffffff', H_FEED, False, 17, 12))
    vline(196, 236, H_FEED)
    s.append(box(MX, 236, MW, 76, L['h_pre'], L['h_pre_s'], '#ffffff', INK, False, 17, 12))
    vline(312, 352, H_FEED)
    s.append(box(MX, 352, MW, 76, L['h_v1'], L['h_v1_s'], '#eaf2fb', INK, False, 17, 12))
    vline(428, 500, H_FEED)
    s.append(junction(CX, 462, H_FEED))
    s.append(box(MX, 500, MW, 90, L['h_pump'], L['h_pump_s'], '#fff8e1', INK, False, 17, 12))
    vline(590, 740, H_PRESS)
    s.append(junction(CX, 634, H_PRESS))
    s.append(junction(CX, 700, H_PRESS))
    s.append(box(MX, 740, MW, 86, L['h_carbon'], L['h_carbon_s'], '#ffffff', INK, False, 17, 12))
    vline(826, 906, H_PRESS)
    s.append(junction(CX, 866, H_PRESS))
    s.append(box(MX, 906, MW, 86, L['h_sed'], L['h_sed_s'], '#ffffff', INK, False, 17, 12))
    vline(992, 1040, H_PRESS)
    s.append(box(MX, 1040, MW, 110, L['h_mem'], L['h_mem_s'], '#e3f2fd', INK, False, 19, 13))

    # Recirculation loop: pump outlet -> adjustable restrictor -> pump inlet.
    s.append(pipe([(CX, 634), (620, 634)], H_PRESS, 5))
    s.append(box(620, 602, 300, 64, L['h_adj'], L['h_adj_s'], '#ffffff', H_PRESS, False, 15, 11))
    s.append(pipe([(920, 634), (1010, 634), (1010, 462), (CX, 462)], H_PRESS, 5, True, 'press'))
    s.append(tag(1016, 548, L['h_recirc'], H_PRESS, 12, 'start'))
    s.append(tag(1016, 566, L['h_recirc_s'], GREY, 11, 'start', '400'))

    # Pressure gauge on the tee after the pump.
    s.append(pipe([(CX, 700), (640, 700)], H_PRESS, 5))
    s.append('<circle cx="692" cy="700" r="40" fill="#ffffff" stroke="%s" stroke-width="3"/>' % INK)
    s.append('<circle cx="692" cy="700" r="3.5" fill="%s"/>' % INK)
    s.append('<path d="M 692 700 L 708 679" stroke="%s" stroke-width="3" stroke-linecap="round"/>' % INK)
    s.append(text(692, 762, L['h_gauge'], 13, 'middle', '700', INK))

    # H2O2 injection point on the tee after the carbon filter.
    s.append(pipe([(620, 866), (CX, 866)], H_PRESS, 5, True, 'press'))
    s.append(box(620, 834, 360, 64, L['h_dis'], L['h_dis_s'], '#f3e5f5', '#7b1fa2', False, 15, 11))

    # Permeate side.
    s.append(pipe([(240, 1150), (240, 1215), (135, 1215), (135, 1250)], H_PERM, 5))
    s.append(pipe([(240, 1215), (335, 1215), (335, 1250)], H_PERM, 5))
    s.append(junction(240, 1215, H_PERM))
    s.append(tag(228, 1186, L['h_perm_lbl'], H_PERM, 12, 'end'))
    s.append(box(50, 1250, 170, 66, 'V3', L['h_v3_s'], '#eaf7ee', INK, False, 16, 11))
    s.append(box(250, 1250, 170, 66, 'V4', L['h_v4_s'], '#f6efe9', INK, False, 16, 11))
    s.append(pipe([(135, 1316), (135, 1390)], H_PERM, 5, True, 'perm'))
    s.append(box(40, 1390, 190, 76, L['h_clean'], L['h_clean_s'], '#e8f5e9', H_PERM, False, 16, 11))
    s.append(pipe([(335, 1316), (335, 1520)], H_WASTE, 5))

    # Waste side: fixed restrictor + adjustable restrictor, bypassed by V2.
    s.append(pipe([(430, 1150), (430, 1190), (820, 1190), (820, 1250)], H_WASTE, 5))
    s.append(tag(560, 1178, L['h_waste_lbl'], H_WASTE, 12))
    s.append(junction(820, 1250, H_WASTE))
    s.append(pipe([(820, 1250), (740, 1250), (740, 1288)], H_WASTE, 5))
    s.append(pipe([(820, 1250), (1000, 1250), (1000, 1288)], H_WASTE, 5))
    s.append(box(630, 1288, 220, 60, L['h_fixed'], '', '#ffffff', INK, False, 13))
    s.append(tag(740, 1366, L['h_fixed_s'], GREY, 11, 'middle', '400'))
    s.append(pipe([(740, 1348), (740, 1388)], H_WASTE, 5))
    s.append(box(630, 1388, 220, 60, L['h_adj2'], '', '#ffffff', INK, False, 13))
    s.append(tag(740, 1466, L['h_adj2_s'], GREY, 11, 'middle', '400'))
    s.append(box(910, 1288, 180, 66, 'V2', L['h_v2_s'], '#f6efe9', INK, False, 16, 11))
    s.append(pipe([(740, 1448), (740, 1520)], H_WASTE, 5))
    s.append(pipe([(1000, 1354), (1000, 1520)], H_WASTE, 5))
    s.append(pipe([(1000, 1520), (250, 1520)], H_WASTE, 5, True, 'waste'))
    for jx in (740, 335):
        s.append(junction(jx, 1520, H_WASTE))
    s.append(box(60, 1482, 190, 76, L['h_waste'], L['h_waste_s'], '#efebe9', H_WASTE, False, 16, 11))

    # Sidebar: legend, valve table, build notes.
    SX, SW = 1140, 540
    s.append('<rect x="%g" y="110" width="%g" height="210" rx="10" fill="#fafafa" '
             'stroke="#cfd8d3" stroke-width="2"/>' % (SX, SW))
    s.append(text(SX + 20, 142, L['legend'], 16, 'start', '700', INK))
    for i, (c, t) in enumerate([(H_FEED, L['h_lg_feed']), (H_PRESS, L['h_lg_press']),
                                (H_PERM, L['h_lg_perm']), (H_WASTE, L['h_lg_waste'])]):
        yy = 172 + i * 26
        s.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="5" '
                 'stroke-linecap="round"/>' % (SX + 20, yy, SX + 60, yy, c))
        s.append(text(SX + 72, yy + 5, t, 13, 'start', '400', '#41544a'))
    s.append(junction(SX + 40, 286, INK, 6))
    s.append(text(SX + 72, 291, L['h_lg_tee'], 13, 'start', '400', '#41544a'))

    valve_table(s, SX, 392, L, [180, 58, 58, 58, 58, 90])

    hy = 620
    s.append('<rect x="%g" y="%g" width="%g" height="520" rx="10" fill="#fafafa" '
             'stroke="#cfd8d3" stroke-width="2"/>' % (SX, hy, SW))
    s.append(text(SX + 20, hy + 32, L['h_notes_title'], 16, 'start', '700', INK))
    yy = hy + 58
    for head, lines in L['h_notes']:
        s.append(text(SX + 20, yy, head, 13, 'start', '700', '#1b4f8a'))
        yy += 20
        for ln in lines:
            s.append(text(SX + 20, yy, ln, 12, 'start', '400', '#41544a'))
            yy += 17
        yy += 10
    return page(W, H, ''.join(s))


# --------------------------------------------------------------------------
# Electrical schematic
# --------------------------------------------------------------------------

def build_electrical(L):
    W, H = 1740, 1320
    Y24, YGND, Y5 = 250, 1010, 455
    s = [defs({'v24': E_24V, 'gnd': E_GND, 'v5': E_5V, 'sig': E_SIG})]

    s.append(text(50, 52, L['e_title'], 30, 'start', '700', INK))
    s.append(text(50, 80, L['e_subtitle'], 15, 'start', '400', GREY))

    # Power supply and the two rails that span the drawing.
    s.append(box(60, 120, 250, 92, L['e_psu'], L['e_psu_s'], '#ffffff', INK, False, 17, 12))
    s.append(pipe([(310, 150), (380, 150), (380, Y24)], E_24V, 6))
    s.append(pipe([(60, 190), (24, 190), (24, YGND)], E_GND, 6))
    s.append(pipe([(380, Y24), (1600, Y24)], E_24V, 6))
    s.append(text(392, Y24 - 14, L['e_rail24'], 14, 'start', '700', E_24V))
    s.append(pipe([(24, YGND), (1600, YGND)], E_GND, 6))
    s.append(text(392, YGND + 26, L['e_rail0'], 14, 'start', '700', E_GND))

    s.append(box(390, 310, 240, 92, L['e_buck'], L['e_buck_s'], '#fffde7', INK, False, 16, 12))
    s.append(pipe([(450, Y24), (450, 310)], E_24V, 5))
    s.append(junction(450, Y24, E_24V))
    s.append(pipe([(570, 402), (570, YGND)], E_GND, 5))
    s.append(junction(570, YGND, E_GND))
    s.append(pipe([(450, 402), (450, Y5), (820, Y5)], E_5V, 5))
    s.append(text(646, Y5 - 12, '5 V', 14, 'start', '700', E_5V))

    px, py, pw, ph = 390, 505, 270, 320
    s.append(box(px, py, pw, ph, '', '', '#f3f6ff', INK))
    s.append(text(px + pw / 2.0, py + 34, 'Raspberry Pi Pico', 19, 'middle', '700', INK))
    s.append(text(px + pw / 2.0, py + 56, L['e_pico_s'], 12, 'middle', '400', GREY))
    for i, (pn, fn) in enumerate(L['e_pins']):
        yy = py + 86 + i * 24
        s.append(text(px + 18, yy, pn, 13, 'start', '700', '#1b4f8a'))
        s.append(text(px + 90, yy, fn, 12, 'start', '400', '#41544a'))
    s.append(pipe([(450, Y5), (450, py)], E_5V, 5))
    s.append(junction(450, Y5, E_5V))
    s.append(pipe([(530, py + ph), (530, YGND)], E_GND, 5))
    s.append(junction(530, YGND, E_GND))

    s.append(box(60, 520, 230, 76, L['e_buzz'], L['e_buzz_s'], '#ffffff', INK, False, 16, 11))
    s.append(pipe([(px, 558), (292, 558)], E_SIG, 3.5, True, 'sig'))
    s.append(text(340, 548, 'GP15', 11, 'middle', '700', E_SIG))
    s.append(pipe([(150, 596), (150, YGND)], E_GND, 3.5))
    s.append(junction(150, YGND, E_GND))
    s.append(box(60, 660, 230, 76, L['e_btn'], L['e_btn_s'], '#ffffff', INK, False, 16, 11))
    s.append(pipe([(292, 698), (px, 698)], E_SIG, 3.5, True, 'sig'))
    s.append(text(340, 688, 'GP16', 11, 'middle', '700', E_SIG))
    s.append(pipe([(210, 736), (210, YGND)], E_GND, 3.5))
    s.append(junction(210, YGND, E_GND))

    # Four-channel relay board. The contacts sit in the ground return, so the
    # loads are permanently tied to +24 V and the relay completes the circuit.
    rx, ry, rw, rh = 740, 490, 400, 320
    s.append('<rect x="%g" y="%g" width="%g" height="%g" rx="10" fill="#f7f9fb" stroke="%s" '
             'stroke-width="2.5" stroke-dasharray="8 5"/>' % (rx, ry, rw, rh, GREY))
    s.append(text(rx + rw / 2.0, ry + 26, L['e_relay4'], 16, 'middle', '700', INK))
    s.append(text(rx + rw / 2.0, ry + 45, L['e_relay4_s'], 11, 'middle', '400', '#6a4a72'))
    s.append(pipe([(820, Y5), (820, ry)], E_5V, 4))
    s.append(text(834, ry - 10, 'VCC 5 V', 11, 'start', '700', E_5V))

    rows = [575, 640, 705, 770]
    X_NO, X_COM, X_LOAD_L, X_LOAD_R, X_PLUS = 980, 1090, 1200, 1540, 1600
    s.append(pipe([(X_NO, 575), (X_NO, YGND)], E_GND, 5))
    s.append(junction(X_NO, YGND, E_GND))
    s.append(pipe([(X_PLUS, Y24), (X_PLUS, 770)], E_24V, 5))
    s.append(junction(X_PLUS, Y24, E_24V))

    for i, row in enumerate(rows):
        s.append(junction(X_NO, row, E_GND))
        s.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="3.5" '
                 'stroke-linecap="round"/>' % (X_COM, row, X_NO + 10, row - 21, E_GND))
        s.append('<circle cx="%g" cy="%g" r="6" fill="%s"/>' % (X_COM, row, E_GND))
        s.append(text(1035, row + 26, 'K%d' % (i + 1), 12, 'middle', '700', GREY))
        s.append('<rect x="734" y="%g" width="13" height="13" fill="%s"/>' % (row - 7, E_SIG))
        s.append(pipe([(px + pw, row), (734, row)], E_SIG, 3.5, True, 'sig'))
        s.append(text(700, row - 10, 'GP%d' % i, 11, 'middle', '700', E_SIG))
        vy = row - 28
        s.append(box(X_LOAD_L, vy, X_LOAD_R - X_LOAD_L, 56, L['e_valves'][i], '',
                     '#ffffff', INK, False, 15))
        s.append(text((X_LOAD_L + X_LOAD_R) / 2.0, vy + 46, L['e_valve_s'], 10.5,
                      'middle', '400', '#6a7a72'))
        s.append(pipe([(X_LOAD_L, row), (X_COM, row)], E_GND, 4))
        s.append(pipe([(X_PLUS, row), (X_LOAD_R, row)], E_24V, 4, True, 'v24'))
        if i < 3:
            s.append(junction(X_PLUS, row, E_24V))
    s.append(pipe([(760, ry + rh), (760, 830), (716, 830), (716, YGND)], E_GND, 4))
    s.append(junction(716, YGND, E_GND))
    s.append(text(600, 846, L['e_logic_gnd'], 11, 'start', '700', E_GND))

    # Single-channel relay for the pump, plus the manual switch on the case.
    qx, qy, qw, qh = 740, 860, 400, 120
    s.append('<rect x="%g" y="%g" width="%g" height="%g" rx="10" fill="#f7f9fb" stroke="%s" '
             'stroke-width="2.5" stroke-dasharray="8 5"/>' % (qx, qy, qw, qh, GREY))
    s.append(text(qx + qw / 2.0, qy + 24, L['e_relay1'], 15, 'middle', '700', INK))
    s.append(text(qx + qw / 2.0, qy + 42, L['e_relay1_s'], 11, 'middle', '400', '#6a4a72'))
    prow = 930
    s.append(junction(X_NO, prow, E_GND))
    s.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="3.5" '
             'stroke-linecap="round"/>' % (X_COM, prow, X_NO + 10, prow - 21, E_GND))
    s.append('<circle cx="%g" cy="%g" r="6" fill="%s"/>' % (X_COM, prow, E_GND))
    s.append('<rect x="734" y="%g" width="13" height="13" fill="%s"/>' % (prow - 7, E_SIG))
    s.append(pipe([(px + pw, 795), (686, 795), (686, prow), (734, prow)], E_SIG, 3.5, True, 'sig'))
    s.append(text(664, 785, 'GP4', 11, 'middle', '700', E_SIG))
    s.append(box(X_LOAD_L, prow - 28, X_LOAD_R - X_LOAD_L, 56, L['e_pump'], '',
                 '#fff8e1', INK, False, 15))
    s.append(text((X_LOAD_L + X_LOAD_R) / 2.0, prow + 18, L['e_pump_s'], 10.5,
                  'middle', '400', '#6a7a72'))
    s.append(pipe([(X_LOAD_L, prow), (X_COM, prow)], E_GND, 4))
    s.append(pipe([(X_PLUS, 770), (X_PLUS, 838)], E_24V, 4))
    s.append('<circle cx="%g" cy="844" r="5.5" fill="%s"/>' % (X_PLUS, E_24V))
    s.append('<line x1="%g" y1="844" x2="%g" y2="884" stroke="%s" stroke-width="3.5" '
             'stroke-linecap="round"/>' % (X_PLUS, X_PLUS - 26, E_24V))
    s.append('<circle cx="%g" cy="890" r="5.5" fill="%s"/>' % (X_PLUS, E_24V))
    s.append(pipe([(X_PLUS, 890), (X_PLUS, prow), (X_LOAD_R, prow)], E_24V, 4, True, 'v24'))
    s.append(text(X_PLUS - 44, 852, L['e_switch'], 11, 'end', '700', E_24V))
    s.append(text(X_PLUS - 44, 870, L['e_switch_s'], 11, 'end', '400', GREY))
    s.append(pipe([(X_PLUS, 770), (X_LOAD_R, 770)], E_24V, 4, True, 'v24'))
    s.append(junction(X_PLUS, 770, E_24V))

    s.append('<rect x="40" y="1070" width="1660" height="190" rx="10" fill="#fafafa" '
             'stroke="#cfd8d3" stroke-width="2"/>')
    for i, (c, t) in enumerate([(E_24V, L['e_lg_24']), (E_GND, L['e_lg_gnd']),
                                (E_5V, L['e_lg_5v']), (E_SIG, L['e_lg_sig'])]):
        xx = 66 + i * 250
        s.append('<line x1="%g" y1="1102" x2="%g" y2="1102" stroke="%s" stroke-width="5" '
                 'stroke-linecap="round"/>' % (xx, xx + 36, c))
        s.append(text(xx + 46, 1107, t, 12.5, 'start', '400', '#41544a'))
    for i, n in enumerate(L['e_notes']):
        s.append(text(66, 1140 + i * 21, '•  ' + n, 12.5, 'start', '400', '#41544a'))
    return page(W, H, ''.join(s))


# --------------------------------------------------------------------------
# Strings
# --------------------------------------------------------------------------

STRINGS = {
    'en': {
        'legend': 'Legend',
        't_title': 'Valve positions per mode  (from main.py)',
        't_mode': 'Mode', 't_pump': 'Pump',
        't_idle': 'Idle', 't_flush': 'Flush', 't_discard': 'Discard',
        't_filter': 'Filter', 't_bleed': 'Pressure bleed',
        't_open': 'open', 't_closed': 'closed', 't_on': 'ON', 't_off': 'OFF',

        'h_title': 'Hydraulics — every water-carrying part',
        'h_subtitle': 'Reverse osmosis system in a carry case · AquaMichel Mini with '
                      'booster pump and four solenoid valves',
        'h_inlet': 'Inlet', 'h_inlet_s': 'tap, jerrycan or tank',
        'h_pre': 'Coarse pre-filter', 'h_pre_s': 'grey inline strainer, screw-off cap',
        'h_v1': 'V1 — inlet valve', 'h_v1_s': 'solenoid 24 V · closed when off',
        'h_pump': 'Booster pump',
        'h_pump_s': 'E-CHEN EC-304-200B\n24 V DC · 2.8 A · ≤ 2.4 l/min',
        'h_carbon': 'Carbon filter', 'h_carbon_s': 'WATER PRO IN10C · 10"\nremoves chlorine',
        'h_sed': 'Sediment filter', 'h_sed_s': 'WATER PRO IN10S · 5 µm',
        'h_mem': 'RO membrane', 'h_mem_s': 'AquaMichel Mini\nreverse osmosis module',
        'h_adj': 'Adjustable restrictor', 'h_adj_s': 'knurled silver screw',
        'h_recirc': 'Recirculation', 'h_recirc_s': 'sets the pressure',
        'h_gauge': 'Pressure gauge',
        'h_dis': 'Disinfection inlet',
        'h_dis_s': 'check valve with blue plug · H₂O₂',
        'h_perm_lbl': 'Permeate — white tube',
        'h_waste_lbl': 'Waste water — red tube',
        'h_v3_s': 'clean water', 'h_v4_s': 'first-water discard', 'h_v2_s': 'flush valve',
        'h_clean': 'Clean water', 'h_clean_s': 'carafe / canister',
        'h_waste': 'Waste water', 'h_waste_s': 'one outlet on the case',
        'h_fixed': 'Fixed flow\nrestrictor', 'h_fixed_s': 'original part, with strainer',
        'h_adj2': 'Adjustable\nrestrictor', 'h_adj2_s': 'sets the flush rate',
        'h_lg_feed': 'Supply, unpressurised (before the pump)',
        'h_lg_press': 'Pressure side (pump → membrane)',
        'h_lg_perm': 'Permeate / clean water',
        'h_lg_waste': 'Waste water / flush water',
        'h_lg_tee': 'Tee / branch',
        'h_notes_title': 'Notes for rebuilding',
        'h_notes': [
            ('Operating modes', [
                'Filter: V1 + V3 open. Waste water leaves only through the',
                'restrictors, which therefore set the recovery rate.',
                'Flush: V1 + V2 open. V2 bypasses both restrictors, giving a',
                'high cross-flow that sweeps the membrane clean.',
                'Discard: V1 + V4 open. The first permeate after a standstill',
                'goes to the waste outlet instead of into the glass.',
                'Pressure bleed: V2 alone open, pump off — residual pressure',
                'escapes through the waste line.']),
            ('Compared with the original build manual', [
                'V2 replaces the blue ball valve of the flush-water system.',
                'The order carbon → sediment → membrane is the one the',
                'AquaMichel Mini manual prescribes, not a mistake.',
                'The fixed restrictor carries a strainer that keeps scale out',
                'of the adjustable one — keep it in that order.']),
            ('Tube colours in this build', [
                'white = permeate from the membrane, red = waste water from the',
                'membrane, blue = supply and pre-filter run. Red is also used on',
                'the pressure side, so do not read the colours as a strict code.']),
        ],

        'e_title': 'Electrics — controller, valves and pump',
        'e_subtitle': 'Raspberry Pi Pico · 24 V DC · the relays switch the negative line',
        'e_psu': 'Power supply 24 V DC', 'e_psu_s': 'CJ-2430 · 24 V / 3 A · no fuse fitted',
        'e_rail24': '+24 V  (permanently present at valves and pump)',
        'e_rail0': '0 V / GND  (common ground)',
        'e_buck': 'DC-DC step-down', 'e_buck_s': 'LM2596 · 24 V → 5 V',
        'e_pico_s': 'MicroPython · main.py',
        'e_pins': [('VSYS', '5 V in'), ('GP0', '→ relay K1 (V1)'), ('GP1', '→ relay K2 (V2)'),
                   ('GP2', '→ relay K3 (V3)'), ('GP3', '→ relay K4 (V4)'),
                   ('GP4', '→ pump relay'), ('GP15', '→ buzzer (PWM)'),
                   ('GP16', '← button (PULL_UP)'), ('GND', 'ground')],
        'e_buzz': 'Buzzer', 'e_buzz_s': 'KY-006 · inside the electronics box',
        'e_btn': 'Button', 'e_btn_s': 'small silver button on the case',
        'e_relay4': '4-channel relay board (5 V)',
        'e_relay4_s': 'inputs active LOW — GP = 0 energises',
        'e_valves': ['V1 — inlet valve', 'V2 — flush valve',
                     'V3 — clean-water outlet', 'V4 — discard'],
        'e_valve_s': 'solenoid 24 V · closed when de-energised',
        'e_logic_gnd': 'GND (logic)',
        'e_relay1': '1-channel relay (pump)',
        'e_relay1_s': 'input active HIGH — GP4 = 1 energises',
        'e_pump': 'Booster pump E-CHEN EC-304-200B', 'e_pump_s': '24 V DC · 2.8 A',
        'e_switch': 'black switch on the case (in the red lead)',
        'e_switch_s': 'cuts the pump only',
        'e_lg_24': '+24 V (pump, valves)', 'e_lg_gnd': '0 V / switched ground',
        'e_lg_5v': '5 V (logic)', 'e_lg_sig': 'GPIO control signal',
        'e_notes': [
            'Switching principle: +24 V sits permanently on every load. The relay breaks the '
            'negative line — at rest the contact is open, so the load is dead.',
            'Relay polarity: the 4-channel board energises on LOW, the pump relay on HIGH. '
            'main.py already matches this (_set_valves inverts, set_pump does not).',
            'Tie all grounds together: supply −, step-down −, Pico GND, both relay boards. '
            'Without a common ground the relays switch erratically.',
            'Recommended when rebuilding: a 5 A slow-blow fuse in the +24 V line and a 5 A supply '
            '— the pump alone draws 2.8 A of the 3 A available.',
        ],
    },
    'de': {
        'legend': 'Legende',
        't_title': 'Ventilstellungen je Betriebsart  (aus main.py)',
        't_mode': 'Betriebsart', 't_pump': 'Pumpe',
        't_idle': 'Ruhe', 't_flush': 'Spülen', 't_discard': 'Verwerfen',
        't_filter': 'Filtern', 't_bleed': 'Druckabbau',
        't_open': 'auf', 't_closed': 'zu', 't_on': 'EIN', 't_off': 'AUS',

        'h_title': 'Hydraulik — alle wasserführenden Teile',
        'h_subtitle': 'Umkehrosmose-Anlage im Koffer · AquaMichel Mini mit Druckpumpe '
                      'und vier Magnetventilen',
        'h_inlet': 'Zulauf', 'h_inlet_s': 'Wasserhahn, Kanister oder Tank',
        'h_pre': 'Grob-Vorfilter', 'h_pre_s': 'grauer Mini-Vorfilter mit Sieb',
        'h_v1': 'V1 — Einlassventil', 'h_v1_s': 'Magnetventil 24 V · stromlos zu',
        'h_pump': 'Druckpumpe',
        'h_pump_s': 'E-CHEN EC-304-200B\n24 V DC · 2,8 A · ≤ 2,4 l/min',
        'h_carbon': 'Aktivkohlefilter', 'h_carbon_s': 'WATER PRO IN10C · 10"\nentfernt Chlor',
        'h_sed': 'Sedimentfilter', 'h_sed_s': 'WATER PRO IN10S · 5 µm',
        'h_mem': 'RO-Membran', 'h_mem_s': 'AquaMichel Mini\nUmkehrosmose-Modul',
        'h_adj': 'Durchflussversteller', 'h_adj_s': 'einstellbar · Silberschraube',
        'h_recirc': 'Rückführung', 'h_recirc_s': 'stellt den Druck ein',
        'h_gauge': 'Manometer',
        'h_dis': 'Desinfektions-Einlass',
        'h_dis_s': 'Rückschlagventil mit blauem Stopfen · H₂O₂',
        'h_perm_lbl': 'Permeat — weißer Schlauch',
        'h_waste_lbl': 'Abwasser — roter Schlauch',
        'h_v3_s': 'Reinwasser', 'h_v4_s': 'Verwurf', 'h_v2_s': 'Spülventil',
        'h_clean': 'Reinwasser', 'h_clean_s': 'Karaffe / Kanister',
        'h_waste': 'Abwasser', 'h_waste_s': 'ein Ausgang am Koffer',
        'h_fixed': 'Fester\nDurchflussreduzierer', 'h_fixed_s': 'Original-Teil, mit Sieb',
        'h_adj2': 'Durchfluss-\nversteller', 'h_adj2_s': 'stellt die Spülmenge ein',
        'h_lg_feed': 'Zulauf, drucklos (vor der Pumpe)',
        'h_lg_press': 'Druckseite (Pumpe → Membran)',
        'h_lg_perm': 'Permeat / Reinwasser',
        'h_lg_waste': 'Abwasser / Spülwasser',
        'h_lg_tee': 'T-Stück / Abzweig',
        'h_notes_title': 'Hinweise für den Nachbau',
        'h_notes': [
            ('Betriebsarten', [
                'Filtern: V1 + V3 offen. Abwasser läuft nur über die Drosseln —',
                'sie bestimmen damit die Ausbeute.',
                'Spülen: V1 + V2 offen. V2 überbrückt beide Drosseln, dadurch',
                'hohe Strömung quer über die Membran.',
                'Verwerfen: V1 + V4 offen. Das erste Permeat nach Stillstand',
                'geht in den Abwasserausgang statt ins Glas.',
                'Druckabbau: nur V2 offen, Pumpe aus — der Restdruck',
                'entweicht über die Abwasserleitung.']),
            ('Gegenüber der Original-Bauanleitung', [
                'V2 ersetzt den blauen Kugelhahn des Spülwassersystems.',
                'Die Reihenfolge Aktivkohle → Sediment → Membran ist die der',
                'AquaMichel-Mini-Anleitung, kein Fehler.',
                'Im festen Durchflussreduzierer sitzt ein Sieb, das Kalk vom',
                'einstellbaren fernhält — Reihenfolge beibehalten.']),
            ('Schlauchfarben in dieser Anlage', [
                'weiß = Permeat ab Membran, rot = Abwasser ab Membran,',
                'blau = Zulauf und Vorfilterstrecke. Rot wird auch auf der',
                'Druckseite verwendet — die Farben sind kein strenger Code.']),
        ],

        'e_title': 'Elektrik — Steuerung, Ventile und Pumpe',
        'e_subtitle': 'Raspberry Pi Pico · 24 V DC · die Relais schalten die Minus-Leitung',
        'e_psu': 'Netzteil 24 V DC', 'e_psu_s': 'CJ-2430 · 24 V / 3 A · keine Sicherung',
        'e_rail24': '+24 V  (liegt dauerhaft an Ventilen und Pumpe an)',
        'e_rail0': '0 V / GND  (gemeinsame Masse)',
        'e_buck': 'DC-DC Step-Down', 'e_buck_s': 'LM2596 · 24 V → 5 V',
        'e_pico_s': 'MicroPython · main.py',
        'e_pins': [('VSYS', '5 V Eingang'), ('GP0', '→ Relais K1 (V1)'),
                   ('GP1', '→ Relais K2 (V2)'), ('GP2', '→ Relais K3 (V3)'),
                   ('GP3', '→ Relais K4 (V4)'), ('GP4', '→ Pumpen-Relais'),
                   ('GP15', '→ Summer (PWM)'), ('GP16', '← Taster (PULL_UP)'),
                   ('GND', 'Masse')],
        'e_buzz': 'Summer', 'e_buzz_s': 'KY-006 · in der Elektronikbox',
        'e_btn': 'Taster', 'e_btn_s': 'silberner Knopf außen am Koffer',
        'e_relay4': '4-Kanal-Relaismodul (5 V)',
        'e_relay4_s': 'Eingänge aktiv LOW — GP = 0 zieht an',
        'e_valves': ['V1 — Einlassventil', 'V2 — Spülventil',
                     'V3 — Reinwasser-Ausgang', 'V4 — Verwurf'],
        'e_valve_s': 'Magnetventil 24 V · stromlos geschlossen',
        'e_logic_gnd': 'GND (Logik)',
        'e_relay1': '1-Kanal-Relais (Pumpe)',
        'e_relay1_s': 'Eingang aktiv HIGH — GP4 = 1 zieht an',
        'e_pump': 'Druckpumpe E-CHEN EC-304-200B', 'e_pump_s': '24 V DC · 2,8 A',
        'e_switch': 'schwarzer Schalter außen (in der roten Leitung)',
        'e_switch_s': 'trennt nur die Pumpe',
        'e_lg_24': '+24 V (Pumpe, Ventile)', 'e_lg_gnd': '0 V / geschaltete Masse',
        'e_lg_5v': '5 V (Logik)', 'e_lg_sig': 'Steuersignal GPIO',
        'e_notes': [
            'Schaltprinzip: +24 V liegt dauerhaft an jeder Last. Das Relais trennt die '
            'Minus-Leitung — im Ruhezustand ist der Kontakt offen, die Last also stromlos.',
            'Relais-Polarität: das 4-Kanal-Modul zieht bei LOW an, das Pumpen-Relais bei HIGH. '
            'Genau so steht es in main.py (_set_valves invertiert, set_pump nicht).',
            'Alle Massen zusammenführen: Netzteil −, Step-Down −, Pico GND, beide '
            'Relaismodule. Ohne gemeinsame Masse schalten die Relais unzuverlässig.',
            'Für den Nachbau empfohlen: Feinsicherung 5 A träge in der +24-V-Leitung und ein '
            'Netzteil mit 5 A — die Pumpe allein zieht 2,8 A der verfügbaren 3 A.',
        ],
    },
}


def main():
    for lang, L in STRINGS.items():
        for name, svg in (('hydraulic', build_hydraulic(L)),
                          ('electrical', build_electrical(L))):
            path = os.path.join(OUT_DIR, '%s-%s.svg' % (name, lang))
            with open(path, 'w') as f:
                f.write(svg)
            print('wrote', os.path.basename(path))


if __name__ == '__main__':
    main()
