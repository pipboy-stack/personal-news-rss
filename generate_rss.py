from __future__ import annotations
import json, html, hashlib, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE/"config.json").read_text(encoding="utf-8"))
DOCS = BASE/"docs"
DOCS.mkdir(exist_ok=True)
JST = timezone(timedelta(hours=9a))

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


def extract_image(entry):
    # RSS/Atom media fields
    for attr in ("media_thumbnail", "media_content"):
        values = getattr(entry, attr, None) or []
        if isinstance(values, dict):
            values = [values]
        for v in values:
            if isinstance(v, dict):
                url = v.get("url")
                if url and url.startswith(("http://", "https://")):
                    return url

    # enclosure
    for enc in getattr(entry, "enclosures", []) or []:
        if isinstance(enc, dict):
            url = enc.get("href") or enc.get("url")
            typ = (enc.get("type") or "").lower()
            if url and (typ.startswith("image/") or re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", url, re.I)):
                return url

    # image embedded in summary/description HTML
    raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if raw:
        soup = BeautifulSoup(raw, "html.parser")
        img = soup.find("img")
        if img:
            url = img.get("src") or img.get("data-src")
            if url and url.startswith(("http://", "https://")):
                return url
    return ""

CATEGORY_VISUALS = {
    "国内重要ニュース": ("🇯🇵", "国内"),
    "浜松市・静岡県西部": ("📍", "浜松・静岡西部"),
    "IT・AI": ("🤖", "IT・AI"),
    "ガジェット": ("📱", "ガジェット"),
    "ゲーム": ("🎮", "ゲーム"),
    "J-HipHop・音楽": ("🎧", "音楽"),
    "QOL・生活改善": ("🏠", "QOL"),
    "映画・動画配信": ("🎬", "映画・配信"),
    "オリジナルドラマ": ("📺", "ドラマ"),
}

def fetch_og_image(url):
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PersonalNewsRSS/1.0; +https://github.com/)"
        }
        req = Request(url, headers=headers)
        with urlopen(req, timeout=8) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            page = r.read(2_000_000).decode(charset, errors="replace")
        soup = BeautifulSoup(page, "html.parser")
        for attrs in (
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "twitter:image"},
        ):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return tag["content"].strip()
    except Exception:
        pass
    return ""


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
        image = extract_image(e)
        if not image:
            image = fetch_og_image(link)
        out.append(dict(id=guid,title=title,link=link,summary=summary,source=src,category=cat,published=pub,image=image))
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


def detect_game_badges(title, summary, category):
    if category != "ゲーム":
        return []
    text = f"{title} {summary}".lower()
    badges = []
    free_words = [
        "無料配布", "無料で配布", "期間限定無料", "free to keep",
        "free game", "無料入手", "無料でもら", "100% off", "無料配信"
    ]
    sale_words = [
        "セール", "sale", "割引", "値下げ", "特価", "discount",
        "サマーセール", "ウィンターセール", "オータムセール", "スプリングセール"
    ]
    weekend_words = ["free weekend", "フリーウィークエンド", "週末無料", "無料プレイ"]
    if any(w in text for w in free_words):
        badges.append(("🎁", "無料配布"))
    if any(w in text for w in weekend_words):
        badges.append(("🆓", "無料プレイ"))
    if any(w in text for w in sale_words):
        badges.append(("🔥", "セール"))
    return badges

def write_index(items):
    preferred = [
        "国内重要ニュース","浜松市・静岡県西部","IT・AI","ガジェット","ゲーム",
        "J-HipHop・音楽","QOL・生活改善","映画・動画配信","オリジナルドラマ"
    ]
    cats = preferred

    buttons = [
        "<button class='filter active' data-category='all'>すべて</button>",
        "<button class='filter bookmark-filter' data-category='bookmarks'>★ ブックマーク</button>"
    ]
    buttons += [
        f"<button class='filter' data-category='{html.escape(c, quote=True)}'>{html.escape(c)}</button>"
        for c in cats
    ]

    cards = []
    for i in items[:100]:
        dt = i["published"].astimezone(JST).strftime("%m/%d %H:%M")
        cat = i["category"]
        emoji, visual_label = CATEGORY_VISUALS.get(cat, ("📰", "ニュース"))
        image = i.get("image", "")
        if image:
            media = (
                f"<a class='media-link' href='{html.escape(i['link'], quote=True)}' target='_blank' rel='noopener' aria-label='{html.escape(i['title'], quote=True)}'>"
                f"<div class='media has-image'>"
                f"<img src='{html.escape(image, quote=True)}' alt='' loading='lazy' referrerpolicy='no-referrer' "
                f"onerror=\"this.closest('a').outerHTML='<div class=&quot;compact-fallback&quot;><span>{emoji}</span><b>{html.escape(visual_label)}</b></div>'\">"
                f"</div></a>"
            )
        else:
            media = f"<div class='compact-fallback'><span>{emoji}</span><b>{html.escape(visual_label)}</b></div>"

        summary = i["summary"] or "要約はありません。見出しを押すと元記事を開きます。"
        badge_html = "".join(
            f"<span class='alert-badge'>{icon} {html.escape(label)}</span>"
            for icon, label in detect_game_badges(i["title"], summary, cat)
        )
        cards.append(
            f"<article class='news-card' data-category='{html.escape(cat, quote=True)}' data-id='{html.escape(i['id'], quote=True)}'>"
            f"{media}"
            f"<div class='card-body'>"
            f"<div class='topline'><div class='category'>{html.escape(cat)}</div><div class='top-actions'><div class='badges'>{badge_html}</div><button class='bookmark-btn' type='button' aria-label='ブックマーク' title='ブックマーク'>☆</button></div></div>"
            f"<h2><a href='{html.escape(i['link'], quote=True)}' target='_blank' rel='noopener'>{html.escape(i['title'])}</a></h2>"
            f"<p class='summary'>{html.escape(summary)}</p>"
            f"<div class='meta'><span>{dt}</span><span>{html.escape(i['source'])}</span></div>"
            f"</div></article>"
        )

    page = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Personal News RSS</title>
