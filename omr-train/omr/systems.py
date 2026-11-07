"""ページの画像から、大譜表（ピアノの2段）を1段ずつ切り出す（試し読み用。アプリでは systems.js が同じ役目）"""
import cv2, numpy as np

def find_staves(img):
    """五線を探す: 戻り値 [(上の線の y, 下の線の y, 左端 x, 右端 x)]"""
    b = (cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15) > 0).astype(np.uint8)
    h, w = b.shape
    lines = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 25), 1)))
    prof = lines.sum(1).astype(np.float32)
    if prof.max() <= 0:
        return [], b
    rows = np.where(prof > prof.max() * 0.35)[0]
    cs = []
    for r in rows:
        if cs and r - cs[-1][-1] <= 2:
            cs[-1].append(r)
        else:
            cs.append([r])
    c = [float(np.mean(x)) for x in cs]
    staves, used = [], set()
    for i in range(len(c)):
        if i in used:
            continue
        best = None
        for j in range(i + 1, min(i + 3, len(c))):
            for div in (1, 2):  # 間の線が1本見つからない場合
                s = (c[j] - c[i]) / div
                if not 4 <= s <= 40:
                    continue
                hit = [k for k in range(len(c)) if any(abs(c[k] - (c[i] + n * s)) <= max(1.5, s * 0.18) for n in range(5))]
                if len(hit) >= 4 and (best is None or len(hit) > len(best[1])):
                    best = (s, hit)
        if best:
            s, hit = best
            top, bot = c[i], c[i] + 4 * s
            used |= set(hit)
            ys = [int(round(top + n * s)) for n in range(5)]
            xs = np.where(lines[ys[2] - 1:ys[2] + 2].max(0) > 0)[0]
            x0, x1 = (int(xs.min()), int(xs.max())) if len(xs) else (0, w - 1)
            staves.append((top, bot, x0, x1))
    return staves, b


def grand_systems(img):
    """大譜表（2段が左端の線でつながっている所）を切り出す。つながりが見えなければ、上から2段ずつ"""
    st, b = find_staves(img)
    # 重なっている（同じ五線を2回見つけた）ものを除く
    st.sort(key=lambda t: t[0])
    clean = []
    for t in st:
        if clean and t[0] < clean[-1][1]:
            if (t[1] - t[0]) > (clean[-1][1] - clean[-1][0]):
                clean[-1] = t
            continue
        clean.append(t)
    st = clean
    h = img.shape[0]

    def joined(a, c):
        y0, y1 = int(a[1]) + 2, int(c[0]) - 2
        if y1 <= y0:
            return True
        lo, hi = max(0, min(a[2], c[2]) - 30), max(a[2], c[2]) + 12
        return max((b[y0:y1, xx:xx + 3].max(1) > 0).mean() for xx in range(lo, hi)) > 0.85  # 2段をつなぐ縦線・括弧

    pairs, k, used = [], 0, set()
    while k < len(st) - 1:
        if joined(st[k], st[k + 1]):
            pairs.append((k, k + 1)); used |= {k, k + 1}; k += 2
        else:
            k += 1
    # つながりが見えなかった残りの段は、隣どうしで組にする
    rest = [i for i in range(len(st)) if i not in used]
    i = 0
    while i < len(rest) - 1:
        if rest[i + 1] == rest[i] + 1:
            pairs.append((rest[i], rest[i + 1])); i += 2
        else:
            i += 1
    pairs = [(st[x], st[y]) for x, y in sorted(pairs)]
    out = []
    for a, c in pairs:
        sp = (a[1] - a[0]) / 4
        y0 = int(max(0, a[0] - sp * 4)); y1 = int(min(h, c[1] + sp * 4))
        x0 = int(max(0, min(a[2], c[2]) - sp * 2)); x1 = int(min(img.shape[1], max(a[3], c[3]) + sp))
        out.append((img[y0:y1, x0:x1], (x0, y0, x1, y1)))
    return out
