# AutoCut for CapCut

動画編集の「無音カット」「間延び・言い直し・フィラー削除」を自動化し、結果を CapCut に渡すためのローカルツールです。

```
動画 ──▶ ① ffmpeg で無音検出 ─────────────────────────────────┐
     └▶ ② Whisper で文字起こし ─▶ ③ Claude が間延び・言い直しを判定 ─┤
                                                              ▼
                ブラウザ UI で確認・ON/OFF・手動カット（カット箇所を飛ばしてプレビュー）
                                                              ▼
        A. カット済み MP4 + 字幕 SRT  /  B. CapCut ドラフト  /  C. JSON カットリスト
```

## 構成

| パス | 内容 |
|---|---|
| `backend/app/main.py` | FastAPI サーバー（API + フロントエンド配信） |
| `backend/app/media.py` | ffprobe / ffmpeg `silencedetect` による無音検出・波形生成 |
| `backend/app/transcribe.py` | faster-whisper による単語タイムスタンプ付き文字起こし |
| `backend/app/ai_editor.py` | Claude API（構造化出力）でカット候補を生成 |
| `backend/app/timeline.py` | カット候補 → 残す区間、カット後の時刻変換 |
| `backend/app/exporters/` | MP4 書き出し / SRT 字幕 / CapCut ドラフト生成 |
| `frontend/` | 素の HTML/CSS/JS の編集 UI（ビルド不要） |

## セットアップ

前提: Python 3.10+、[ffmpeg](https://ffmpeg.org/)（`ffmpeg` / `ffprobe` に PATH が通っていること）

```bash
cd capcut-autocut
python -m venv .venv
# Windows: .venv\Scripts\activate   /   macOS・Linux: source .venv/bin/activate
pip install -r backend/requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...        # AI 機能を使う場合（Windows: set ANTHROPIC_API_KEY=...）
cd backend
uvicorn app.main:app --port 8000
```

ブラウザで http://localhost:8000 を開きます。設定項目は `.env.example` を参照してください。

- **無音カットだけ**なら `ANTHROPIC_API_KEY` と faster-whisper は不要です（UI で AI のチェックを外す）。
- `CAPCUT_DRAFT_DIR` を CapCut のドラフト保存先に設定すると、「CapCut に直接追加」ボタンでプロジェクトを直接作成できます。

## 使い方

1. 動画をドロップ
2. 無音の閾値・長さ・前後の余白を調整して「自動カットを実行」
   - AI を ON にすると、文字起こし → Claude が「フィラー」「言い直し（最後のテイクを残す）」「噛み」「重複」「長い間」「撮影中の独り言」を提案
   - 確信度が閾値未満の AI 提案は OFF の状態で並ぶので、プレビューして判断
3. タイムライン / 一覧で確認
   - 「カット箇所を飛ばして再生」で仕上がりをその場で確認
   - 一覧の行をクリックすると、カットの 1.5 秒前から再生
   - `I` / `O` で範囲指定 → `X` で手動カット、`Space` 再生/停止、`←` `→` で 1 秒移動（Shift で 5 秒）
4. 書き出し
   - **A. カット済み MP4 + SRT**（確実）: CapCut に読み込み、字幕は「テキスト → ローカル字幕」から SRT をインポート
   - **B. CapCut ドラフト**: 元動画を参照したまま、残す区間をクリップとして並べたプロジェクト。CapCut 上で切れ目を微調整できます。ZIP を展開し、以下にフォルダごとコピーして CapCut を再起動
     - Windows: `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft\`
     - macOS: `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`
     - 「CapCut を使う PC 上の元動画パス」に元動画の場所を入力してください（サーバーと CapCut が同じ PC なら空欄で可）

> **CapCut ドラフトについての注意**: ドラフト形式は CapCut の非公開の内部形式で、本ツールの出力は互換性を推定して作ったものです（実機の CapCut での読み込みは未確認）。新しいバージョンの CapCut ではドラフトファイルが暗号化されており、外部で生成したドラフトを読み込めないことがあります。その場合は A の書き出しを使ってください。

## API

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/api/health` | Whisper / Claude キー / CapCut 直接追加の可否 |
| POST | `/api/projects` | 動画アップロード（multipart `file`） |
| GET | `/api/projects/{id}` | 状態・カット候補・残す区間 |
| POST | `/api/projects/{id}/analyze` | 解析開始（無音・AI 設定を JSON で指定、非同期） |
| PUT | `/api/projects/{id}/cuts` | カット候補の更新（ON/OFF・手動追加・削除） |
| GET | `/api/projects/{id}/export/{mp4\|srt\|capcut\|json}` | 書き出し |
| POST | `/api/projects/{id}/export/capcut-install` | `CAPCUT_DRAFT_DIR` にドラフトを直接作成 |

## AI 部分の仕組み

`ai_editor.py` は単語ごとに `[番号]単語(開始秒-終了秒)` 形式の文字起こしを Claude に渡し、JSON Schema で縛った構造化出力でカット範囲を単語番号で受け取ります。番号から秒に戻すので、切れ目は必ず Whisper の単語境界に揃います。

- モデル: `CLAUDE_MODEL`（既定 `claude-opus-5-5`）、推論の深さ: `CLAUDE_EFFORT`（既定 `medium`）
- 安全性分類器でリクエストが断られた場合は、サーバー側フォールバック（`fallbacks: "default"`）で別モデルが自動で処理を引き継ぎます
- UI の「AI への追加指示」で「笑い声は残す」「商品名の部分は削らない」などの方針を渡せます

## テスト

```bash
pip install -r backend/requirements-dev.txt
cd backend && pytest
```

ffmpeg で生成した合成動画を使い、無音検出 → カット編集 → MP4 / ドラフト書き出しまで通しで確認します（Claude API はモック）。
