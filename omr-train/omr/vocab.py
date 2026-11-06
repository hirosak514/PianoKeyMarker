"""記号（トークン）の一覧。学習とアプリで同じ番号を使う（順番を変えないこと。足すときは最後に）"""

SPECIAL = ['<pad>', '<bos>', '<eos>', '<unk>']
STRUCT = ['|', '<s2>', '<v>', 'r', 'R', '.', '~']
DURS = ['d1', 'd2', 'd4', 'd8', 'd16', 'd32']
ACCS = ['#', 'b', 'n', 'x', 'bb']
PITCHES = [f'{s}{o}' for o in range(0, 9) for s in 'CDEFGAB']
CLEFS = ['clef:G2', 'clef:F4', 'clef:C3', 'clef:C4']
KEYS = [f'key:{k}' for k in range(-7, 8)]
TIMES = ['time:2/4', 'time:3/4', 'time:4/4', 'time:5/4', 'time:6/4', 'time:2/2', 'time:3/2',
         'time:3/8', 'time:6/8', 'time:9/8', 'time:12/8']

TOKENS = SPECIAL + STRUCT + DURS + ACCS + PITCHES + CLEFS + KEYS + TIMES
INDEX = {t: i for i, t in enumerate(TOKENS)}
PAD, BOS, EOS, UNK = 0, 1, 2, 3


def encode(tokens):
    return [BOS] + [INDEX.get(t, UNK) for t in tokens] + [EOS]


def decode(ids):
    out = []
    for i in ids:
        if i == EOS:
            break
        if i in (PAD, BOS):
            continue
        out.append(TOKENS[i] if 0 <= i < len(TOKENS) else '<unk>')
    return out
