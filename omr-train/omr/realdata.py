"""本物の楽譜（画像・PDF ＋ その曲の MusicXML）から、学習用のデータを作る。

使い方:
  python -m omr.realdata --src 楽譜フォルダ --out data/real --ckpt run1/best.pt
楽譜フォルダの中は、1曲ごとに1つのフォルダ:
  楽譜フォルダ/
    エリーゼのために/        ← 曲の名前（何でもよい）
      score.musicxml         ← その曲の MusicXML（.musicxml / .xml / .mxl のどれか1つ）
      page1.jpg page2.jpg    ← 楽譜の画像（名前の順にページとして並べる）。PDF でもよい
しくみ:
  1. 画像から大譜表（ピアノの2段）を1段ずつ切り出す（omr/systems.py）
  2. MusicXML を小節ごとの記号に直す（このファイルの musicxml_measures）
  3. どの段にどの小節が載っているかは、画像の版と MusicXML の段の区切りが違うことが多いので、
     今の AI で各段を試しに読み、その読みに最も近くなるように小節を割り当てる（align）
  4. 割り当てがうまくいかなかった段（AI の読みとかけ離れている＝切り出し失敗など）は使わない
できるもの: out/train（学習用）, out/val（確かめ用: 1曲おき、または10段に1段）, out/report.tsv（段ごとの結果）
"""
import argparse
import glob
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import cv2
import numpy as np

from .render import to_model_input
from .systems import grand_systems
from .vocab import INDEX

TYPE_DUR = {'breve': 'd1', 'whole': 'd1', 'half': 'd2', 'quarter': 'd4', 'eighth': 'd8', '16th': 'd16', '32nd': 'd32', '64th': 'd32', '128th': 'd32'}
ACC = {'sharp': '#', 'flat': 'b', 'natural': 'n', 'double-sharp': 'x', 'sharp-sharp': 'x', 'flat-flat': 'bb',
       'natural-sharp': '#', 'natural-flat': 'b'}
ALTER_ACC = {2: 'x', 1: '#', 0: 'n', -1: 'b', -2: 'bb'}
STEPS = 'CDEFGAB'
SHARPS, FLATS = 'FCGDAEB', 'BEADGCF'


# ---------------- MusicXML → 小節ごとの記号 ----------------

def read_xml_text(path):
    if path.lower().endswith('.mxl'):
        z = zipfile.ZipFile(path)
        root = None
        if 'META-INF/container.xml' in z.namelist():
            c = ET.fromstring(z.read('META-INF/container.xml'))
            rf = c.find('.//{*}rootfile')
            if rf is not None:
                root = rf.get('full-path')
        if not root:
            root = next(n for n in z.namelist() if n.lower().endswith(('.xml', '.musicxml')) and not n.startswith('META-INF'))
        return z.read(root)
    with open(path, 'rb') as f:
        return f.read()


def strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]
    return root


def key_alter(fifths, step):
    if fifths > 0:
        return 1 if step in SHARPS[:fifths] else 0
    if fifths < 0:
        return -1 if step in FLATS[:-fifths] else 0
    return 0


def dur_token(note, divisions):
    t = note.findtext('type')
    if t in TYPE_DUR:
        return TYPE_DUR[t], len(note.findall('dot'))
    # type が無いとき: 長さから推定（3連符などは近い長さ）
    d = float(note.findtext('duration') or 0) / max(1, divisions)
    for q, tok in ((4, 'd1'), (2, 'd2'), (1, 'd4'), (0.5, 'd8'), (0.25, 'd16'), (0.125, 'd32')):
        for dots, f in ((0, 1), (1, 1.5), (2, 1.75)):
            if abs(d - q * f) < 1e-3:
                return tok, dots
    return 'd4', 0


