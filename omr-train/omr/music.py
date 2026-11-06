"""ランダムなピアノ譜（大譜表1段分）を作り、MusicXML（描画用）と正解の記号列（学習用）を返す。

ここで作る曲は、すべてこのプログラムが乱数で作ったもの（著作権の問題が無い）。
楽譜らしさを出すため、拍ごとのリズムの型・音階に沿った旋律・和音・分散和音・2声などを混ぜる。

正解の記号列（トークン）の形（1段分）:
  clef:G2 clef:F4 key:-3 time:4/4  <小節1>  <小節2> ...
  小節 = [上の段の音] <s2> [下の段の音] |
  同じ段に2つの声部があるときは <v> で区切る。
  1つの音（和音）= [臨時記号] 音名オクターブ ... d長さ [.] [~]
     例: "b E4 G4 d8 ." = ♭ミとソの付点8分の和音、"r d4" = 4分休符、"~" = 次の音へタイ
  臨時記号は「楽譜に書いてある記号」（# b n x bb）。調号で付く音には書かない（楽譜と同じ）。
"""
import random

STEPS = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
STEP_SEMI = [0, 2, 4, 5, 7, 9, 11]
SHARP_ORDER = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
FLAT_ORDER = ['B', 'E', 'A', 'D', 'G', 'C', 'F']
ACC_TOKEN = {2: 'x', 1: '#', 0: 'n', -1: 'b', -2: 'bb'}
ACC_XML = {2: 'double-sharp', 1: 'sharp', 0: 'natural', -1: 'flat', -2: 'flat-flat'}
DUR_TYPE = {4: 'whole', 2: 'half', 1: 'quarter', 0.5: 'eighth', 0.25: '16th', 0.125: '32nd'}
DUR_TOKEN = {4: 'd1', 2: 'd2', 1: 'd4', 0.5: 'd8', 0.25: 'd16', 0.125: 'd32'}
DIV = 24  # MusicXML の divisions（4分音符 = 24）


def key_alters(fifths):
    a = {s: 0 for s in STEPS}
    if fifths > 0:
        for s in SHARP_ORDER[:fifths]:
            a[s] = 1
    elif fifths < 0:
        for s in FLAT_ORDER[:-fifths]:
            a[s] = -1
    return a


def split_dur(d):
    """4分音符単位の長さ → (基本の長さ, 付点の数)。書けない長さは None"""
    for base in (4, 2, 1, 0.5, 0.25, 0.125):
        if abs(d - base) < 1e-9:
            return base, 0
        if abs(d - base * 1.5) < 1e-9:
            return base, 1
        if abs(d - base * 1.75) < 1e-9:
            return base, 2
    return None


# 拍の中のリズムの型（4分音符単位）
BEAT_PATTERNS_Q = [  # 拍 = 4分音符
    ([1], 30), ([0.5, 0.5], 30), ([0.25] * 4, 10), ([0.75, 0.25], 6), ([0.25, 0.25, 0.5], 6), ([0.5, 0.25, 0.25], 6),
]
LONG_PATTERNS_Q = [  # 2拍以上
    ([2], 14), ([1.5, 0.5], 6), ([3], 4), ([4], 3),
]
BEAT_PATTERNS_DQ = [  # 拍 = 付点4分（6/8 など）
    ([1.5], 20), ([1, 0.5], 25), ([0.5, 0.5, 0.5], 30), ([0.25] * 6, 6), ([0.75, 0.25, 0.5], 8),
]


def wchoice(items):
    tot = sum(w for _, w in items)
    r = random.uniform(0, tot)
    for v, w in items:
        r -= w
        if r <= 0:
            return v
    return items[-1][0]