<style>
:root {{
  --bg:#f3f4f6; --card:#fff; --text:#1f2937; --muted:#6b7280;
  --line:#e5e7eb; --chip:#fff; --chip-active:#111827; --chip-active-text:#fff;
}}
@media (prefers-color-scheme:dark) {{
  :root {{ --bg:#111318; --card:#1b1f27; --text:#edf0f5; --muted:#9da6b5;
           --line:#2c3340; --chip:#1b1f27; --chip-active:#edf0f5; --chip-active-text:#111318; }}
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}}
.wrap{{max-width:1500px;margin:auto;padding:20px}}
header{{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:12px}}
h1{{font-size:1.55rem;margin:0}} .rss{{font-size:.82rem;color:var(--muted)}} a{{color:inherit}}
.toolbar{{display:flex;gap:8px;overflow-x:auto;padding:10px 0 14px;position:sticky;top:0;background:var(--bg);z-index:20;scrollbar-width:thin}}
.filter{{flex:0 0 auto;border:1px solid var(--line);background:var(--chip);color:var(--text);border-radius:999px;padding:8px 13px;cursor:pointer;font-weight:650}}
.filter.active{{background:var(--chip-active);color:var(--chip-active-text);border-color:var(--chip-active)}}
.status{{font-size:.84rem;color:var(--muted);margin:0 0 12px}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:start}}
.news-card{{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.04);break-inside:avoid}}
.news-card[hidden]{{display:none}}
.media-link{{display:block;text-decoration:none}}\n.media.has-image{{aspect-ratio:16/9;background:#242936;overflow:hidden;cursor:pointer}}
.media img{{width:100%;height:100%;object-fit:cover;display:block;transition:transform .18s ease}}\n.media-link:hover img{{transform:scale(1.02)}}
.compact-fallback{{height:72px;display:flex;align-items:center;gap:10px;padding:0 14px;background:linear-gradient(145deg,#303744,#171b23);color:white}}
.compact-fallback span{{font-size:1.65rem}} .compact-fallback b{{font-size:.9rem;letter-spacing:.02em}}
.card-body{{padding:14px}}
.topline{{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:8px}}
.category{{display:inline-block;font-size:.76rem;font-weight:750;background:var(--bg);border-radius:999px;padding:4px 8px}}
.badges{{display:flex;gap:6px;flex-wrap:wrap}}
.top-actions{{display:flex;align-items:center;gap:8px;margin-left:auto}}
.alert-badge{{display:inline-block;font-size:.74rem;font-weight:800;border:1px solid var(--line);background:var(--bg);border-radius:999px;padding:4px 8px}}
.bookmark-btn{{width:34px;height:34px;border-radius:999px;border:1px solid var(--line);background:var(--chip);color:var(--text);font-size:1.3rem;line-height:1;cursor:pointer;display:grid;place-items:center}}
.bookmark-btn.active{{background:#f2c94c;color:#111;border-color:#f2c94c}}
.news-card.bookmarked{{outline:1px solid rgba(242,201,76,.55)}}
h2{{font-size:1.06rem;line-height:1.42;margin:0 0 8px}}
h2 a{{text-decoration:none}} h2 a:hover{{text-decoration:underline}}
.summary{{font-size:.91rem;color:var(--muted);margin:0 0 12px;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}}
.meta{{display:flex;justify-content:space-between;gap:8px;font-size:.76rem;color:var(--muted);border-top:1px solid var(--line);padding-top:9px}}
@media (max-width:1000px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media (max-width:620px){{.wrap{{padding:12px}} header{{display:block}} .rss{{margin-top:5px}} .grid{{grid-template-columns:1fr;gap:12px}} .toolbar{{margin:0 -12px;padding-left:12px;padding-right:12px}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div><h1>Personal News RSS</h1><div class="rss">画像付きニュースカード（記事画像優先） ・ <a href='external.html'>📡 外部RSS</a></div></div>
  <div class="rss">RSSリーダー登録用：<a href="feed.xml">feed.xml</a></div>
</header>
<nav class="toolbar">{''.join(buttons)}</nav>
<div id="status" class="status"></div>
<main id="grid" class="grid">{''.join(cards)}</main>
</div>
<script>
const buttons=[...document.querySelectorAll('.filter')];
const cards=[...document.querySelectorAll('.news-card')];
const status=document.getElementById('status');
const STORAGE_KEY='personal-news-rss-bookmarks-v1';
function loadBookmarks(){{try{{const v=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');return new Set(Array.isArray(v)?v:[]);}}catch(e){{return new Set();}}}}
let bookmarks=loadBookmarks();
function saveBookmarks(){{localStorage.setItem(STORAGE_KEY,JSON.stringify([...bookmarks]));}}
function syncBookmarkUI(){{cards.forEach(card=>{{const on=bookmarks.has(card.dataset.id);card.classList.toggle('bookmarked',on);const btn=card.querySelector('.bookmark-btn');if(btn){{btn.classList.toggle('active',on);btn.textContent=on?'★':'☆';btn.title=on?'ブックマークを解除':'ブックマーク';}}}});}}
function filterNews(category,setHash=true){{
  let shown=0;
  cards.forEach(card=>{{
    let visible;
    if(category==='all') visible=true;
    else if(category==='bookmarks') visible=bookmarks.has(card.dataset.id);
    else visible=card.dataset.category===category;
    card.hidden=!visible;
    if(visible) shown++;
  }});
  buttons.forEach(b=>b.classList.toggle('active',b.dataset.category===category));
  const label=category==='all'?'すべて':category==='bookmarks'?'ブックマーク':category;
  status.textContent=label+'：'+shown+'件'+(shown===0?'（現在、新着記事なし）':'');
  if(setHash) history.replaceState(null,'',category==='all'?location.pathname:'#'+encodeURIComponent(category));
}}
cards.forEach(card=>{{const btn=card.querySelector('.bookmark-btn');if(!btn)return;btn.addEventListener('click',e=>{{e.preventDefault();e.stopPropagation();const id=card.dataset.id;if(bookmarks.has(id))bookmarks.delete(id);else bookmarks.add(id);saveBookmarks();syncBookmarkUI();const active=buttons.find(b=>b.classList.contains('active'))?.dataset.category||'all';if(active==='bookmarks')filterNews('bookmarks',false);}});}});
buttons.forEach(b=>b.addEventListener('click',()=>filterNews(b.dataset.category)));
syncBookmarkUI();
let initial='all';
if(location.hash){{try{{const h=decodeURIComponent(location.hash.slice(1));if(buttons.some(b=>b.dataset.category===h))initial=h;}}catch(e){{}}}}
filterNews(initial,false);
</script>
</body>
</html>"""
    (DOCS/"index.html").write_text(page,encoding="utf-8")

def slug(s):
    table={"国内重要ニュース":"domestic","浜松市・静岡県西部":"hamamatsu","IT・AI":"it-ai","ガジェット":"gadget","ゲーム":"game",
           "J-HipHop・音楽":"music","QOL・生活改善":"qol","映画・動画配信":"streaming","オリジナルドラマ":"original-drama"}
    return table.get(s,hashlib.md5(s.encode()).hexdigest()[:8])

def load_external_feeds():
    p=Path("external_feeds.json")
    if not p.exists(): return []
    try:
        return [x for x in json.loads(p.read_text(encoding="utf-8")).get("feeds",[]) if x.get("enabled",True) and x.get("url")]
    except Exception as ex:
        print("external config error:",ex); return []

def entry_tags(e):
    vals=[]
    for t in getattr(e,"tags",[]) or []:
        v=(t.get("term") or t.get("label")) if isinstance(t,dict) else getattr(t,"term",None)
        if v:
            v=re.sub(r"\s+"," ",str(v)).strip()
            if v and v not in vals: vals.append(v)
    return vals[:8]

def fetch_external_feed(cfg):
    name=cfg.get("name") or cfg["url"]; genre=cfg.get("genre") or "外部RSS"
    d=feedparser.parse(cfg["url"]); out=[]
    for e in d.entries[:40]:
        title=re.sub(r"\s+"," ",getattr(e,"title","")).strip(); link=getattr(e,"link","").strip()
        if not title or not link: continue
        summary=clean_summary(getattr(e,"summary","") or getattr(e,"description","") or "")
        pub=parse_date(e); guid=hashlib.sha256(("external|"+link+"|"+title).encode()).hexdigest()
        image=extract_image(e) or fetch_og_image(link)
        out.append(dict(id=guid,title=title,link=link,summary=summary,source=name,category=genre,published=pub,image=image,tags=entry_tags(e)))
    return out

def write_external_index(items):
    sites=sorted({i["source"] for i in items}); tags=sorted({t for i in items for t in i.get("tags",[])},key=str.casefold)
    cards=[]
    for i in items[:300]:
        dt=i["published"].astimezone(JST).strftime("%m/%d %H:%M")
        if i.get("image"):
            media=f"<a class='media' href='{html.escape(i['link'],quote=True)}' target='_blank'><img src='{html.escape(i['image'],quote=True)}' loading='lazy' alt=''></a>"
        else: media="<div class='fallback'>📡</div>"
        th="".join(f"<button class='tag' data-tag='{html.escape(t,quote=True)}'>#{html.escape(t)}</button>" for t in i.get("tags",[]))
        cards.append(f"<article class='card' data-site='{html.escape(i['source'],quote=True)}' data-tags='{html.escape('|'.join(i.get('tags',[])),quote=True)}'>{media}<div class='body'><small>{html.escape(i['source'])} ・ {dt}</small><h2><a href='{html.escape(i['link'],quote=True)}' target='_blank'>{html.escape(i['title'])}</a></h2><p>{html.escape(i['summary'])}</p><div>{th}</div></div></article>")
    opts="".join(f"<option value='{html.escape(s,quote=True)}'>{html.escape(s)}</option>" for s in sites)
    tbs="".join(f"<button class='tf' data-tag='{html.escape(t,quote=True)}'>#{html.escape(t)}</button>" for t in tags[:60])
    page=f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>外部RSS</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#111318;color:#edf0f5;font-family:system-ui,sans-serif}}.w{{max-width:1500px;margin:auto;padding:20px}}a{{color:inherit}}nav a,button,select{{background:#1b1f27;color:#edf0f5;border:1px solid #303744;border-radius:999px;padding:7px 11px;margin:3px;text-decoration:none}}.tools,.tagbar{{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}.card{{background:#1b1f27;border:1px solid #303744;border-radius:15px;overflow:hidden}}.card[hidden]{{display:none}}.media{{display:block;aspect-ratio:16/9;overflow:hidden}}.media img{{width:100%;height:100%;object-fit:cover}}.fallback{{height:72px;display:grid;place-items:center;font-size:2rem;background:#252b36}}.body{{padding:14px}}small,p{{color:#9da6b5}}h2{{font-size:1.05rem}}p{{font-size:.9rem}}.active{{background:#edf0f5;color:#111318}}@media(max-width:1000px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:620px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="w"><h1>📡 外部RSS</h1><nav><a href="index.html">📰 マイニュース</a><a href="external.html">📡 外部RSS</a></nav><div class="tools">サイト <select id="site"><option value="">すべて</option>{opts}</select><button id="clear">解除</button><span id="count"></span></div><div class="tagbar">{tbs}</div><main class="grid">{''.join(cards)}</main></div><script>
const cs=[...document.querySelectorAll('.card')],s=document.getElementById('site'),ct=document.getElementById('count');let tag='';function ap(){{let n=0;cs.forEach(c=>{{let ok=(!s.value||c.dataset.site===s.value)&&(!tag||(c.dataset.tags||'').split('|').includes(tag));c.hidden=!ok;if(ok)n++}});ct.textContent=n+'件';document.querySelectorAll('.tf').forEach(b=>b.classList.toggle('active',b.dataset.tag===tag))}}s.onchange=ap;document.getElementById('clear').onclick=()=>{{s.value='';tag='';ap()}};document.querySelectorAll('.tf,.tag').forEach(b=>b.onclick=()=>{{tag=b.dataset.tag;ap();scrollTo(0,0)}});ap();
</script></body></html>"""
    (DOCS/"external.html").write_text(page,encoding="utf-8")

def main():
    items=collect()
    write_feed(items)
    for cat in CFG["category_rules"].keys():
        write_feed(items,f"feed-{slug(cat)}.xml",cat)
    write_feed(items,"feed-domestic.xml","国内重要ニュース")
    write_index(items)
    external=[]
    for cfg in load_external_feeds():
        try: external.extend(fetch_external_feed(cfg))
        except Exception as ex: print("external feed error:",ex)
    external.sort(key=lambda x:x["published"],reverse=True)
    write_external_index(external)
    print("generated",len(items),"items")

if __name__=="__main__": main()
