"""学習する。

使い方（Colab の例）:
  python -m omr.train --data data/train --val data/val --out /content/drive/MyDrive/chopin-omr/run1 --hours 10
・--out に途中経過（checkpoint）を保存する。止まっても、同じコマンドで続きから再開する。
・GPU が無いときは CPU で動く（とても遅いので、動作確認用）。
"""
import argparse
import json
import math
import os
import random
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, Sampler

from .model import OMRModel, count_params
from .vocab import encode, decode, PAD

HEIGHT = 192


def read_labels(folder, limit=None):
    items = []
    with open(os.path.join(folder, 'labels.tsv'), encoding='utf-8') as f:
        for line in f:
            p = line.rstrip('\n').split('\t')
            if len(p) != 3:
                continue
            items.append((os.path.join(folder, 'images', p[0]), int(p[1]), p[2].split()))
            if limit and len(items) >= limit:
                break
    return items


class SysDataset(Dataset):
    def __init__(self, items, train=True, max_tokens=700):
        self.items = [it for it in items if len(it[2]) + 2 <= max_tokens]
        self.train = train

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        path, w, toks = self.items[i]
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            img = np.full((HEIGHT, max(32, w)), 255, np.uint8)
        if self.train:
            # 軽い追加のゆらぎ（横の伸び縮み・明るさ）
            if random.random() < 0.5:
                s = random.uniform(0.85, 1.15)
                img = cv2.resize(img, (max(32, int(img.shape[1] * s)), HEIGHT), interpolation=cv2.INTER_AREA)
            if random.random() < 0.3:
                img = np.clip(img.astype(np.float32) * random.uniform(0.85, 1.1) + random.uniform(-15, 15), 0, 255).astype(np.uint8)
        return torch.from_numpy(img), torch.tensor(encode(toks), dtype=torch.long)


class WidthBatchSampler(Sampler):
    """幅の近い画像をまとめて1組にする（詰め物を減らす）。1組の画素数の上限で枚数を決める"""

    def __init__(self, items, max_pixels, shuffle=True):
        self.widths = [it[1] for it in items]
        self.max_pixels = max_pixels
        self.shuffle = shuffle

    def batches(self):
        idx = list(range(len(self.widths)))
        if self.shuffle:
            random.shuffle(idx)
        out = []
        for c in range(0, len(idx), 4096):
            chunk = sorted(idx[c:c + 4096], key=lambda i: self.widths[i])
            b, mw = [], 0
            for i in chunk:
                w = self.widths[i]
                if b and max(mw, w) * HEIGHT * (len(b) + 1) > self.max_pixels:
                    out.append(b)
                    b, mw = [], 0
                b.append(i)
                mw = max(mw, w)
            if b:
                out.append(b)
        if self.shuffle:
            random.shuffle(out)
        return out

    def __iter__(self):
        return iter(self.batches())

    def __len__(self):
        return len(self.batches())


def collate(batch):
    W = max(img.shape[1] for img, _ in batch)
    W = int(math.ceil(W / 16) * 16)
    T = max(len(t) for _, t in batch)
    imgs = torch.full((len(batch), 1, HEIGHT, W), 1.0)
    mask = torch.ones((len(batch), W), dtype=torch.bool)
    toks = torch.full((len(batch), T), PAD, dtype=torch.long)
    for i, (img, t) in enumerate(batch):
        w = img.shape[1]
        imgs[i, 0, :, :w] = img.float() / 255.0
        mask[i, :w] = False
        toks[i, :len(t)] = t
    return imgs, mask, toks


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[-1]