def pick_streams(score):
    """ピアノの2段にあたる (part, staff番号) を2つ選ぶ"""
    parts = score.findall('part')
    for p in parts:
        st = p.find('.//attributes/staves')
        if st is not None and st.text and int(st.text) >= 2:
            return [(p, 1), (p, 2)]
    if len(parts) >= 2:
        return [(parts[0], None), (parts[1], None)]
    if parts:
        return [(parts[0], None)]
    return []


def musicxml_measures(path):
    """戻り値: 小節のリスト。各小節 = {'tokens': [...], 'clefs': [..], 'fifths': n, 'time': 'a/b' or None,
    'time_shown': bool, 'tuplet': bool}"""
    score = strip_ns(ET.fromstring(read_xml_text(path)))
    if score.tag == 'score-timewise':
        raise ValueError('timewise 形式の MusicXML は使えません（partwise で書き出し直してください）')
    streams = pick_streams(score)
    if not streams:
        raise ValueError('楽譜（part）がありません')
    has_acc = any(True for _ in score.iter('accidental'))
    per_stream = []
    for part, staff_no in streams:
        per_stream.append(stream_measures(part, staff_no, has_acc))
    n = max(len(s) for s in per_stream)
    out = []
    for i in range(n):
        ms = [s[i] if i < len(s) else None for s in per_stream]
        first = next(m for m in ms if m)
        toks = []
        for k, m in enumerate(ms):
            if k == 1:
                toks.append('<s2>')
            if m:
                toks += m['tokens']
        out.append({'tokens': toks, 'clefs': [m['clef'] if m else 'clef:F4' for m in ms], 'fifths': first['fifths'],
                    'time': first['time'], 'time_shown': first['time_shown'], 'tuplet': any(m and m['tuplet'] for m in ms)})
    return out


