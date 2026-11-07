"""楽譜の画像を読んで、記号列を表示する（学習の結果を自分の楽譜で試す用）

使い方: python -m omr.predict --ckpt run1/best.pt  画像1.jpg 画像2.png ...
ページ全体の画像なら、大譜表を1段ずつ自動で切り出して読む（切り出した画像は crops/ に保存）。
"""
import argparse
import os

import cv2
import torch

from .model import OMRModel
from .render import to_model_input
from .systems import grand_systems
from .vocab import decode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--single', action='store_true', help='切り出さずに、画像全体を1段として読む')
    ap.add_argument('images', nargs='+')
    a = ap.parse_args()
    dev = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    st = torch.load(a.ckpt, map_location=dev)
    model = OMRModel(**st['cfg']).to(dev)
    model.load_state_dict(st['model'])
    model.eval()
    os.makedirs('crops', exist_ok=True)
    for p in a.images:
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print('読めない画像:', p)
            continue
        # 大きすぎる写真は縮める（五線の間が 8〜20 画素くらいになる大きさ）
        if max(img.shape) > 2600:
            f = 2600 / max(img.shape)
            img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        crops = [] if a.single else [c for c, _ in grand_systems(img)]
        if not crops:
            crops = [img]
        print(f'== {p}（{len(crops)}段）')
        for j, c in enumerate(crops):
            x = to_model_input(c, 192)
            cv2.imwrite(f'crops/{os.path.splitext(os.path.basename(p))[0]}_{j + 1}.png', x)
            t = torch.from_numpy(x).float()[None, None].to(dev) / 255.0
            toks = decode(model.greedy(t)[0].tolist())
            print(f'-- {j + 1}段目\n' + ' '.join(toks).replace(' | ', ' |\n'))


if __name__ == '__main__':
    main()
