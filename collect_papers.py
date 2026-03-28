#!/usr/bin/env python3
"""
論文収集ボット - arXiv から毎日論文を自動収集し、研究テーマへの関連度をスコアリングします
Paper Collection Bot - Collects papers from arXiv daily and scores relevance with LLM
"""

import json
import csv
import os
import sys
import logging
import argparse
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
import arxiv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_search_query(queries: list[str], categories: list[str]) -> str:
    """クエリとカテゴリから arXiv 検索クエリを構築する"""
    keyword_part = " OR ".join(f'"{q}"' for q in queries)
    if categories:
        cat_part = " OR ".join(f"cat:{c}" for c in categories)
        return f"({keyword_part}) AND ({cat_part})"
    return keyword_part


def fetch_papers(query: str, max_results: int, days_back: int) -> list[dict]:
    """arXiv から論文を取得する"""
    logger.info(f"検索クエリ: {query}")
    logger.info(f"最大取得件数: {max_results}, 過去 {days_back} 日分")

    client = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    papers = []

    for result in client.results(search):
        if days_back == 0:
            today = datetime.now(timezone.utc).date()
            if result.published.date() != today:
                continue
        elif result.published < cutoff:
            break

        papers.append({
            "arxiv_id": result.entry_id.split("/")[-1],
            "title": result.title,
            "authors": [a.name for a in result.authors],
            "abstract": result.summary.replace("\n", " "),
            "categories": result.categories,
            "published": result.published.isoformat(),
            "updated": result.updated.isoformat(),
            "url": result.entry_id,
            "pdf_url": result.pdf_url,
            "doi": result.doi or "",
            "journal_ref": result.journal_ref or "",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "relevance_score": None,
            "relevance_reason": "",
        })

    logger.info(f"{len(papers)} 件の論文を取得しました")
    return papers


def score_paper(client, model: str, research_description: str, paper: dict) -> tuple[float, str]:
    """Claude API を使って論文の関連度を 0-10 でスコアリングする"""
    prompt = f"""以下の研究テーマと論文を比較し、この論文が研究に役立つかどうかを評価してください。

## 研究テーマ
{research_description.strip()}

## 評価対象論文
タイトル: {paper['title']}
要旨: {paper['abstract'][:1000]}

## 指示
1. 関連度スコアを 0〜10 の整数で評価してください (10が最も関連度が高い)
2. 判定理由を1〜2文で簡潔に日本語で説明してください

以下のフォーマットで回答してください:
SCORE: <数字>
REASON: <理由>"""

    response = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    score = 0.0
    reason = ""

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()

    return score, reason


def score_papers(
    papers: list[dict],
    model: str,
    research_description: str,
    threshold: float,
) -> list[dict]:
    """全論文をスコアリングし、閾値以上のものだけ返す"""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic パッケージがインストールされていません: pip install anthropic")
        return papers

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY が設定されていないためスコアリングをスキップします")
        return papers

    client = anthropic.Anthropic(api_key=api_key)
    scored = []

    logger.info(f"{len(papers)} 件の論文をスコアリング中... (モデル: {model}, 閾値: {threshold})")

    for i, paper in enumerate(papers, 1):
        try:
            score, reason = score_paper(client, model, research_description, paper)
            paper["relevance_score"] = score
            paper["relevance_reason"] = reason
            status = "✓" if score >= threshold else "✗"
            logger.info(f"  [{i}/{len(papers)}] {status} スコア {score:.0f}/10 - {paper['title'][:60]}")
            if score >= threshold:
                scored.append(paper)
            # API レート制限対策
            if i < len(papers):
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"  スコアリング失敗 ({paper['title'][:40]}): {e}")
            paper["relevance_score"] = -1
            paper["relevance_reason"] = f"スコアリング失敗: {e}"
            scored.append(paper)  # 失敗した場合は念のため含める

    logger.info(f"スコアリング完了: {len(scored)}/{len(papers)} 件が閾値 {threshold} 以上")
    return scored


def save_json(papers: list[dict], output_dir: Path, date_str: str, prefix: str) -> Path:
    output_path = output_dir / f"{prefix}_{date_str}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 保存: {output_path} ({len(papers)} 件)")
    return output_path


def save_csv(papers: list[dict], output_dir: Path, date_str: str, prefix: str) -> Path:
    output_path = output_dir / f"{prefix}_{date_str}.csv"
    if not papers:
        output_path.touch()
        return output_path

    fieldnames = [
        "arxiv_id", "title", "authors", "categories",
        "published", "updated", "url", "pdf_url",
        "doi", "journal_ref", "relevance_score", "relevance_reason",
        "abstract", "collected_at",
    ]

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for paper in papers:
            row = paper.copy()
            row["authors"] = "; ".join(row["authors"])
            row["categories"] = "; ".join(row["categories"])
            writer.writerow(row)

    logger.info(f"CSV 保存: {output_path} ({len(papers)} 件)")
    return output_path


