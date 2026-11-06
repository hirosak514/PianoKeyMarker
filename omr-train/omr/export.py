"""学習した AI を、アプリ（ブラウザ）で動かせる形（ONNX）に変える。

使い方: python -m omr.export --ckpt run1/best.pt --out run1/onnx
できるもの: encoder.onnx（画像 → 特徴）, decoder.onnx（これまでの記号 + 特徴 → 次の記号の確からしさ）, vocab.json
"""
import argparse
import json
import os

import torch

from .model import OMRModel
from .vocab import TOKENS


class DecStep(torch.nn.Module):
    """アプリ用: 最後の位置の確からしさだけを返す"""

    def __init__(self, dec):
        super().__init__()
        self.dec = dec

    def forward(self, tokens, memory):
        return self.dec(tokens, memory, None)[:, -1, :]


class Enc(torch.nn.Module):
    def __init__(self, enc):
        super().__init__()
        self.enc = enc

    def forward(self, img):
        return self.enc(img, None)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    st = torch.load(a.ckpt, map_location='cpu')
    model = OMRModel(**st['cfg'])
    model.load_state_dict(st['model'])
    model.eval()
    os.makedirs(a.out, exist_ok=True)
    img = torch.ones(1, 1, 192, 640)
    with torch.no_grad():
        mem = Enc(model.encoder)(img)
    torch.onnx.export(Enc(model.encoder), (img,), os.path.join(a.out, 'encoder.onnx'), input_names=['image'], output_names=['memory'],
                      dynamic_axes={'image': {3: 'width'}, 'memory': {1: 'positions'}}, opset_version=17, dynamo=False)
    toks = torch.tensor([[1, 5, 6]], dtype=torch.long)
    torch.onnx.export(DecStep(model.decoder), (toks, mem), os.path.join(a.out, 'decoder.onnx'), input_names=['tokens', 'memory'], output_names=['logits'],
                      dynamic_axes={'tokens': {1: 'length'}, 'memory': {1: 'positions'}}, opset_version=17, dynamo=False)
    with open(os.path.join(a.out, 'vocab.json'), 'w', encoding='utf-8') as f:
        json.dump({'tokens': TOKENS, 'height': 192, 'bos': 1, 'eos': 2, 'pad': 0, 'step': st.get('step')}, f, ensure_ascii=False)
    # 書き出した ONNX で同じ答えになるか確かめる
    try:
        import numpy as np
        import onnxruntime as ort
        e = ort.InferenceSession(os.path.join(a.out, 'encoder.onnx'))
        d = ort.InferenceSession(os.path.join(a.out, 'decoder.onnx'))
        m2 = e.run(None, {'image': img.numpy()})[0]
        l2 = d.run(None, {'tokens': toks.numpy(), 'memory': m2})[0]
        model.eval()
        with torch.no_grad():
            l1 = DecStep(model.decoder)(toks, Enc(model.encoder)(img)).numpy()
        print('ONNX の確認: 最大の差', float(np.abs(l1 - l2).max()))
    except ImportError:
        print('（onnxruntime が無いので、確認は省きました）')
    print('書き出しました:', a.out)


if __name__ == '__main__':
    main()