def rhythm(beats, beat_len, style):
    """1小節分の長さの並び（4分音符単位）と、拍の区切り（連桁を付ける単位）を返す"""
    out = []  # (長さ, 拍番号)
    b = 0
    while b < beats:
        left = beats - b
        if beat_len == 1:
            if style in ('chordal', 'bass') and random.random() < 0.55:
                cand = [(p, w) for p, w in LONG_PATTERNS_Q if sum(p) <= left]
                if cand:
                    p = wchoice(cand)
                    for d in p:
                        out.append((d, b))
                    b += int(sum(p))
                    continue
            if style == 'alberti':
                p = [0.25] * 4 if random.random() < 0.7 else [0.5, 0.5]
            elif style == 'arpeggio':
                p = [0.5, 0.5] if random.random() < 0.75 else [0.25] * 4
            else:
                if random.random() < 0.18:
                    cand = [(p, w) for p, w in LONG_PATTERNS_Q if sum(p) <= left]
                    if cand:
                        p = wchoice(cand)
                        for d in p:
                            out.append((d, b))
                        b += int(sum(p))
                        continue
                p = wchoice(BEAT_PATTERNS_Q)
            for d in p:
                out.append((d, b))
            b += 1
        else:  # 付点4分の拍
            if style in ('chordal', 'bass') and random.random() < 0.4:
                p = [1.5]
            elif style == 'arpeggio':
                p = [0.5, 0.5, 0.5]
            else:
                p = wchoice(BEAT_PATTERNS_DQ)
            for d in p:
                out.append((d, b))
            b += 1
    return out


class Writer:
    """MusicXML と記号列を同時に組み立てる"""

    def __init__(self, fifths, ts, clefs):
        self.fifths = fifths
        self.ts = ts
        self.clefs = clefs
        self.key = key_alters(fifths)

    def pitch_of(self, diat):
        """diat: C0 からの全音階の番号 → (step, octave)"""
        return STEPS[diat % 7], diat // 7


