"""練習用データ（楽譜画像と正解の記号列）をたくさん作る。

使い方:  python -m omr.make_data --out data/train --count 200000 --workers 8
できるもの: out/images/000000123.jpg ... と out/labels.tsv（ファイル名<TAB>画像の幅<TAB>記号列）
"""
import argparse
import os
import random
import sys
import time
from multiprocessing import Pool

import cv2
import numpy as np

HEIGHT = 192


def _work(args):
    idx, out, seed_base, clean_ratio = args
    # Verovio の警告は大量に出るので捨てる
    try:
        import verovio
        verovio.enableLog(verovio.LOG_OFF)
    except Exception:
        pass
    from .music import gen_system
    from .render import render_clean, augment, to_model_input
    seed = seed_base + idx
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))
    for _ in range(3):  # まれに描画に失敗するので作り直す
        try:
            xml, toks = gen_system()
            img = render_clean(xml)
            if random.random() >= clean_ratio:
                img = augment(img, strength=random.uniform(0.4, 1.0))
            img = to_model_input(img, HEIGHT)
            name = f'{idx:09d}.jpg'  # PNG の約3分の1の大きさ（少しの劣化は、学習ではむしろ写真に近づく）
            cv2.imwrite(os.path.join(out, 'images', name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            return f'{name}\t{img.shape[1]}\t{" ".join(toks)}'
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--count', type=int, default=1000)
    ap.add_argument('--start', type=int, default=0, help='続きから作るときの番号')
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 2)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--clean', type=float, default=0.25, help='汚さない（きれいな）画像の割合')
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, 'images'), exist_ok=True)
    t0 = time.time()
    jobs = [(i, a.out, a.seed * 1000003, a.clean) for i in range(a.start, a.start + a.count)]
    n = 0
    with open(os.path.join(a.out, 'labels.tsv'), 'a', encoding='utf-8') as f, Pool(a.workers) as pool:
        for line in pool.imap_unordered(_work, jobs, chunksize=16):
            if line:
                f.write(line + '\n')
                n += 1
                if n % 1000 == 0:
                    el = time.time() - t0
                    print(f'{n}/{a.count}  {n / el:.1f}枚/秒  残り約{(a.count - n) / max(1e-9, n / el) / 60:.0f}分', flush=True)
    print(f'完了: {n}枚（{(time.time() - t0) / 60:.1f}分）')


if __name__ == '__main__':
    sys.exit(main())