def stream_measures(part, staff_no, has_acc):
    divisions, fifths, time = 1, 0, '4/4'
    clefs = {}
    out = []
    pend_tie = {}  # (voice) → set of (step, oct) 前の音からタイで続く
    for mel in part.findall('measure'):
        time_shown = False
        voices = {}  # voice → events
        order = []
        tuplet = False
        last_ev = {}
        for el in mel:
            if el.tag == 'attributes':
                if el.findtext('divisions'):
                    divisions = int(float(el.findtext('divisions')))
                k = el.find('key/fifths')
                if k is not None and k.text:
                    fifths = int(k.text)
                t = el.find('time')
                if t is not None and t.findtext('beats'):
                    beats = sum(int(x) for x in re.findall(r'\d+', t.findtext('beats')))
                    time = f'{beats}/{t.findtext("beat-type")}'
                    if t.get('print-object') != 'no':
                        time_shown = True
                for c in el.findall('clef'):
                    num = int(c.get('number') or 1)
                    sign, line = c.findtext('sign'), c.findtext('line')
                    tok = {'G': 'clef:G2', 'F': 'clef:F4'}.get(sign, f'clef:C{line or 3}' if sign == 'C' else 'clef:G2')
                    clefs[num] = tok
                continue
            if el.tag != 'note':
                continue
            if el.find('grace') is not None or el.find('cue') is not None:
                continue
            st = int(el.findtext('staff') or 1)
            if staff_no is not None and st != staff_no:
                continue
            if el.get('print-object') == 'no':
                continue
            v = el.findtext('voice') or '1'
            if v not in voices:
                voices[v] = []
                order.append(v)
            if el.find('time-modification') is not None:
                tuplet = True
            dt, dots = dur_token(el, divisions)
            chord = el.find('chord') is not None
            if el.find('rest') is not None:
                r = el.find('rest')
                voices[v].append({'rest': True, 'full': r.get('measure') == 'yes', 'd': dt, 'dots': dots,
                                  'dur': float(el.findtext('duration') or 0) / max(1, divisions)})
                last_ev[v] = None
                continue
            p = el.find('pitch')
            if p is None:
                continue
            step, octv = p.findtext('step'), int(p.findtext('octave'))
            alter = int(round(float(p.findtext('alter') or 0)))
            acc_el = el.findtext('accidental')
            ties = [t.get('type') for t in el.findall('tie')]
            nt = {'step': step, 'oct': octv, 'alter': alter, 'acc': ACC.get(acc_el) if acc_el else None,
                  'tie_start': 'start' in ties, 'tie_stop': 'stop' in ties}
            if chord and last_ev.get(v) is not None:
                last_ev[v]['notes'].append(nt)
            else:
                ev = {'rest': False, 'd': dt, 'dots': dots, 'notes': [nt]}
                voices[v].append(ev)
                last_ev[v] = ev
        # 記号に直す
        num = 1 if staff_no is None else staff_no
        mlen = eval_time(time)
        toks = []
        carry = {}
        vs = sorted(order, key=lambda x: (int(x) if x.isdigit() else 99, x))
        for vi, v in enumerate(vs):
            evs = voices[v]
            if vi:
                toks.append('<v>')
            if len(evs) == 1 and evs[0]['rest'] and (evs[0]['full'] or abs(evs[0]['dur'] - mlen) < 1e-3):
                toks.append('R')
                continue
            for ev in evs:
                if ev['rest']:
                    toks += ['r', ev['d']] + ['.'] * min(2, ev['dots'])
                    continue
                notes = sorted(ev['notes'], key=lambda n: (n['oct'] * 7 + STEPS.index(n['step'])))
                for n in notes:
                    ck = (n['step'], n['oct'])
                    if has_acc:
                        acc = n['acc']
                    else:
                        cur = carry.get(ck, key_alter(fifths, n['step']))
                        acc = None if (n['tie_stop'] or n['alter'] == cur) else ALTER_ACC.get(n['alter'])
                    carry[ck] = n['alter']
                    if acc:
                        toks.append(acc)
                    toks.append(f"{n['step']}{n['oct']}")
                toks.append(ev['d'])
                toks += ['.'] * min(2, ev['dots'])
                if any(n['tie_start'] for n in notes):
                    toks.append('~')
        out.append({'tokens': toks, 'clef': clefs.get(num, 'clef:G2' if num == 1 else 'clef:F4'), 'fifths': fifths,
                    'time': time, 'time_shown': time_shown, 'tuplet': tuplet})
    return out


def eval_time(t):
    a, b = t.split('/')
    return int(a) * 4 / int(b)


def system_tokens(measures, s, e, first):
    """小節 s〜e-1 を1段の記号列にする（段の頭: 音部記号・調・（出ていれば）拍子）"""
    m0 = measures[s]
    head = list(m0['clefs'][:2]) + [f"key:{max(-7, min(7, m0['fifths']))}"]
    if first or m0['time_shown']:
        t = f"time:{m0['time']}"
        if t in INDEX:
            head.append(t)
    body = []
    for m in measures[s:e]:
        body += m['tokens'] + ['|']
    return head + body


# ---------------- 画像 ----------------

