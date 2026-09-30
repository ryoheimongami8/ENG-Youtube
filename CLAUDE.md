# ENG-Youtube

YouTube URL → 学習教材ZIP(audio.mp3 + lesson.json) → Android PWA(`viewer/`)。

## 入口
- 生成: `uv run --no-sync python -m engyt run <URL>` （stdoutは最終JSON1行のみ。再実行=再開）
- 初回のみ: `uv run --no-sync python -m engyt setup`（モデルDL、約25GB）
- テスト: `uv run --no-sync pytest`
- ZIPは `out/<videoId>.zip`。Driveへは手動同期。

## 方針（トークン節約）
- 全文・全ログ・lesson.json全体を読まない。結果JSONの `ok/zip/review_needed` だけ確認。
- 失敗時は返却JSONの `log` の**末尾のみ**読む（`work/<id>/logs/*.log`）。
- 各GPU工程(asr/fix/align)は子プロセス。キャッシュは `work/<id>/{asr,fix,align}/cNNNN.json`（key不一致で再計算）。
- 設定は `config.toml`。LLMやプロンプト変更で fix 以降が自動再実行される。

## 罠
- 必ず `--no-sync`（外すとtorchがCPU版に置換される恐れ）。Python 3.11固定。
- ComfyUI等がVRAMを掴んでいるとLLM(27B)が載らない。事前に終了。
- torchcodec不使用: 音声は `util.read_wav_slice` で `(np配列,16000)` を渡す。
- yt-dlp失敗時: `uv lock --upgrade-package yt-dlp` → `uv sync --locked` （JSランタイムはnode、config.toml）。
- LLMは時刻を生成しない。時刻は整列後の単語から算出。
- 文は1チャンク内で完結（チャンク境界で文が割れる場合あり）。
