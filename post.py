import os, time, json, random, re
from datetime import datetime, timezone
import tweepy
import yaml
from openai import OpenAI

# ---- 環境変数（GitHub Secretsに格納） ----
API_KEY        = os.getenv("X_API_KEY")
API_SECRET     = os.getenv("X_API_SECRET")
ACCESS_TOKEN   = os.getenv("X_ACCESS_TOKEN")
ACCESS_SECRET  = os.getenv("X_ACCESS_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # LLM用

if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, OPENAI_API_KEY]):
    raise RuntimeError("Secretsが不足しています（XとOPENAI）。")

# ---- LLMクライアント ----
client = OpenAI(api_key=OPENAI_API_KEY)

# ---- ペルソナ読込 ----
with open("persona.yaml", "r", encoding="utf-8") as f:
    persona = yaml.safe_load(f)

LANG = persona.get("language", "ja")
max_chars = persona["guardrails"].get("max_chars", 280)
banned = set(persona["guardrails"].get("banned_words", []))
emoji_density = persona["style"].get("emoji_density", "medium")
hashtags_policy = persona["style"].get("hashtags_policy", "2以内で厳選")

# ---- 重複防止のための簡易メモリ ----
MEMO_PATH = ".last_posts.json"
history = []
if os.path.exists(MEMO_PATH):
    try:
        history = json.load(open(MEMO_PATH, "r", encoding="utf-8"))
    except Exception:
        history = []

def too_similar(text, prev_list, threshold=0.85):
    # 超簡易：Jaccardで類似判定（厳密にしたければsimhash等に変更）
    def shingles(s, n=4):
        s = re.sub(r"\s+", "", s)
        return {s[i:i+n] for i in range(max(len(s)-n+1, 1))}
    cur = shingles(text)
    for p in prev_list[-10:]:
        other = shingles(p)
        j = len(cur & other) / max(len(cur | other), 1)
        if j >= threshold:
            return True
    return False

def build_prompt():
    topics = persona["content_preferences"].get("topics_pool", [])
    topic = random.choice(topics) if topics else "日々の気づき"
    tone = persona["style"].get("tone", "ニュートラル")
    formality = persona["style"].get("formality", "カジュアル")
    cta_rate = persona["content_preferences"].get("call_to_action_rate", 0.0)
    quote_rate = persona["content_preferences"].get("add_quote_rate", 0.0)
    now_jst = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d (%a) %H:%M")

    sys = f"""
あなたは「{persona.get('name','ペルソナ')}」として、{LANG}でX向けの短文を作成します。
口調: {tone} / 文体: {formality} / 絵文字密度: {emoji_density} / ハッシュタグ方針: {hashtags_policy}
厳守: 上限{max_chars}文字、誹謗中傷・政治・攻撃的表現・個人情報は避ける。
同じ内容の繰り返しを避け、読みやすい1〜3文で。
可能なら自然な絵文字・ハッシュタグを少量。
"""
    user = f"""
テーマ候補: {topic}
現在時刻(JST近似): {now_jst}

追加の確率的ルール:
- {int(quote_rate*100)}%で短い引用（出典不要・一般的な格言風）
- {int(cta_rate*100)}%で軽い呼びかけ（質問や行動喚起は控えめ）

出力要件:
- プレーンテキストのみ（改行は2回まで）
- ハッシュタグは最大2個まで。多すぎる装飾を避ける
- 先頭と末尾に同じ絵文字を連打しない
- 具体的・等身大・即効性のある微小なコツや姿勢を示す
- 280文字を超えない
"""
    return sys.strip(), user.strip()

def generate_text():
    sys, usr = build_prompt()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",  # 任意の小型モデルでも可
        messages=[{"role":"system","content":sys},
                  {"role":"user","content":usr}],
        temperature=0.95,
        top_p=0.9,
        max_tokens=200
    )
    text = resp.choices[0].message.content.strip()
    # 文字数調整
    if len(text) > max_chars:
        text = text[:max_chars-1] + "…"
    # NGワード除去（シンプル）
    for w in banned:
        text = text.replace(w, "")
    # 類似チェック
    if too_similar(text, history):
        text += "\n#今日の学び"
        if len(text) > max_chars:
            text = text[:max_chars]
    return text

def post_to_x(text):
    auth_client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET
    )
    r = auth_client.create_tweet(text=text)
    return r.data

def main():
    text = generate_text()
    data = post_to_x(text)
    # 履歴保存
    history.append(text)
    try:
        json.dump(history[-50:], open(MEMO_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass
    print("Tweeted:", data)

if __name__ == "__main__":
    main()