def load_pages(folder):
    files = sorted(f for f in glob.glob(os.path.join(folder, '*')) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf', '.tif', '.tiff', '.bmp', '.webp')))
    pages = []
    for f in files:
        if f.lower().endswith('.pdf'):
            import fitz  # PyMuPDF
            doc = fitz.open(f)
            for pg in doc:
                pix = pg.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
                img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
                pages.append((f'{os.path.basename(f)}#{pg.number + 1}', img.copy()))
        else:
            img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                pages.append((os.path.basename(f), img))
    out = []
    for name, img in pages:
        if max(img.shape) > 2600:
            f = 2600 / max(img.shape)
            img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        out.append((name, img))
    return out


# ---------------- 今の AI で試しに読む ----------------

class Reader:
    def __init__(self, ckpt=None, onnx_dir=None):
        if onnx_dir:
            import onnxruntime as ort
            self.enc = ort.InferenceSession(os.path.join(onnx_dir, 'encoder.onnx'))
            self.dec = ort.InferenceSession(os.path.join(onnx_dir, 'decoder.onnx'))
            self.kind = 'onnx'
        else:
            import torch
            from .model import OMRModel
            self.torch = torch
            self.dev = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            st = torch.load(ckpt, map_location=self.dev)
            self.model = OMRModel(**st['cfg']).to(self.dev).eval()
            self.model.load_state_dict(st['model'])
            self.kind = 'torch'

    def read(self, x):
        """x: 高さ192の uint8 画像 → 記号列"""
        from .vocab import decode
        t = (x.astype(np.float32) / 255.0)[None, None]
        if self.kind == 'torch':
            with self.torch.no_grad():
                ids = self.model.greedy(self.torch.from_numpy(t).to(self.dev), max_len=700)[0].tolist()
            return decode(ids)
        mem = self.enc.run(None, {'image': t})[0]
        toks = [1]
        for _ in range(700):
            n = int(self.dec.run(None, {'tokens': np.array([toks], np.int64), 'memory': mem})[0][0].argmax())
            toks.append(n)
            if n == 2:
                break
        return decode(toks[1:])


# ---------------- 段と小節の割り当て ----------------

def dist(a, b):
    from rapidfuzz.distance import Levenshtein
    ia = [INDEX.get(t, 3) for t in a]
    ib = [INDEX.get(t, 3) for t in b]
    return Levenshtein.distance(ia, ib)


def body_of(toks):
    i = 0
    while i < len(toks) and re.match(r'^(clef|key|time):', toks[i]):
        i += 1
    return toks[i:]


def align(preds, measures, max_per_system=16, window=10):
    """段 i に小節 [s_i, s_{i+1}) を割り当てる。AI の読みとの違い（編集距離）の合計が最小になるように。
    戻り値: [(s, e, 違いの割合)]（段の数だけ）"""
    nS, nM = len(preds), len(measures)
    bodies = [body_of(p) for p in preds]
    guess = [max(1, p.count('|')) for p in preds]
    # 小節ごとの記号列（つなげる手間を省くため、前もって作る）
    mt = [m['tokens'] + ['|'] for m in measures]
    INF = float('inf')
    best = [dict() for _ in range(nS + 1)]
    best[0][0] = (0.0, None)
    cum = 0
    for i in range(nS):
        lo_c, hi_c = max(0, cum - window), cum + window
        cum += guess[i]
        for s, (cost, _) in best[i].items():
            if not (lo_c <= s <= hi_c):
                continue
            seq = []
            for k in range(1, max_per_system + 1):
                e = s + k
                if e > nM:
                    break
                seq = seq + mt[e - 1]
                # 残りの段が少なくとも1小節ずつ持てるように
                if nM - e < nS - i - 1:
                    break
                d = dist(bodies[i], seq)
                c = cost + d
                if e not in best[i + 1] or c < best[i + 1][e][0]:
                    best[i + 1][e] = (c, (s, d, len(seq)))
    # 最後は全部の小節を使い切るのが理想。ダメなら一番近いところで終わる
    end = nM if nM in best[nS] else (max(best[nS], key=lambda e: (e, -best[nS][e][0])) if best[nS] else None)
    if end is None:
        return None
    res = []
    e = end
    for i in range(nS, 0, -1):
        _, (s, d, ln) = best[i][e]
        res.append((s, e, d / max(1, ln)))
        e = s
    return res[::-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='曲ごとのフォルダが入ったフォルダ')
    ap.add_argument('--out', required=True)
    ap.add_argument('--ckpt', help='今の AI（best.pt）')
    ap.add_argument('--onnx', help='（--ckpt の代わりに）ONNX のフォルダ')
    ap.add_argument('--max-diff', type=float, default=0.45, help='AI の読みとの違いがこの割合を超える段は使わない')
    a = ap.parse_args()
    reader = Reader(a.ckpt, a.onnx)
    songs = sorted(d for d in glob.glob(os.path.join(a.src, '*')) if os.path.isdir(d))
    if not songs and glob.glob(os.path.join(a.src, '*.*xml')) + glob.glob(os.path.join(a.src, '*.mxl')):
        songs = [a.src]
    for sub in ('train', 'val'):
        os.makedirs(os.path.join(a.out, sub, 'images'), exist_ok=True)
    labels = {'train': open(os.path.join(a.out, 'train', 'labels.tsv'), 'w', encoding='utf-8'),
              'val': open(os.path.join(a.out, 'val', 'labels.tsv'), 'w', encoding='utf-8')}
    report = open(os.path.join(a.out, 'report.tsv'), 'w', encoding='utf-8')
    report.write('曲\tページ\t段\t小節\t違い\t使う\n')
    total = {'train': 0, 'val': 0, 'skip': 0}
    for si, song in enumerate(songs):
        name = os.path.basename(song.rstrip('/'))
        xs = [f for f in glob.glob(os.path.join(song, '*')) if f.lower().endswith(('.musicxml', '.xml', '.mxl'))]
        if not xs:
            print(f'× {name}: MusicXML がありません（.musicxml / .xml / .mxl）')
            continue
        try:
            measures = musicxml_measures(xs[0])
        except Exception as e:
            print(f'× {name}: MusicXML を読めませんでした（{e}）')
            continue
        pages = load_pages(song)
        crops = []
        for pname, img in pages:
            for j, (c, box) in enumerate(grand_systems(img)):
                crops.append((pname, j + 1, to_model_input(c, 192)))
        if not crops:
            print(f'× {name}: 画像から大譜表が見つかりませんでした')
            continue
        print(f'== {name}: {len(pages)}ページ・{len(crops)}段・MusicXML {len(measures)}小節。今の AI で試し読み中…', flush=True)
        preds = [reader.read(x) for _, _, x in crops]
        al = align(preds, measures)
        if al is None:
            print(f'× {name}: 段と小節を対応づけられませんでした')
            continue
        used = 0
        for k, ((pname, j, x), (s, e, diff)) in enumerate(zip(crops, al)):
            ok = diff <= a.max_diff and not any(m['tuplet'] for m in measures[s:e])
            why = '' if ok else ('3連符など（まだ書けない記号）' if diff <= a.max_diff else '読みとかけ離れている')
            # 確かめ用: 曲が4曲以上なら4曲に1曲をまるごと、少なければ5段に1段
            gidx = total['train'] + total['val'] + total['skip']
            sub = 'val' if (len(songs) >= 4 and si % 4 == 3) or (len(songs) < 4 and gidx % 5 == 4) else 'train'
            report.write(f'{name}\t{pname}\t{j}\t{s + 1}-{e}\t{diff:.2f}\t{"○" if ok else "×" + why}\n')
            if not ok:
                total['skip'] += 1
                continue
            toks = system_tokens(measures, s, e, s == 0)
            fn = re.sub(r'[^\w\-]+', '_', f'{name}_{pname}_{j}') + '.jpg'
            cv2.imwrite(os.path.join(a.out, sub, 'images', fn), x, [cv2.IMWRITE_JPEG_QUALITY, 93])
            labels[sub].write(f'{fn}\t{x.shape[1]}\t{" ".join(toks)}\n')
            total[sub] += 1
            used += 1
        print(f'   使う段 {used}/{len(crops)}（小節 {al[0][0] + 1}〜{al[-1][1]} に対応づけ）')
    for f in labels.values():
        f.close()
    report.close()
    print(f'\nできました: 学習用 {total["train"]}段 / 確かめ用 {total["val"]}段 / 使わなかった段 {total["skip"]}')
    print('段ごとの結果:', os.path.join(a.out, 'report.tsv'))


if __name__ == '__main__':
    main()
