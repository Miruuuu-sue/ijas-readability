# 論文収集ボット (Paper Collection Bot)

arXiv から毎日自動的に論文を収集し、**Claude AI で研究テーマとの関連度をスコアリング**して役立つ論文だけを保存します。

## 機能

- arXiv から毎日論文を自動収集 (GitHub Actions)
- **Claude API (claude-haiku) で各論文の関連度を 0-10 でスコアリング**
- 閾値以上の論文だけ JSON/CSV に保存
- Slack 通知対応 (スコア・理由つき)
- `--dry-run` で保存せずに結果を確認可能

## セットアップ

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. `config.yaml` の編集

```yaml
search:
  queries:
    - "politeness theory"         # ← 検索キーワード
    - "speech act Japanese"
  categories:
    - "cs.CL"                     # ← arXiv カテゴリ (空リストで全カテゴリ)
  max_results: 100
  days_back: 1

scoring:
  enabled: true
  model: "claude-haiku-4-5-20251001"
  threshold: 6                    # ← 6以上のスコアの論文を保存
  research_description: |
    私の研究テーマは... (自由記述)
```

### 3. API キーの設定

**ローカル実行:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**GitHub Actions:**
リポジトリの Settings → Secrets and variables → Actions に追加:
- `ANTHROPIC_API_KEY` (必須・スコアリング用)
- `SLACK_WEBHOOK_URL` (任意・Slack 通知用)

### 4. 実行

```bash
# 通常実行 (スコアリングあり)
python collect_papers.py

# 保存せず結果だけ表示
python collect_papers.py --dry-run

# スコアリングなし (API キー不要)
python collect_papers.py --no-scoring
```

## GitHub Actions による自動実行

毎日 **JST 09:00** に自動実行し、関連度の高い論文を `papers/` にコミットします。

Actions タブ → "Daily Paper Collection" → "Run workflow" で手動実行も可能です。

## 出力ファイル

```
papers/
├── papers_20260328.json
└── papers_20260328.csv
```

| フィールド | 説明 |
|---|---|
| `arxiv_id` | arXiv ID |
| `title` | タイトル |
| `authors` | 著者 |
| `abstract` | 要旨 |
| `relevance_score` | 関連度スコア (0-10) |
| `relevance_reason` | スコアの理由 (日本語) |
| `url` / `pdf_url` | arXiv / PDF リンク |
