from __future__ import annotations
import json, html, hashlib, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from urllib.parse import quote_plus
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE/"config.json").read_text(encoding="utf-8"))
DOCS = BASE/"docs"
DOCS.mkdir(exist_ok=True)
JST = timezone(timedelta(hours=9))

def clean(v):
    if not v: return ""
    return re.sub(r"\s+"," ",BeautifulSoup(v,"html.parser").get_text(" ",strip=True)).strip()

def parse_date(e):
    for k in ("published","updated","created"):
        v=getattr(e,k,None)
        if v:
            try:
                d=dateparser.parse(v)
                if not d.tzinfo: d=d.replace(tzinfo=timezone.utc)
                return d.astimezone(timezone.utc)
            except: pass
    return datetime.now(timezone.utc)

def google_url(q):
    loc=CFG["google_news_locale"]
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={loc['hl']}&gl={loc['gl']}&ceid={quote_plus(loc['ceid'])}"

def excluded(text):
    low=text.lower()
    if any(k.lower() in low for k in CFG["allow_even_if_excluded"]): return False
    return any(k.lower() in low for k in CFG["exclude_keywords"])

def classify(text,hint):
    low=text.lower()
    # local first
    for cat in ["浜松市・静岡県西部","オリジナルドラマ","映画・動画配信","J-HipHop・音楽","ゲーム","QOL・生活改善","ガジェット","IT・AI"]:
        if any(k.lower() in low for k in CFG["category_rules"].get(cat,[])):
            return cat
    return hint or "国内重要ニュース"

def source_name(entry,fallback):
    src=getattr(entry,"source",None)
    if src:
        if isinstance(src,dict) and src.get("title"): return clean(src["title"])
        t=getattr(src,"title",None)
        if t: return clean(t)
    return fallback

def normalize_title(title, source):
    # Google News often appends " - Publisher"
    suffix=f" - {source}"
    if source and title.endswith(suffix):
        return title[:-len(suffix)].strip()
    return title

def fetch_one(name,url,hint,kind):
    feed=feedparser.parse(url)
    out=[]
    cutoff=datetime.now(timezone.utc)-timedelta(hours=int(CFG["lookback_hours"]))
    for e in feed.entries:
        pub=parse_date(e)
        if pub<cutoff and kind!="search": continue
        title=clean(getattr(e,"title",""))
        summary=clean(getattr(e,"summary","") or getattr(e,"description",""))
        link=getattr(e,"link","")
        src=source_name(e,name)
        title=normalize_title(title,src)
        text=f"{title} {summary}"
        if excluded(text): continue
        cat=classify(text,hint)
        limit=int(CFG["summary_chars"])
        if len(summary)>limit: summary=summary[:limit].rstrip()+"…"
        guid=hashlib.sha256((link+"|"+title).encode()).hexdigest()
        out.append(dict(id=guid,title=title,link=link,summary=summary,source=src,category=cat,published=pub))
    return out

def collect():
    items=[]
    for s in CFG["direct_sources"]:
        items += fetch_one(s["name"],s["url"],s.get("category_hint",""),"direct")
    for s in CFG["search_sources"]:
        items += fetch_one(s["name"],google_url(s["query"]),s.get("category_hint",""),"search")
    # de-duplicate by normalized title, then URL
    dedup={}
    for i in sorted(items,key=lambda x:x["published"],reverse=True):
        key=re.sub(r"\W+","",i["title"].lower())[:160] or i["link"]
        if key not in dedup: dedup[key]=i
    return list(dedup.values())[:int(CFG["max_items"])]

def write_feed(items, filename="feed.xml", category=None):
    subset=[i for i in items if category is None or i["category"]==category]
    now=datetime.now(timezone.utc)
    body=[]
    for i in subset:
        desc=(f"<p><b>カテゴリー:</b> {html.escape(i['category'])}</p>"
              f"<p>{html.escape(i['summary'])}</p>"
              f"<p><b>ソース:</b> {html.escape(i['source'])}</p>")
        body.append(f"""<item>
<title>{html.escape(i['title'])}</title>
<link>{html.escape(i['link'])}</link>
<guid isPermaLink="false">{i['id']}</guid>
<pubDate>{format_datetime(i['published'])}</pubDate>
<category>{html.escape(i['category'])}</category>
<description><![CDATA[{desc}]]></description>
</item>""")
    xml=f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>{html.escape(CFG['feed_title'] if category is None else CFG['feed_title']+' - '+category)}</title>
<link>https://example.invalid/</link>
<description>個人用ニュースフィード</description>
<language>ja</language>
<lastBuildDate>{format_datetime(now)}</lastBuildDate>
{''.join(body)}
</channel></rss>"""
    (DOCS/filename).write_text(xml,encoding="utf-8")

def write_index(items):
    cards=[]
    for i in items[:50]:
        dt=i["published"].astimezone(JST).strftime("%m/%d %H:%M")
        cards.append(f"<article><div class=meta>{html.escape(i['category'])} ・ {dt} ・ {html.escape(i['source'])}</div>"
                     f"<h2><a href='{html.escape(i['link'])}' target=_blank rel=noopener>{html.escape(i['title'])}</a></h2>"
                     f"<p>{html.escape(i['summary'])}</p></article>")
    cats=sorted({i["category"] for i in items})
    links=" ".join(f"<a href='feed-{slug(c)}.xml'>{html.escape(c)}</a>" for c in cats)
    page=f"""<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Personal News RSS</title><style>
body{{font-family:system-ui,sans-serif;max-width:960px;margin:auto;padding:24px;line-height:1.6}}
article{{padding:16px 0;border-bottom:1px solid #ddd}} h2{{font-size:1.05rem;margin:.3rem 0}}
.meta{{font-size:.84rem;opacity:.68}} nav a{{margin-right:12px}} a{{color:inherit}}
</style></head><body><h1>Personal News RSS</h1><p><a href=feed.xml>すべてのニュースRSS</a></p><nav>{links}</nav>{''.join(cards)}</body></html>"""
    (DOCS/"index.html").write_text(page,encoding="utf-8")

def slug(s):
    table={"国内重要ニュース":"domestic","浜松市・静岡県西部":"hamamatsu","IT・AI":"it-ai","ガジェット":"gadget","ゲーム":"game",
           "J-HipHop・音楽":"music","QOL・生活改善":"qol","映画・動画配信":"streaming","オリジナルドラマ":"original-drama"}
    return table.get(s,hashlib.md5(s.encode()).hexdigest()[:8])

def main():
    items=collect()
    write_feed(items)
    for cat in CFG["category_rules"].keys():
        write_feed(items,f"feed-{slug(cat)}.xml",cat)
    write_feed(items,"feed-domestic.xml","国内重要ニュース")
    write_index(items)
    print("generated",len(items),"items")

if __name__=="__main__": main()
