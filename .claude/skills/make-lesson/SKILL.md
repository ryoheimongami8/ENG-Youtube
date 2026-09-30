---
name: make-lesson
description: YouTube URLから英語学習教材ZIP（MP3+英日対訳+時間情報）を生成する。「教材を作って」「このYouTubeを教材化」などURL付き依頼で使う。
---

1. 作業ディレクトリ `D:\50_ENG-Youtube` で実行（ComfyUI等がVRAMを使っていないか先に確認）:
   `uv run --no-sync python -m engyt run "<URL>"`
2. 出力の最終JSON1行だけを読む。全文・ログ・lesson.jsonは読まない。
3. `ok:true` → `zip`のパス、`sentences`、`review_needed`（要確認文数）だけ報告。
4. `ok:false` → `log` の末尾30行程度だけ読んで原因を特定。ネットワーク系は同じコマンドで再開できる（キャッシュ済み）。
   yt-dlp系は CLAUDE.md の更新手順を実行。
