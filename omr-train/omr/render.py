"""MusicXML を楽譜画像（1段分・グレースケール）に描き、写真らしい汚れ・ゆがみを加える。

描画には Verovio（LGPL）を使う。学習用の画像を作るためだけに使い、アプリには入れない。
"""
import io
import math
import random

import cairosvg
import cv2
import numpy as np
import verovio

_tk = None


def toolkit():
    global _tk
    if _tk is None:
        _tk = verovio.toolkit()
    return _tk


def render_clean(xml, scale=None):
    """1段に収めて描画 → 白地に黒の画像（uint8, 余白を詰める）"""
    tk = toolkit()
    sc = scale or random.randint(32, 48)
    tk.setOptions({
        'pageWidth': 60000, 'pageHeight': 60000, 'adjustPageWidth': True, 'adjustPageHeight': True,
        'breaks': 'none', 'scale': sc, 'header': 'none', 'footer': 'none',
        'pageMarginLeft': 50, 'pageMarginRight': 50, 'pageMarginTop': 50, 'pageMarginBottom': 50,
        'spacingStaff': random.randint(6, 12), 'spacingLinear': random.uniform(0.2, 0.35), 'spacingNonLinear': random.uniform(0.5, 0.7),
        'font': random.choice(['Leipzig', 'Bravura', 'Gootville', 'Leland', 'Petaluma']) if random.random() < 0.6 else 'Leipzig',
        'svgViewBox': False,
    })
    if not tk.loadData(xml):
        raise RuntimeError('verovio could not load')
    svg = tk.renderToSVG(1)
    png = cairosvg.svg2png(bytestring=svg.encode('utf-8'), background_color='white')
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    return crop_content(img)


def crop_content(img, pad=None):
    ys, xs = np.where(img < 200)
    if len(xs) == 0:
        return img
    pad = pad if pad is not None else random.randint(6, 30)
    y0, y1 = max(0, ys.min() - pad), min(img.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(img.shape[1], xs.max() + pad)
    return img[y0:y1, x0:x1]


def add_neighbors(img):
    """ページから1段を切り出したときのように、上下に隣の段のはしを少し写り込ませる"""
    h, w = img.shape
    out = [img]
    if random.random() < 0.8:  # 上（前の段の下の方）
        th = int(h * random.uniform(0.06, 0.3))
        strip = np.roll(img[h - th:], random.randint(-w // 3, w // 3), axis=1)
        gap = np.full((int(h * random.uniform(0, 0.08)), w), 255, np.uint8)
        out = [strip, gap] + out
    if random.random() < 0.8:  # 下（次の段の上の方）
        th = int(h * random.uniform(0.06, 0.3))
        strip = np.roll(img[:th], random.randint(-w // 3, w // 3), axis=1)
        gap = np.full((int(h * random.uniform(0, 0.08)), w), 255, np.uint8)
        out = out + [gap, strip]
    return np.vstack(out)


def augment(img, strength=1.0):
    """紙の写真らしくする: 傾き・台形・ゆがみ・影・ぼけ・ノイズ・JPEG"""
    h, w = img.shape
    out = img.astype(np.float32)
    s = strength
    # 1) 紙の明るさ・インクの濃さ
    ink = random.uniform(0, 70) * s
    paper = 255 - random.uniform(0, 45) * s
    out = ink + (out / 255.0) * (paper - ink)
    # 2) 太さ（にじみ・かすれ）
    r = random.random()
    if r < 0.2 * s:
        out = cv2.erode(out, np.ones((2, 2), np.uint8))
    elif r < 0.35 * s:
        out = cv2.dilate(out, np.ones((2, 2), np.uint8))
    # 3) 傾き・台形（射影変換）
    if random.random() < 0.8 * s:
        ang = random.uniform(-2.5, 2.5) * s
        dx = w * random.uniform(-0.03, 0.03) * s
        dy = h * random.uniform(-0.06, 0.06) * s
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        jit = lambda: random.uniform(-1, 1)
        dst = np.float32([[0 + dx * jit(), 0 + dy * jit()], [w + dx * jit(), 0 + dy * jit()], [w + dx * jit(), h + dy * jit()], [0 + dx * jit(), h + dy * jit()]])
        M = cv2.getPerspectiveTransform(src, dst)
        R = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        R3 = np.vstack([R, [0, 0, 1]])
        out = cv2.warpPerspective(out, R3 @ M, (w, h), borderValue=float(paper))
    # 4) 紙のたわみ（上下に波打つ）
    if random.random() < 0.4 * s:
        amp = random.uniform(1, 4) * s
        per = random.uniform(0.6, 2.0) * w
        ph = random.uniform(0, 6.28)
        mapx, mapy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        mapy = mapy + amp * np.sin(2 * math.pi * mapx / per + ph).astype(np.float32)
        out = cv2.remap(out, mapx, mapy, cv2.INTER_LINEAR, borderValue=float(paper))
    # 5) 影（明るさのむら）
    if random.random() < 0.6 * s:
        gx = np.linspace(random.uniform(-1, 1), random.uniform(-1, 1), w)[None, :]
        gy = np.linspace(random.uniform(-1, 1), random.uniform(-1, 1), h)[:, None]
        shade = 1 - random.uniform(0.05, 0.4) * s * np.clip((gx + gy + 2) / 4, 0, 1)
        out = out * shade
    # 6) ぼけ
    if random.random() < 0.5 * s:
        k = random.choice([3, 3, 5])
        out = cv2.GaussianBlur(out, (k, k), random.uniform(0.3, 1.2) * s)
    # 7) ノイズ
    if random.random() < 0.6 * s:
        out = out + np.random.normal(0, random.uniform(2, 12) * s, out.shape)
    out = np.clip(out, 0, 255).astype(np.uint8)
    # 8) JPEG の劣化
    if random.random() < 0.5 * s:
        q = random.randint(35, 90)
        ok, buf = cv2.imencode('.jpg', out, [cv2.IMWRITE_JPEG_QUALITY, q])
        if ok:
            out = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    return out


def to_model_input(img, height=192, max_width=2048):
    """高さをそろえる（横は比率のまま。長すぎれば縮める）"""
    h, w = img.shape
    nw = max(32, int(round(w * height / h)))
    if nw > max_width:
        nw = max_width
    return cv2.resize(img, (nw, height), interpolation=cv2.INTER_AREA)
