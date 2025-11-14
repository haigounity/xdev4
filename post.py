import os, json, random, re, time
from datetime import datetime, timezone, timedelta
import tweepy
import yaml

API_KEY        = os.getenv("X_API_KEY")
API_SECRET     = os.getenv("X_API_SECRET")
ACCESS_TOKEN   = os.getenv("X_ACCESS_TOKEN")
ACCESS_SECRET  = os.getenv("X_ACCESS_SECRET")

if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
    raise RuntimeError("X API の認証情報が不足しています。Secrets を確認してください。")

# ---- 読み込み ----
with open("persona.yaml", "r", encoding="utf-8") as f:
    persona = yaml.safe_load(f)

MAX_CHARS = persona.get("guardrails", {}).get("max_chars", 220)
BANNED = set(persona.get("guardrails", {}).get("banned_words", []))

# ---- 簡易テンプレ群（短文・観察メモ中心） ----
# 句読点や具体性で“AIっぽさ”を抑え、短く断定しすぎない
TEMPLATES = [
    "{paper}で{pen}。乾き{drying}。左手に移らない。きょうはこれでいく。",
    "{grid}は図が収まる。文字は{rule}のほうが速い。きょうは速度優先。",
    "インク{ink}は{paper}だと薄く見える。裏抜けは{bleed}。",
    "筆圧を{pressure}。同じページで裏抜けが止まった。",
    "{pen}の{tip}は細い線が続く。長文は{alt_pen}に替えると楽だった。",
    "{paper}の紙目は{grain}。ペン先の引っかかりが少ない。",
    "索引を最初に{index_pages}枚。迷わない。続く。",
    "クリップは{clip}。厚みが出ない。ノートが平らのまま。",
    "下敷き{underlay}で筆跡が揺れない。小さい字の比率が安定した。",
    "{ruler}で罫線を延長。図の修正が早くなる。今日はここまで。",
    "ゲル{tip}は{drying}。紙は{paper}。速度は十分。",
    "{label}を先に作る。探す時間が減った。"
]

PAPERS = ["上質紙", "淡クリーム", "再生紙", "コートっぽい紙", "方眼ノート", "無地ノート"]
PEN_TYPES = ["ゲルインク", "油性ボール", "染料インク", "顔料インク", "万年筆"]
TIPS = ["0.38", "0.5", "0.7", "F", "M"]
DRYINGS = ["速い", "普通", "遅い"]
BLEEDS = ["出ない", "少し出る", "強い"]
PRESSURES = ["少し抜く", "いつもより軽くする", "意識して一定にする"]
ALT_PENS = ["油性0.5", "ゲル0.5", "万年筆F", "ローラーボール0.5"]
GRAINS = ["細かい", "やや粗い", "均一"]
GRIDS = ["方眼5mm", "方眼3.7mm", "10mm方眼"]
RULES = ["3mm罫", "6mm罫", "A罫"]
INDEX_PAGES = ["2", "3", "4"]
CLIPS = ["フラット", "ワイヤー", "ゼム"]
UNDERLAYS = ["薄手", "厚手", "やわらかめ"]
RULERS = ["アルミ定規", "透明定規", "ステンレス定規"]
LABELS = ["ラベル", "見出し", "番号"]

def seeded_rand_for_today():
    # JSTで日付シードを作る（同じ日なら同じ乱数系列）
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y%m%d")
    seed_base = f"{today}-{os.getenv('GITHUB_REPOSITORY','local')}"
    random.seed(hash(seed_base) & 0xffffffff)

def pick():
    return {
        "paper": random.choice(PAPERS),
        "pen": random.choice(PEN_TYPES),
        "tip": random.choice(TIPS),
        "drying": random.choice(DRYINGS),
        "bleed": random.choice(BLEEDS),
        "pressure": random.choice(PRESSURES),
        "alt_pen": random.choice(ALT_PENS),
        "grain": random.choice(GRAINS),
        "grid": random.choice(GRIDS),
        "rule": random.choice(RULES),
        "index_pages": random.choice(INDEX_PAGES),
        "clip": random.choice(CLIPS),
        "underlay": random.choice(UNDERLAYS),
        "ruler": random.choice(RULERS),
        "label": random.choice(LABELS)
    }

def sanitize(text: str) -> str:
    # 絵文字・ハッシュタグ禁止
    text = re.sub(r"[#]+[A-Za-z0-9_ぁ-んァ-ヶ一-龠ー]+", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF]", "", text)
    # banned word除去（単純置換）
    for w in BANNED:
        text = text.replace(w, "")
    text = text.strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return text

MEMO_PATH = ".last_posts.json"
def load_history():
    if os.path.exists(MEMO_PATH):
        try:
            return json.load(open(MEMO_PATH, "r", encoding="utf-8"))
        except Exception:
            return []
    return []

def too_similar(cur, prevs, threshold=0.9):
    # 簡易Jaccard
    def shingles(s, n=4):
        s = re.sub(r"\s+", "", s)
        return {s[i:i+n] for i in range(max(len(s)-n+1,1))}
    a = shingles(cur)
    for p in prevs[-30:]:
        b = shingles(p)
        j = len(a & b) / max(len(a | b), 1)
        if j >= threshold:
            return True
    return False

def generate_text():
    seeded_rand_for_today()
    tries = 0
    history = load_history()
    while tries < 8:
        tmpl = random.choice(TEMPLATES)
        vars = pick()
        text = tmpl.format(**vars)
        text = sanitize(text)
        if not too_similar(text, history):
            return text
        tries += 1
    # 似通ってしまう場合のフォールバック
    fallback = random.choice(persona.get("example_posts", ["きょうはここまで。"]))
    return sanitize(fallback)

def post_to_x(text):
    client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET
    )
    resp = client.create_tweet(text=text)
    return resp.data

def save_history(text):
    hist = load_history()
    hist.append(text)
    try:
        json.dump(hist[-100:], open(MEMO_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass

def main():
    text = generate_text()
    data = post_to_x(text)
    save_history(text)
    print("Tweeted:", data)

if __name__ == "__main__":
    main()