def gen_system(seed=None):
    """1段分（2〜5小節）の楽譜を作る。戻り値: (musicxml 文字列, トークンのリスト)"""
    if seed is not None:
        random.seed(seed)
    fifths = wchoice([(0, 16), (1, 10), (-1, 10), (2, 8), (-2, 8), (3, 6), (-3, 7), (4, 4), (-4, 5), (5, 2), (-5, 3), (6, 1), (-6, 2), (7, 0.3), (-7, 0.3)])
    ts = wchoice([((4, 4), 40), ((3, 4), 25), ((2, 4), 10), ((6, 8), 14), ((2, 2), 4), ((3, 8), 4), ((9, 8), 2), ((12, 8), 1)])
    compound = ts[1] == 8 and ts[0] % 3 == 0
    beat_len = 1.5 if compound else 1
    mlen = ts[0] * 4 / ts[1]
    nbeats = int(round(mlen / beat_len))
    clef1 = 'G2' if random.random() < 0.95 else 'F4'
    clef2 = 'F4' if random.random() < 0.88 else 'G2'
    nmeas = random.choice([2, 3, 3, 4, 4, 5])
    key = key_alters(fifths)
    rh_style = wchoice([('melody', 45), ('chordal', 25), ('arpeggio', 10), ('alberti', 5), ('melody2', 15)])
    lh_style = wchoice([('bass', 30), ('chordal', 20), ('arpeggio', 30), ('alberti', 10), ('melody', 10)])

    def rng(clef):
        # 全音階の番号の範囲（C4 = 28）
        return (27, 41) if clef == 'G2' else (13, 28)

    staves = [(clef1, rh_style), (clef2, lh_style)]
    state = [{'pos': random.randint(*rng(c))} for c, _ in staves]
    # 曲の途中の段（拍子記号が書かれていない段）も作る。そのときは time: を出さない
    show_time = random.random() < 0.55
    tokens = [f'clef:{clef1}', f'clef:{clef2}', f'key:{fifths}'] + ([f'time:{ts[0]}/{ts[1]}'] if show_time else [])
    first_no = 1 if show_time else random.randint(2, 120)
    xml_measures = []
    harmony_on = random.random() < 0.3
    dyn_on = random.random() < 0.35
    slur_on = random.random() < 0.25
    fing_on = random.random() < 0.12
    pending_tie = [None, None]  # 前の小節から続くタイ: (step, oct, alter)

    for mi in range(nmeas):
        mx = []
        mtok = []
        if mi == 0:
            mx.append(attributes_xml(fifths, ts, clef1, clef2, show_time))
        if harmony_on and random.random() < 0.7:
            root = random.choice(STEPS)
            kind = random.choice(['major', 'minor', 'dominant', 'major-seventh', 'minor-seventh'])
            mx.append(f'<harmony><root><root-step>{root}</root-step></root><kind>{kind}</kind></harmony>')
        if dyn_on and random.random() < 0.4:
            d = random.choice(['p', 'mp', 'mf', 'f', 'pp', 'ff'])
            mx.append(f'<direction placement="below"><direction-type><dynamics><{d}/></dynamics></direction-type><staff>1</staff></direction>')
        for si, (clef, style) in enumerate(staves):
            if si == 1:
                mx.append(f'<backup><duration>{int(mlen * DIV)}</duration></backup>')
                mtok.append('<s2>')
            carry = {}  # 小節の中で効いている臨時記号: (step, oct) -> alter
            two_voices = (style == 'melody2' and random.random() < 0.6) or random.random() < 0.06
            voices = [style.replace('melody2', 'melody')]
            if two_voices:
                voices.append('long')
            for vi, vstyle in enumerate(voices):
                if vi == 1:
                    mx.append(f'<backup><duration>{int(mlen * DIV)}</duration></backup>')
                    mtok.append('<v>')
                if vstyle == 'long':
                    durs = []
                    left = mlen
                    while left > 1e-9:
                        cands = [d for d in (4, 3, 2, 1.5, 1) if d <= left + 1e-9 and split_dur(d)]
                        d = random.choice(cands[:2]) if cands else left
                        durs.append((d, 0))
                        left -= d
                else:
                    durs = rhythm(nbeats, beat_len, vstyle)
                voice_no = si * 4 + vi + 1
                stem = None if len(voices) == 1 else ('up' if vi == 0 else 'down')
                evs = []
                for d, beat in durs:
                    is_rest = random.random() < (0.07 if vstyle != 'long' else 0.03)
                    if pending_tie[si] is not None and vi == 0:
                        is_rest = False
                    evs.append((d, beat, is_rest))
                # 連桁（拍ごと）
                beam_groups = group_beams(evs, beat_len)
                for ei, (d, beat, is_rest) in enumerate(evs):
                    base, dots = split_dur(d)
                    if is_rest:
                        full = abs(d - mlen) < 1e-9 and len(evs) == 1
                        mx.append(note_xml(None, base, dots, voice_no, si + 1, rest=True, full_measure=full))
                        # 1小節まるごとの休符は、拍子にかかわらず全休符の形で書かれるので、専用の記号にする
                        mtok += ['R'] if full else ['r', DUR_TOKEN[base]] + ['.'] * dots
                        continue
                    forced = vi == 0 and 'force' in state[si]  # 同じ小節の前の音からタイで続く
                    pitches = choose_pitches(state[si], rng(clef), vstyle if vi == 0 else 'long', key, si, vi) if vi == 0 else choose_pitches(state[si] if False else {'pos': state[si]['pos'] - 3}, rng(clef), 'long', key, si, vi)
                    tie_stop = forced
                    if pending_tie[si] is not None and vi == 0:
                        pitches = [pending_tie[si]]
                        pending_tie[si] = None
                        tie_stop = True
                    tie_start = vi == 0 and len(pitches) == 1 and random.random() < 0.05
                    # 臨時記号（表示する記号を決める）
                    chord_tok = []
                    for k, (step, octv, alter) in enumerate(sorted(pitches, key=lambda p: (p[1] * 7 + STEPS.index(p[0])))):
                        cur = carry.get((step, octv), key[step])
                        acc = None
                        if tie_stop:
                            carry[(step, octv)] = alter
                        elif alter != cur:
                            acc = alter
                            carry[(step, octv)] = alter
                        elif random.random() < 0.01 and alter == key[step] and (step, octv) in carry:
                            acc = alter  # 念のための臨時記号（たまに）
                        beam = beam_groups[ei] if k == 0 else ()  # 連桁は和音の最初の音だけに付ける
                        extras = []
                        if fing_on and random.random() < 0.3 and k == 0:
                            extras.append(f'<notations><technical><fingering>{random.randint(1, 5)}</fingering></technical></notations>')
                        if slur_on and k == 0 and ei == 0 and len(evs) > 2 and random.random() < 0.5:
                            extras.append('<notations><slur type="start" number="1"/></notations>')
                        if slur_on and k == 0 and ei == len(evs) - 1 and len(evs) > 2 and random.random() < 0.5:
                            extras.append('<notations><slur type="stop" number="1"/></notations>')
                        mx.append(note_xml((step, octv, alter), base, dots, voice_no, si + 1, chord=k > 0, acc=acc,
                                           beam=beam, stem=stem, tie_start=tie_start, tie_stop=tie_stop, extras=extras))
                        if acc is not None:
                            chord_tok.append(ACC_TOKEN[acc])
                        chord_tok.append(f'{step}{octv}')
                    mtok += chord_tok + [DUR_TOKEN[base]] + ['.'] * dots
                    if tie_start:
                        mtok.append('~')
                        p0 = pitches[0]
                        if ei < len(evs) - 1:
                            # 次の音を同じ高さにする（休符なら取り消し）
                            if evs[ei + 1][2]:
                                mtok.pop()
                                mx[-1] = mx[-1].replace('<tie type="start"/>', '').replace('<tied type="start"/>', '')
                            else:
                                state[si]['force'] = p0
                        else:
                            if mi < nmeas - 1:
                                pending_tie[si] = p0
                            else:
                                mtok.pop()
                                mx[-1] = mx[-1].replace('<tie type="start"/>', '').replace('<tied type="start"/>', '')
        mtok.append('|')
        xml_measures.append(f'<measure number="{first_no + mi}">' + ''.join(mx) + '</measure>')
        tokens += mtok
    xml = ('<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1"><part-list>'
           '<score-part id="P1"><part-name></part-name></score-part></part-list><part id="P1">'
           + ''.join(xml_measures) + '</part></score-partwise>')
    return xml, tokens


