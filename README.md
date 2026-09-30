# ENG-Youtube

YouTube URL から英語学習教材を作り、Android の PWA で学習する。

```
Windows: URL → yt-dlp+FFmpeg → Qwen3-ASR-1.7B → Qwen3.8-27B(llama.cpp: 誤認識修正+和訳)
              → Qwen3-ForcedAligner-0.6B → ZIP(audio.mp3 + lesson.json)
手動: ZIP を Google Drive へ同期
Android: PWA(GitHub Pages) で ZIP を取り込み → IndexedDB → オフライン学習
```

## 生成
```bash
uv sync --locked                                        # 初回のみ
uv run --no-sync python -m engyt setup                  # モデルDL(約25GB)、初回のみ
uv run --no-sync python -m engyt run "https://youtu.be/xxxx"
```
- 出力は最終JSON1行のみ（`ok`, `zip`, `sentences`, `review_needed`）。ログは `work/<id>/logs/`。
- 途中で落ちても同じコマンドで再開（チャンク単位キャッシュ、設定/モデル/プロンプト変更で自動再計算）。
- 実行前に ComfyUI 等でVRAMを使っていないこと（27B LLMが載らない）。
- yt-dlp更新: `uv lock --upgrade-package yt-dlp && uv sync --locked`

## lesson.json
`{version,id,title,source_url,duration,sentences:[{i,chunk,start,end,en,ja,words:[{w,start,end}],flag?}]}`
`flag` = 未整列 / 単語数不一致 / 異常な語長 / 時間逆転 / 大幅な英文変更 / 訳欠落。該当文も削除せず残す。

## ビューア (`viewer/`)
GitHub Pages（`.github/workflows/pages.yml`、Settings → Pages → Source: GitHub Actions）で `/ENG-Youtube/` 配下に配信。
Android Chrome で開き「ホーム画面に追加」→ Drive からDLした ZIP を「教材ZIPを取り込む」で選択。
機能: 再生位置の文/単語ハイライト、英日対訳、文タップ再生、速度変更、文リピート(2/3/5回/無限)、学習位置の保存。
共有メニューからの取り込み(share_target)は未対応。

ローカル確認: `python -m http.server 8080 -d viewer`
