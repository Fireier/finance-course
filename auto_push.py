#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions 财商课程每日自动推送脚本
完全自包含，仅依赖 Python 标准库，在 GitHub Actions 免费额度内运行
"""

import re, os, sys, json, uuid, base64, urllib.request, urllib.error, html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ============================================================
# 配置（敏感信息从环境变量读取）
# ============================================================
CARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance-deep-dives")
PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance-course-progress.json")
SHARE_BASE_URL = "https://fireier.github.io/finance-course"

CLAWBOT_TOKEN = os.environ.get("CLAWBOT_TOKEN", "")
CLAWBOT_USER_ID = os.environ.get("CLAWBOT_USER_ID", "")
CLAWBOT_BASE_URL = os.environ.get("CLAWBOT_BASE_URL", "https://ilinkai.weixin.qq.com")

# 阶段配置
PHASES = [
    (1, 25, "金融世界观基础", "🌍"),
    (26, 45, "大师智慧", "🧠"),
    (46, 65, "投资工具箱", "🔧"),
    (66, 95, "综合实战", "⚔️"),
    (96, 120, "毕业与终身学习", "🎓"),
]

# ============================================================
# HTML 卡片解析
# ============================================================

def parse_html_card(day_num):
    filepath = os.path.join(CARDS_DIR, f"day{day_num:02d}.html")
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    result = {'day': day_num, 'title': '', 'core_points': [], 'tldr': '', 'keywords': ''}
    m = re.search(r'<h1>(.*?)</h1>', content)
    if m:
        result['title'] = html.unescape(m.group(1).strip())
    m = re.search(r'<div class="tldr">.*?<p>(.*?)</p>', content, re.DOTALL)
    if m:
        result['tldr'] = html.unescape(m.group(1).strip())
    m = re.search(r'<div class="sub">(.*?)</div>', content)
    if m:
        result['keywords'] = html.unescape(m.group(1).strip())
    k_texts = re.findall(r'<span class="k-text">(.*?)</span>', content, re.DOTALL)
    for i, k in enumerate(k_texts):
        raw = k.strip()
        text = re.sub(r'<[^>]+>', '', html.unescape(raw))
        strongs = re.findall(r'<strong>(.*?)</strong>', k)
        summary = strongs[0].strip()[:80] if strongs else text[:80].strip()
        result['core_points'].append({'full': text, 'raw_html': raw, 'summary': summary, 'num': i + 1})
    return result


# ============================================================
# 核心知识智能提取
# ============================================================

def is_header_or_empty(s):
    s = s.strip()
    if len(s) < 12:
        return True
    if re.match(r'^.{2,25}[：:：]\s*$', s):
        return True
    if re.match(r'^[A-Z]{2,6}[（(].{0,20}[)）]\s*$', s):
        return True
    patterns = [
        r'^(他是谁|马克斯的核心思想|格雷厄姆|巴菲特|达里奥|芒格|彼得·林奇|查理·芒格)(的|是).{0,25}$',
        r'^(一个|关键|重要|注意|⚠️|批判性|核心).{0,20}$',
        r'^(盈利能力指标|财务指标|核心定义|标准计算|保险浮存金|信息源分级|必备信息).{0,20}$',
        r'^(《.{2,20}》的核心定义).{0,20}$',
        r'^(成长性指标|偿债能力指标|运营效率指标|现金流指标).{0,15}$',
        r'^(平安的|平安经营|保险.{0,5}赚钱).{0,20}$',
        r'^(通过|重要提醒|马克斯识别).{0,20}$',
    ]
    return any(re.match(p, s) for p in patterns)


def extract_key_lines(core_points, max_lines=4):
    lines = []
    for p in core_points:
        if len(lines) >= max_lines:
            break
        s = p['summary']
        if is_header_or_empty(s):
            continue
        if any(s[:20] == l[:20] for l in lines):
            continue
        lines.append(s)
    if len(lines) < 3:
        used = set(lines)
        all_candidates = []
        for p in core_points:
            raw_html = p.get('raw_html', p['full'])
            full_marked = re.sub(r'<br\s*/?>', '\n', raw_html)
            full_marked = re.sub(r'</strong>', '\n', full_marked)
            full_clean = re.sub(r'<[^>]+>', '', full_marked)
            full_clean = re.sub(r'\s+', ' ', full_clean).strip()
            segments = re.split(r'[。；\n]', full_clean)
            for sent in segments:
                sent = sent.strip()
                if len(sent) < 10 or len(sent) > 72:
                    continue
                if is_header_or_empty(sent):
                    continue
                if sent in used:
                    continue
                used.add(sent)
                score = 0
                if re.search(r'(区分|分清|不要|警惕|避免|注意|必须|关键是|核心在)', sent):
                    score += 4
                if re.search(r'(本质|真相|底层|根源|不是.*而是|看起来.*其实)', sent):
                    score += 3
                if re.search(r'[>≥<>]\s*\d+%?', sent):
                    score += 3
                elif re.search(r'\d+%|\d+倍|\d+万亿|\d+亿', sent):
                    score += 2
                if re.search(r'(ROE|PE|PB|PEG|CPI|M2|GDP|ETF|FCF)', sent):
                    score += 2
                if re.search(r'(关键|核心|最重要|陷阱|误区|真正)', sent):
                    score += 1
                all_candidates.append((score, sent))
        dedup = {}
        for score, sent in all_candidates:
            key = sent[:20]
            if key not in dedup or score > dedup[key][0]:
                dedup[key] = (score, sent)
        sorted_candidates = sorted(dedup.values(), key=lambda x: (-x[0], -len(x[1])))
        for score, sent in sorted_candidates:
            if len(lines) >= max_lines:
                break
            lines.append(sent)
    if len(lines) < 2:
        for p in core_points:
            if len(lines) >= max_lines:
                break
            s = p['summary']
            s = re.sub(r'[：:：]\s*$', '', s)
            s = re.sub(r'^[（(][^)）]*[)）]\s*', '', s)
            if len(s) > 8 and s not in lines:
                lines.append(s)
    return lines[:max_lines]


# ============================================================
# 新闻获取（RSS 源，全球可访问，无需 API key）
# ============================================================

def get_finance_news():
    """通过 RSS 获取财经新闻，返回带日期和来源的新闻列表"""
    beijing = timezone(timedelta(hours=8))
    today_str = datetime.now(beijing).strftime('%m月%d日')
    items = []

    # 源1：人民网-财经 RSS
    try:
        req = urllib.request.Request(
            'http://www.people.com.cn/rss/finance.xml',
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            root = ET.fromstring(raw)
            for item in root.findall('.//item')[:5]:
                title = item.findtext('title', '').strip()
                title = re.sub(r'<[^>]+>', '', title)
                pub = item.findtext('pubDate', '').strip()
                if title and len(title) > 8:
                    items.append(f"{today_str} {title[:55]}（来源：人民网）")
                    if len(items) >= 3:
                        break
    except Exception as e:
        print(f"  人民网RSS失败: {e}")

    # 源2：36氪 RSS
    if not items:
        try:
            req = urllib.request.Request(
                'https://36kr.com/feed',
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                root = ET.fromstring(raw)
                for item in root.findall('.//item')[:5]:
                    title = item.findtext('title', '').strip()
                    title = re.sub(r'<[^>]+>', '', title)
                    if title and len(title) > 8:
                        items.append(f"{today_str} {title[:55]}（来源：36氪）")
                        if len(items) >= 3:
                            break
        except Exception as e:
            print(f"  36氪RSS失败: {e}")

    # 源3：IT之家 RSS（科技+财经混合）
    if not items:
        try:
            req = urllib.request.Request(
                'https://www.ithome.com/rss/',
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                root = ET.fromstring(raw)
                for item in root.findall('.//item')[:5]:
                    title = item.findtext('title', '').strip()
                    title = re.sub(r'<[^>]+>', '', title)
                    if title and len(title) > 8:
                        items.append(f"{today_str} {title[:55]}（来源：IT之家）")
                        if len(items) >= 3:
                            break
        except Exception as e:
            print(f"  IT之家RSS失败: {e}")

    return items if items else None


# ============================================================
# ClawBot 发送
# ============================================================

def send_clawbot(text):
    if not CLAWBOT_TOKEN or not CLAWBOT_USER_ID:
        print("ERROR: CLAWBOT_TOKEN or CLAWBOT_USER_ID not set")
        return False

    rand_u = int.from_bytes(os.urandom(4), "little")
    uin = base64.b64encode(str(rand_u).encode()).decode()
    cid = f"wb-{uuid.uuid4().hex[:8]}"

    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {CLAWBOT_TOKEN}",
        "X-WECHAT-UIN": uin,
    }

    payload = {
        "msg": {
            "from_user_id": "",
            "to_user_id": CLAWBOT_USER_ID,
            "client_id": cid,
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": text}}]
        },
        "base_info": {"channel_version": "workbuddy-desktop-1.0.0"}
    }

    url = f'{CLAWBOT_BASE_URL.rstrip("/")}/ilink/bot/sendmessage'
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body) if body else {}
            ret = result.get("ret", result.get("errcode", 0))
            if ret != 0:
                print(f"ERROR: ClawBot returned {result}", file=sys.stderr)
                return False
            print("ClawBot push sent successfully")
            return True
    except Exception as e:
        print(f"ERROR: ClawBot request failed: {e}", file=sys.stderr)
        return False


# ============================================================
# 进度管理
# ============================================================

def get_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    return {'current_day': 1, 'started_date': '', 'total_days': 120}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ============================================================
# 推送生成
# ============================================================

def get_phase(day_num):
    for start, end, name, emoji in PHASES:
        if start <= day_num <= end:
            return name, emoji
    return "毕业与终身学习", "🎓"

def generate_push(card, news_items=None):
    day = card['day']
    phase_name, phase_emoji = get_phase(day)
    progress_pct = round(day / 120 * 100, 1)
    bar_len = 10
    filled = int(day / 120 * bar_len)
    progress_bar = '▓' * filled + '░' * (bar_len - filled)

    key_lines = extract_key_lines(card['core_points'], 4)
    if not key_lines and card.get('tldr'):
        key_lines = [card['tldr'][:65]]

    lines = []
    lines.append(f"💰 📈 财商打卡 · Day {day}")
    lines.append(f"{card['title']}")
    lines.append(f"{progress_bar} {progress_pct}%   {phase_emoji} {phase_name}")
    lines.append("")

    if key_lines:
        lines.append("🔑 核心知识：")
        for i, kl in enumerate(key_lines[:4]):
            lines.append(f"  {i+1}. {kl}")
        lines.append("")

    if news_items and len(news_items) > 0:
        lines.append("📰 今日时事：")
        for n in news_items[:3]:
            lines.append(f"  · {n}")
        lines.append("")

    lines.append("📎 深度学习卡片链接：")
    lines.append(f"  {SHARE_BASE_URL}/day{day:02d}.html")

    msg = '\n'.join(lines)
    if len(msg) > 1800:
        msg = msg[:1750] + "\n...\n" + f"📎 深度学习卡片链接：\n  {SHARE_BASE_URL}/day{day:02d}.html"
    return msg


# ============================================================
# 主入口
# ============================================================

def main():
    print("=" * 50)
    print("Finance Course Auto Push")
    beijing = timezone(timedelta(hours=8))
    print(f"Beijing Time: {datetime.now(beijing).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 1. 读取进度
    progress = get_progress()
    day = progress['current_day']
    print(f"\nProgress: Day {day}/120")

    # 日期防重：同一天不重复推送（应对 cron 多时间点触发）
    today_date = datetime.now(beijing).strftime('%Y-%m-%d')
    if progress.get('last_push_date') == today_date:
        print(f"Already pushed today ({today_date}), skipping")
        return

    if day > 120:
        print("120-day course completed!")
        new_progress = progress.copy()
        new_progress['current_day'] = day
        save_progress(new_progress)
        return

    # 2. 解析当日卡片
    card = parse_html_card(day)
    if card is None:
        print(f"Cannot find card for Day {day}")
        sys.exit(1)
    print(f"Topic: {card['title']}")

    # 3. 获取新闻
    news = get_finance_news()
    if news:
        print(f"Got {len(news)} news items")
    else:
        print("No news available, skipping news section")

    # 4. 生成推送消息
    msg = generate_push(card, news)
    print(f"\nPush content ({len(msg)} chars):")
    print("---")
    print(msg)
    print("---")

    # 5. 发送
    print("\nSending ClawBot push...")
    ok = send_clawbot(msg)
    if not ok:
        print("First attempt failed, retrying in 3s...")
        import time
        time.sleep(3)
        ok = send_clawbot(msg)

    # 6. 更新进度
    new_progress = progress.copy()
    new_progress['current_day'] = day + 1
    new_progress['last_push_date'] = today_date
    save_progress(new_progress)
    print(f"\nProgress updated: Day {day} -> Day {day + 1}")

    if ok:
        print("Today's push completed!")
    else:
        print("Push failed, but progress saved to prevent duplicate push")
        sys.exit(1)


if __name__ == "__main__":
    main()