def attributes_xml(fifths, ts, c1, c2, show_time=True):
    def clef(n, c):
        return f'<clef number="{n}"><sign>{c[0]}</sign><line>{c[1]}</line></clef>'
    return (f'<attributes><divisions>{DIV}</divisions><key><fifths>{fifths}</fifths></key>'
            f'<time{"" if show_time else " print-object=\"no\""}><beats>{ts[0]}</beats><beat-type>{ts[1]}</beat-type></time><staves>2</staves>'
            + clef(1, c1) + clef(2, c2) + '</attributes>')


def group_beams(evs, beat_len):
    """8分音符以下が拍の中で2つ以上続く所に連桁を付ける。戻り値: 音ごとの [(番号, 'begin'|'continue'|'end'|'forward hook'|'backward hook')]"""
    res = [[] for _ in evs]
    i = 0
    while i < len(evs):
        d, beat, rest = evs[i]
        if d >= 1 or rest:
            i += 1
            continue
        j = i
        while j + 1 < len(evs) and evs[j + 1][1] == beat and evs[j + 1][0] < 1 and not evs[j + 1][2]:
            j += 1
        if j > i:
            for k in range(i, j + 1):
                res[k].append((1, 'begin' if k == i else 'end' if k == j else 'continue'))
            # 16分（2本目の桁）
            k = i
            while k <= j:
                if evs[k][0] <= 0.25 or (split_dur(evs[k][0]) and split_dur(evs[k][0])[0] <= 0.25):
                    m = k
                    while m + 1 <= j and (evs[m + 1][0] <= 0.25):
                        m += 1
                    if m > k:
                        for q in range(k, m + 1):
                            res[q].append((2, 'begin' if q == k else 'end' if q == m else 'continue'))
                    else:
                        res[k].append((2, 'backward hook' if k > i else 'forward hook'))
                    k = m + 1
                else:
                    k += 1
        i = j + 1
    return res


