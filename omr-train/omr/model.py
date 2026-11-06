"""楽譜1段の画像 → 記号列 を読む AI（画像を読む部分 + 文章を書く部分）

画像を読む部分（エンコーダ）: 畳み込み（CNN）で縦横 1/16 に縮めた特徴の地図を作り、
  縦・横の位置の情報を足してから Transformer で全体を見渡す。音の高さは縦の位置で決まるので、
  縦方向も潰さずに残す（楽譜の段を横長の1列にしてしまうと、高さを読み違えやすい）。
文章を書く部分（デコーダ）: これまでに書いた記号と画像の特徴を見て、次の記号を1つずつ書く。
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from .vocab import TOKENS, PAD


class ResBlock(nn.Module):
    def __init__(self, cin, cout, stride):
        super().__init__()
        self.c1 = nn.Conv2d(cin, cout, 3, stride, 1, bias=False)
        self.b1 = nn.BatchNorm2d(cout)
        self.c2 = nn.Conv2d(cout, cout, 3, 1, 1, bias=False)
        self.b2 = nn.BatchNorm2d(cout)
        self.sc = None if (cin == cout and stride == 1) else nn.Sequential(nn.Conv2d(cin, cout, 1, stride, bias=False), nn.BatchNorm2d(cout))

    def forward(self, x):
        y = F.relu(self.b1(self.c1(x)))
        y = self.b2(self.c2(y))
        return F.relu(y + (x if self.sc is None else self.sc(x)))


class MHA(nn.Module):
    """注意（attention）の仕組み。ONNX に書き出しても長さが変えられるよう、形の計算を自前で書く"""

    def __init__(self, d, heads, dropout=0.1):
        super().__init__()
        self.h = heads
        self.dk = d // heads
        self.q = nn.Linear(d, d)
        self.k = nn.Linear(d, d)
        self.v = nn.Linear(d, d)
        self.o = nn.Linear(d, d)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, mem, bias=None):
        """x: (B,T,D) / mem: (B,S,D) / bias: (B or 1, 1, T or 1, S) に足す値（見ない所は -1e9）"""
        B, T, D = x.shape
        q = self.q(x).view(B, -1, self.h, self.dk).transpose(1, 2)
        k = self.k(mem).view(B, -1, self.h, self.dk).transpose(1, 2)
        v = self.v(mem).view(B, -1, self.h, self.dk).transpose(1, 2)
        a = torch.matmul(q, k.transpose(-1, -2)) * (1.0 / math.sqrt(self.dk))
        if bias is not None:
            a = a + bias
        a = self.drop(torch.softmax(a, -1))
        y = torch.matmul(a, v).transpose(1, 2).reshape(B, -1, D)
        return self.o(y)


class FF(nn.Module):
    def __init__(self, d, dropout=0.1):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d, d * 4), nn.GELU(), nn.Dropout(dropout), nn.Linear(d * 4, d))

    def forward(self, x):
        return self.net(x)


class EncLayer(nn.Module):
    def __init__(self, d, heads, dropout=0.1):
        super().__init__()
        self.n1, self.n2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.att, self.ff = MHA(d, heads, dropout), FF(d, dropout)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, bias):
        h = self.n1(x)
        x = x + self.drop(self.att(h, h, bias))
        return x + self.drop(self.ff(self.n2(x)))


class DecLayer(nn.Module):
    def __init__(self, d, heads, dropout=0.1):
        super().__init__()
        self.n1, self.n2, self.n3 = nn.LayerNorm(d), nn.LayerNorm(d), nn.LayerNorm(d)
        self.sa, self.ca, self.ff = MHA(d, heads, dropout), MHA(d, heads, dropout), FF(d, dropout)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, mem, self_bias, mem_bias):
        h = self.n1(x)
        x = x + self.drop(self.sa(h, h, self_bias))
        x = x + self.drop(self.ca(self.n2(x), mem, mem_bias))
        return x + self.drop(self.ff(self.n3(x)))


def pad_bias(kpm):
    """詰め物の位置（True）を見ないようにする値: (B,1,1,S)"""
    if kpm is None:
        return None
    return kpm[:, None, None, :].float() * -1e9


class Encoder(nn.Module):
    def __init__(self, d=256, layers=4, heads=8, max_rows=32, max_cols=512):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 2, 1, bias=False), nn.BatchNorm2d(32), nn.ReLU())  # 1/2
        self.cnn = nn.Sequential(
            ResBlock(32, 64, 2), ResBlock(64, 64, 1),          # 1/4
            ResBlock(64, 128, 2), ResBlock(128, 128, 1),       # 1/8
            ResBlock(128, d, 2), ResBlock(d, d, 1), ResBlock(d, d, 1),  # 1/16
        )
        self.row = nn.Embedding(max_rows, d)
        self.col = nn.Embedding(max_cols, d)
        self.layers = nn.ModuleList([EncLayer(d, heads) for _ in range(layers)])
        self.norm = nn.LayerNorm(d)

    def forward(self, img, img_mask=None):
        """img: (B,1,H,W) 0〜1（白=1）。img_mask: (B,W) 余白（詰め物）の列が True"""
        x = self.cnn(self.stem(1.0 - img))  # 黒を大きな値に
        B, C, H, W = x.shape
        rows = torch.arange(H, device=x.device)
        cols = torch.arange(W, device=x.device)
        pos = self.row(rows)[:, None, :] + self.col(cols)[None, :, :]  # (H,W,C)
        x = x.permute(0, 2, 3, 1) + pos[None]
        x = x.reshape(B, H * W, C)
        kpm = None
        if img_mask is not None:
            m = F.max_pool1d(img_mask.float()[:, None, :], 16, 16, ceil_mode=True)[:, 0, :W] > 0.5  # (B,W)
            kpm = m[:, None, :].expand(B, H, W).reshape(B, H * W)
        bias = pad_bias(kpm)
        for l in self.layers:
            x = l(x, bias)
        return self.norm(x), kpm


class Decoder(nn.Module):
    def __init__(self, d=256, layers=6, heads=8, max_len=768):
        super().__init__()
        self.emb = nn.Embedding(len(TOKENS), d, padding_idx=PAD)
        self.pos = nn.Embedding(max_len, d)
        self.layers = nn.ModuleList([DecLayer(d, heads) for _ in range(layers)])
        self.norm = nn.LayerNorm(d)
        self.out = nn.Linear(d, len(TOKENS))
        self.d = d

    def forward(self, tokens, memory, mem_kpm=None):
        T = tokens.shape[1]
        pos = torch.arange(T, device=tokens.device)
        x = self.emb(tokens) * math.sqrt(self.d) + self.pos(pos)[None]
        # 先の記号を見ない（因果マスク）。詰め物は答えの側で無視するので、ここでは隠さない
        causal = (pos[None, :] > pos[:, None]).float() * -1e9  # (T,T)
        self_bias = causal[None, None]
        mem_bias = pad_bias(mem_kpm)
        for l in self.layers:
            x = l(x, memory, self_bias, mem_bias)
        return self.out(self.norm(x))


class OMRModel(nn.Module):
    def __init__(self, d=256, enc_layers=4, dec_layers=6, heads=8):
        super().__init__()
        self.encoder = Encoder(d, enc_layers, heads)
        self.decoder = Decoder(d, dec_layers, heads)

    def forward(self, img, img_mask, tokens_in):
        mem, kpm = self.encoder(img, img_mask)
        return self.decoder(tokens_in, mem, kpm)

    @torch.no_grad()
    def greedy(self, img, max_len=700, bos=1, eos=2):
        """1枚ずつ、記号を順に書いていく（いちばん確からしい記号を選ぶ）"""
        mem, kpm = self.encoder(img, None)
        out = torch.full((img.shape[0], 1), bos, dtype=torch.long, device=img.device)
        done = torch.zeros(img.shape[0], dtype=torch.bool, device=img.device)
        for _ in range(max_len):
            logits = self.decoder(out, mem, kpm)[:, -1]
            nxt = logits.argmax(-1)
            nxt = torch.where(done, torch.full_like(nxt, PAD), nxt)
            out = torch.cat([out, nxt[:, None]], 1)
            done |= nxt == eos
            if done.all():
                break
        return out[:, 1:]


def count_params(m):
    return sum(p.numel() for p in m.parameters())
