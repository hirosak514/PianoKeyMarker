# Chopin the Ⅲ 楽譜読み取りAI（自作エンジン）の学習

大譜表1段の画像 → 記号列（トークン）を読む AI を、乱数で作った楽譜（著作権の問題が無い）で学習する。

- `omr/music.py` … ランダムなピアノ譜（MusicXML）と正解の記号列を作る
- `omr/render.py` … Verovio で画像にして、写真らしい汚れ・ゆがみを加える
- `omr/make_data.py` … 練習用データをたくさん作る
- `omr/model.py` … AI 本体（CNN + Transformer。ONNX に書き出せる自前の層）
- `omr/train.py` … 学習（途中経過を保存し、止まっても続きから再開）
- `omr/export.py` … アプリ用の ONNX（encoder / decoder）と vocab.json を書き出す
- `omr/predict.py` … 自分の画像で試す
- `notebooks/chopin_omr_train.ipynb` … Google Colab で上から順に実行するだけのノートブック

記号列の形は `omr/music.py` の先頭の説明を参照。Verovio（LGPL）は学習用の画像作りにだけ使い、アプリには入れない。