def notify_slack(papers: list[dict], webhook_url: str, max_notify: int) -> None:
    """Slack に新着・関連論文を通知する"""
    import urllib.request

    # スコアの高い順に並べ替え
    sorted_papers = sorted(
        papers,
        key=lambda p: p.get("relevance_score") or 0,
        reverse=True,
    )
    display = sorted_papers[:max_notify] if max_notify > 0 else sorted_papers
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📄 関連論文 {date_str} ({len(papers)} 件)",
            },
        }
    ]

    for paper in display:
        authors_str = ", ".join(paper["authors"][:3])
        if len(paper["authors"]) > 3:
            authors_str += f" ほか {len(paper['authors']) - 3} 名"

        score_str = ""
        if paper.get("relevance_score") is not None and paper["relevance_score"] >= 0:
            score_str = f"⭐ 関連度: {paper['relevance_score']:.0f}/10\n"

        reason_str = ""
        if paper.get("relevance_reason"):
            reason_str = f"_{paper['relevance_reason']}_\n"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*<{paper['url']}|{paper['title']}>*\n"
                    f"{authors_str}\n"
                    f"{score_str}"
                    f"{reason_str}"
                    f"_{paper['published'][:10]}_ | "
                    + ", ".join(paper["categories"][:3])
                ),
            },
        })

    if max_notify > 0 and len(papers) > max_notify:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"他 {len(papers) - max_notify} 件..."}],
        })

    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        logger.info(f"Slack 通知完了 (status={resp.status})")


def main() -> None:
    parser = argparse.ArgumentParser(description="arXiv 論文収集・関連度スコアリングボット")
    parser.add_argument("--config", default="config.yaml", help="設定ファイルパス")
    parser.add_argument("--dry-run", action="store_true", help="保存せずに結果を表示のみ")
    parser.add_argument("--no-scoring", action="store_true", help="LLM スコアリングをスキップ")
    args = parser.parse_args()

    config = load_config(args.config)
    search_cfg = config["search"]
    output_cfg = config["output"]
    scoring_cfg = config.get("scoring", {})
    notify_cfg = config.get("notify", {})

    query = build_search_query(
        search_cfg.get("queries", []),
        search_cfg.get("categories", []),
    )

    papers = fetch_papers(
        query=query,
        max_results=search_cfg.get("max_results", 100),
        days_back=search_cfg.get("days_back", 1),
    )

    if not papers:
        logger.info("新着論文はありませんでした")
        sys.exit(0)

    # LLM スコアリング
    scoring_enabled = scoring_cfg.get("enabled", False) and not args.no_scoring
    if scoring_enabled:
        papers = score_papers(
            papers=papers,
            model=scoring_cfg.get("model", "claude-haiku-4-5-20251001"),
            research_description=scoring_cfg.get("research_description", ""),
            threshold=scoring_cfg.get("threshold", 6),
        )

    if not papers:
        logger.info("関連度の高い論文はありませんでした")
        sys.exit(0)

    if args.dry_run:
        for p in sorted(papers, key=lambda x: x.get("relevance_score") or 0, reverse=True):
            score_str = f" [スコア: {p['relevance_score']:.0f}/10]" if p.get("relevance_score") is not None else ""
            print(f"[{p['published'][:10]}]{score_str} {p['title']}")
            if p.get("relevance_reason"):
                print(f"  理由: {p['relevance_reason']}")
            print(f"  著者: {', '.join(p['authors'][:3])}")
            print(f"  URL:  {p['url']}\n")
        return

    output_dir = Path(output_cfg.get("directory", "papers"))
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = output_cfg.get("filename_prefix", "papers")
    fmt = output_cfg.get("format", "both")

    if fmt in ("json", "both"):
        save_json(papers, output_dir, date_str, prefix)
    if fmt in ("csv", "both"):
        save_csv(papers, output_dir, date_str, prefix)

    # Slack 通知
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if notify_cfg.get("slack") and slack_webhook:
        notify_slack(papers, slack_webhook, notify_cfg.get("max_notify", 10))
    elif notify_cfg.get("slack") and not slack_webhook:
        logger.warning("Slack 通知が有効ですが SLACK_WEBHOOK_URL が設定されていません")

    logger.info("完了")


if __name__ == "__main__":
    main()
