import os, re, asyncio, subprocess, datetime, email.utils, shutil
import feedparser, edge_tts
from openai import OpenAI
from xml.sax.saxutils import escape

FEEDS = {
    "World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "India": "https://www.thehindu.com/news/national/feeder/default.rss",
    "Politics": "https://feeds.bbci.co.uk/news/politics/rss.xml",
    "Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "Markets": "https://www.livemint.com/rss/markets",
    "Technology": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "Space": "https://www.space.com/feeds/all",
    "Health": "https://feeds.bbci.co.uk/news/health/rss.xml",
    "Climate": "https://www.theguardian.com/environment/climate-crisis/rss",
    "Sports": "https://feeds.bbci.co.uk/sport/rss.xml",
    "Cricket": "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
    "Entertainment": "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    "Education": "https://www.thehindu.com/education/feeder/default.rss",
    "Startups": "https://techcrunch.com/category/startups/feed/",
}
STORIES_PER_CAT = 2
WORDS_PER_STORY = 130
VOICE = "en-IN-NeerjaNeural"
BASE = os.environ["SITE_URL"].rstrip("/")

openrouter = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
groq = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])

def chat(prompt):
    for client, model in [(openrouter, "meta-llama/llama-3.3-70b-instruct"),
                          (groq, "llama-3.3-70b-versatile")]:
        try:
            r = client.chat.completions.create(
                model=model, temperature=0.4,
                messages=[{"role": "user", "content": prompt}])
            return r.choices[0].message.content.strip()
        except Exception as e:
            print("LLM failed, trying fallback:", e)
    raise RuntimeError("All LLM providers failed")

def fetch(url):
    entries = feedparser.parse(url).entries[:STORIES_PER_CAT + 3]
    return "\n".join(
        f"- {e.title}: {re.sub('<[^>]+>', '', e.get('summary', ''))[:600]}" for e in entries)

def script_for(cat, raw):
    prompt = f"""You are a radio news anchor. Category: {cat}.
From the items below, pick the {STORIES_PER_CAT} most important distinct stories.
Write each as a spoken segment of about {WORDS_PER_STORY} words: a hook, key facts, why it matters.
Use only facts present in the items. Plain spoken English, no markdown, no bullet points.
Separate segments with a line containing only ###.

{raw}"""
    return [s.strip() for s in chat(prompt).split("###") if s.strip()]

async def tts(text, path):
    await edge_tts.Communicate(text, VOICE).save(path)

def build_site(mp3, title):
    os.makedirs("site", exist_ok=True)
    shutil.copy(mp3, "site/latest.mp3")
    size = os.path.getsize(mp3)
    secs = int(float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", mp3]).strip()))
    stamp = datetime.date.today().isoformat()
    pub = email.utils.format_datetime(datetime.datetime.now(datetime.timezone.utc))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>My Daily Briefing</title>
  <link>{BASE}</link>
  <language>en</language>
  <description>Personal daily news audio briefing</description>
  <itunes:author>Me</itunes:author>
  <itunes:explicit>false</itunes:explicit>
  <itunes:block>Yes</itunes:block>
  <item>
    <title>{escape(title)}</title>
    <guid isPermaLink="false">news-{stamp}</guid>
    <pubDate>{pub}</pubDate>
    <enclosure url="{BASE}/latest.mp3?d={stamp}" length="{size}" type="audio/mpeg"/>
    <itunes:duration>{secs}</itunes:duration>
  </item>
</channel>
</rss>"""
    open("site/feed.xml", "w").write(xml)
    print(f"Episode length: {secs/60:.1f} min")

async def main():
    today = datetime.date.today().strftime("%A, %d %B %Y")
    parts = [f"Good morning. This is your daily briefing for {today}. Let's begin."]
    for cat, url in FEEDS.items():
        try:
            segs = script_for(cat, fetch(url))
        except Exception as e:
            print("skip", cat, e)
            continue
        parts.append(f"{cat}.")
        parts.extend(segs)
    parts.append("That's all for today. Have a great day.")

    files = []
    for i, t in enumerate(parts):
        p = f"part_{i:03d}.mp3"
        await tts(t, p)
        files.append(p)

    with open("list.txt", "w") as f:
        f.writelines(f"file '{p}'\n" for p in files)
    out = "briefing.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
                    "-ac", "1", "-b:a", "64k", out], check=True)
    build_site(out, f"News {today}")

asyncio.run(main())