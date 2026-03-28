#!/usr/bin/env python3
"""
論文収集ボット - arXiv から毎日論文を自動収集します
Paper Collection Bot - Automatically collects papers from arXiv daily
"""

import json
import csv
import os
import sys
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

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


def fetch_papers(
    query: str,
    max_results: int,
    days_back: int,
) -> list[dict]:
    """arXiv から論文を取得する"""
    logger.info(f"検索クエリ: {query}")
    logger.info(f"最大取得件数: {max_results}, 過去 {days_back} 日分")

    client = arxiv.Client(
        page_size=100,
        delay_seconds=3,
        num_retries=3,
    )

    search = arxiv.Search(
        query=query,
        max_results=max_results * 3,  # フィルタリング後に max_results 件確保するため多めに取得
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    papers = []

    for result in client.results(search):
        # days_back=0 の場合は今日のみ
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
        })

        if len(papers) >= max_results:
            break

    logger.info(f"{len(papers)} 件の論文を取得しました")
    return papers


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
        "doi", "journal_ref", "abstract", "collected_at",
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
    """Slack に新着論文を通知する"""
    import urllib.request

    display = papers[:max_notify] if max_notify > 0 else papers
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📄 新着論文 {date_str} ({len(papers)} 件)",
            },
        }
    ]

    for paper in display:
        authors_str = ", ".join(paper["authors"][:3])
        if len(paper["authors"]) > 3:
            authors_str += f" ほか {len(paper['authors']) - 3} 名"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*<{paper['url']}|{paper['title']}>*\n"
                    f"{authors_str}\n"
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
    parser = argparse.ArgumentParser(description="arXiv 論文収集ボット")
    parser.add_argument("--config", default="config.yaml", help="設定ファイルパス")
    parser.add_argument("--dry-run", action="store_true", help="保存せずに結果を表示のみ")
    args = parser.parse_args()

    config = load_config(args.config)

    search_cfg = config["search"]
    output_cfg = config["output"]
    notify_cfg = config.get("notify", {})

    query = build_search_query(
        search_cfg.get("queries", []),
        search_cfg.get("categories", []),
    )

    papers = fetch_papers(
        query=query,
        max_results=search_cfg.get("max_results", 50),
        days_back=search_cfg.get("days_back", 1),
    )

    if not papers:
        logger.info("新着論文はありませんでした")
        sys.exit(0)

    if args.dry_run:
        for p in papers:
            print(f"[{p['published'][:10]}] {p['title']}")
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