def evaluate(model, items, device, n=200, amp_dtype=None):
    """検証用の画像を読み、記号の間違いの割合（SER）を返す"""
    model.eval()
    ds = SysDataset(items[:n], train=False)
    errs = tot = exact = 0
    samples = []
    with torch.no_grad():
        for i in range(len(ds)):
            img, t = ds[i]
            x = (img.float() / 255.0)[None, None].to(device)
            with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
                pred = model.greedy(x)[0].tolist()
            p, g = decode(pred), decode(t.tolist())
            e = edit_distance(p, g)
            errs += e
            tot += len(g)
            exact += e == 0
            if len(samples) < 3:
                samples.append((' '.join(g[:30]), ' '.join(p[:30])))
    model.train()
    return errs / max(1, tot), exact / max(1, len(ds)), samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--val', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--hours', type=float, default=10, help='この時間だけ学習して止まる（再開できる）')
    ap.add_argument('--max-steps', type=int, default=200000)
    ap.add_argument('--lr', type=float, default=3e-4)
    ap.add_argument('--warmup', type=int, default=2000)
    ap.add_argument('--max-pixels', type=int, default=0, help='1組の画素数の上限（0 = GPU のメモリから自動で決める）')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--eval-every', type=int, default=2000)
    ap.add_argument('--eval-n', type=int, default=200, help='検証で読む枚数')
    ap.add_argument('--save-every', type=int, default=1000)
    ap.add_argument('--limit', type=int, default=None, help='（動作確認用）使う枚数の上限')
    ap.add_argument('--d', type=int, default=256)
    ap.add_argument('--enc-layers', type=int, default=4)
    ap.add_argument('--dec-layers', type=int, default=6)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    amp_dtype = None
    if device.type == 'cuda':
        cap = torch.cuda.get_device_capability(0)
        # GTX1080 など古い GPU（Pascal 以前）は半精度の計算がかえって遅いので使わない
        amp_dtype = None if cap[0] < 7 else (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    print('device:', device, torch.cuda.get_device_name(0) if device.type == 'cuda' else '', 'amp:', amp_dtype)
    if not a.max_pixels:
        gb = torch.cuda.get_device_properties(0).total_memory / 2 ** 30 if device.type == 'cuda' else 4
        per = 192 * 1200  # 幅1200の画像1枚分
        a.max_pixels = per * (48 if gb >= 38 else 28 if gb >= 20 else 14 if gb >= 14 else 6)
        print(f'GPU のメモリ {gb:.0f}GB → 1組に幅1200の画像 約{a.max_pixels // per}枚分')

    train_items = read_labels(a.data, a.limit)
    val_items = read_labels(a.val, 400)
    print(f'学習用 {len(train_items)}枚 / 検証用 {len(val_items)}枚')
    ds = SysDataset(train_items, train=True)
    dl = DataLoader(ds, batch_sampler=WidthBatchSampler(ds.items, a.max_pixels), collate_fn=collate,
                    num_workers=a.workers, pin_memory=device.type == 'cuda', persistent_workers=a.workers > 0)

    cfg = {'d': a.d, 'enc_layers': a.enc_layers, 'dec_layers': a.dec_layers, 'heads': 8}
    model = OMRModel(**cfg).to(device)
    print(f'AI の大きさ: {count_params(model) / 1e6:.1f}M')
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    scaler = torch.cuda.amp.GradScaler(enabled=amp_dtype == torch.float16)
    warm = a.warmup

    def lr_at(step):
        if step < warm:
            return a.lr * step / warm
        p = min(1.0, (step - warm) / max(1, a.max_steps - warm))
        return a.lr * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * p)))

    step, best = 0, 1e9
    ck = os.path.join(a.out, 'last.pt')
    if os.path.exists(ck):
        st = torch.load(ck, map_location=device)
        model.load_state_dict(st['model'])
        opt.load_state_dict(st['opt'])
        step, best = st['step'], st.get('best', 1e9)
        print(f'続きから再開します（{step}歩目）')

    def save(path, extra=None):
        d = {'model': model.state_dict(), 'opt': opt.state_dict(), 'step': step, 'best': best, 'cfg': cfg}
        if extra:
            d.update(extra)
        tmp = path + '.tmp'
        torch.save(d, tmp)
        os.replace(tmp, path)

    t_end = time.time() + a.hours * 3600
    t0, seen, loss_avg = time.time(), 0, None
    model.train()
    while step < a.max_steps and time.time() < t_end:
        for imgs, mask, toks in dl:
            imgs, mask, toks = imgs.to(device, non_blocking=True), mask.to(device, non_blocking=True), toks.to(device, non_blocking=True)
            for g in opt.param_groups:
                g['lr'] = lr_at(step)
            with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
                logits = model(imgs, mask, toks[:, :-1])
                loss = F.cross_entropy(logits.float().reshape(-1, logits.shape[-1]), toks[:, 1:].reshape(-1), ignore_index=PAD, label_smoothing=0.05)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            step += 1
            seen += imgs.shape[0]
            loss_avg = loss.item() if loss_avg is None else loss_avg * 0.98 + loss.item() * 0.02
            if step % 50 == 0:
                el = time.time() - t0
                print(f'{step}歩  損失 {loss_avg:.3f}  {seen / el:.0f}枚/秒  学習率 {lr_at(step):.2e}', flush=True)
            if step % a.save_every == 0:
                save(ck)
            if step % a.eval_every == 0:
                ser, ex, smp = evaluate(model, val_items, device, a.eval_n, amp_dtype)
                print(f'== 検証: 記号の間違い {ser * 100:.2f}%  完全に正しい段 {ex * 100:.1f}%')
                for g, p in smp:
                    print('  正解:', g, '\n  読み:', p)
                with open(os.path.join(a.out, 'log.jsonl'), 'a') as f:
                    f.write(json.dumps({'step': step, 'loss': loss_avg, 'ser': ser, 'exact': ex, 'time': time.time()}) + '\n')
                if ser < best:
                    best = ser
                    save(os.path.join(a.out, 'best.pt'))
                    print('  → いちばん良い結果として best.pt に保存しました')
            if step >= a.max_steps or time.time() >= t_end:
                break
    save(ck)
    print(f'止めました（{step}歩目）。同じコマンドで続きから再開できます。')


if __name__ == '__main__':
    main()