def choose_pitches(st, r, style, key, si, vi):
    """音の高さ（和音なら複数）を選ぶ。戻り値: [(step, octave, alter)]"""
    lo, hi = r
    if 'force' in st:
        p = st.pop('force')
        return [p]
    pos = st['pos']
    if style == 'long':
        pos = max(lo, min(hi, pos + random.choice([-4, -3, -2, 2, 3])))
    else:
        step = random.choice([-2, -1, -1, 1, 1, 2, -3, 3, 0, 4, -4]) if style != 'arpeggio' else random.choice([-5, -2, 2, 3, 5, -3])
        pos = pos + step
        if pos < lo or pos > hi:
            pos = pos - 2 * step
        pos = max(lo, min(hi, pos))
    st['pos'] = pos
    notes = [pos]
    nchord = 1
    if style == 'chordal':
        nchord = random.choice([2, 3, 3, 4])
    elif style == 'bass':
        nchord = random.choice([1, 1, 2])
    elif style == 'melody' and si == 0:
        nchord = 1 if random.random() < 0.75 else random.choice([2, 3])
    elif style == 'long':
        nchord = 1 if random.random() < 0.8 else 2
    for _ in range(nchord - 1):
        nxt = notes[-1] - random.choice([2, 2, 3, 4, 5]) if style != 'bass' else notes[-1] - 7
        if nxt >= lo - 3:
            notes.append(nxt)
    out = []
    for d in notes:
        step = STEPS[d % 7]
        octv = d // 7
        alter = key[step]
        if random.random() < 0.07:
            alter = max(-2, min(2, alter + random.choice([-1, 1])))
            if alter == 2 or alter == -2:
                alter = alter // 2 if random.random() < 0.8 else alter
        out.append((step, octv, alter))
    # 同じ音の重なりを除く
    seen, res = set(), []
    for p in out:
        if (p[0], p[1]) not in seen:
            seen.add((p[0], p[1]))
            res.append(p)
    return res


def note_xml(p, base, dots, voice, staff, chord=False, rest=False, acc=None, beam=(), stem=None,
             tie_start=False, tie_stop=False, extras=(), full_measure=False):
    dur = int(round(base * (2 - 0.5 ** dots) * DIV))
    s = ['<note>']
    if chord:
        s.append('<chord/>')
    if rest:
        s.append('<rest measure="yes"/>' if full_measure else '<rest/>')
    else:
        step, octv, alter = p
        s.append(f'<pitch><step>{step}</step>' + (f'<alter>{alter}</alter>' if alter else '') + f'<octave>{octv}</octave></pitch>')
    s.append(f'<duration>{dur}</duration>')
    if tie_stop:
        s.append('<tie type="stop"/>')
    if tie_start:
        s.append('<tie type="start"/>')
    s.append(f'<voice>{voice}</voice><type>{DUR_TYPE[base]}</type>' + '<dot/>' * dots)
    if acc is not None:
        s.append(f'<accidental>{ACC_XML[acc]}</accidental>')
    if stem:
        s.append(f'<stem>{stem}</stem>')
    s.append(f'<staff>{staff}</staff>')
    for n, kind in beam:
        s.append(f'<beam number="{n}">{kind}</beam>')
    nots = []
    if tie_start or tie_stop:
        nots.append(('<tied type="stop"/>' if tie_stop else '') + ('<tied type="start"/>' if tie_start else ''))
    s.append(('<notations>' + ''.join(nots) + '</notations>') if nots else '')
    s.extend(extras)
    s.append('</note>')
    return ''.join(s)


if __name__ == '__main__':
    xml, toks = gen_system(1)
    print(' '.join(toks))
