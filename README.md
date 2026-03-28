# 論文収集ボット (Paper Collection Bot)

arXiv から毎日自動的に論文を収集し、JSON/CSV 形式で保存します。

## セットアップ

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. `config.yaml` の編集

```yaml
search:
  queries:
    - "large language models"   # 検索キーワードを追加・変更
  categories:
    - "cs.LG"                   # arXiv カテゴリで絞り込み
  max_results: 50               # 最大取得件数
  days_back: 1                  # 過去何日分を取得するか

output:
  directory: "papers"           # 保存先ディレクトリ
  format: "both"                # "json", "csv", "both"
```

arXiv のカテゴリ一覧は [こちら](https://arxiv.org/category_taxonomy) を参照してください。

### 3. ローカルで実行

```bash
# 通常実行
python collect_papers.py

# 結果を表示するだけ (保存しない)
python collect_papers.py --dry-run

# 別の設定ファイルを使用
python collect_papers.py --config my_config.yaml
```

## GitHub Actions による自動実行

毎日 **JST 09:00** (UTC 00:00) に自動で論文を収集し、`papers/` ディレクトリにコミットします。

### 手動実行

GitHub の Actions タブ → "Daily Paper Collection" → "Run workflow" から手動実行できます。
`days_back` に日数を入力すると過去分を一括取得できます。

### Slack 通知の設定

1. Slack の [Incoming Webhook](https://api.slack.com/messaging/webhooks) を作成
2. リポジトリの Settings → Secrets → `SLACK_WEBHOOK_URL` に Webhook URL を登録
3. `config.yaml` の `notify.slack` を `true` に変更

## 出力ファイル

```
papers/
├── papers_20260328.json   # JSON 形式
└── papers_20260328.csv    # CSV 形式
```

各論文には以下の情報が含まれます:

| フィールド | 説明 |
|---|---|
| `arxiv_id` | arXiv ID |
| `title` | タイトル |
| `authors` | 著者リスト |
| `abstract` | 要旨 |
| `categories` | arXiv カテゴリ |
| `published` | 投稿日時 |
| `url` | arXiv URL |
| `pdf_url` | PDF URL |
