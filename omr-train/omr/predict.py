"""楽譜1段の画像を読んで、記号列を表示する（学習の結果を自分の楽譜で試す用）

使い方: python -m omr.predict --ckpt run1/best.pt  画像1.png 画像2.jpg ...
画像は「大譜表1段分」を切り出したもの（上下の段が入っていてもよいが、1段だけの方がよく読める）。
"""
import argparse

import cv2
import torch

from .model import OMRModel
from .render import to_model_input
from .vocab import decode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('images', nargs='+')
    a = ap.parse_args()
    dev = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    st = torch.load(a.ckpt, map_location=dev)
    model = OMRModel(**st['cfg']).to(dev)
    model.load_state_dict(st['model'])
    model.eval()
    for p in a.images:
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        img = to_model_input(img, 192)
        x = torch.from_numpy(img).float()[None, None].to(dev) / 255.0
        toks = decode(model.greedy(x)[0].tolist())
        print(f'== {p}\n' + ' '.join(toks).replace(' | ', ' |\n'))


if __name__ == '__main__':
    main()
