#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions 财商课程每日自动推送脚本 v5
- 新闻源：Google News RSS（按主题关键词搜索，确保相关性）+ 36氪 + 财联社 + 华尔街见闻 + IT之家
- 严格相关性：必须命中主题关键词才推新闻，否则跳过
- 每条新闻摘要50-100字
- 每天推送2条新闻
"""

import re, os, sys, json, uuid, base64, urllib.request, urllib.error, urllib.parse, html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# ============================================================
# 配置
# ============================================================
CARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance-deep-dives")
PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance-course-progress.json")
SHARE_BASE_URL = "https://fireier.github.io/finance-course"

CLAWBOT_TOKEN = os.environ.get("CLAWBOT_TOKEN", "")
CLAWBOT_USER_ID = os.environ.get("CLAWBOT_USER_ID", "")
CLAWBOT_BASE_URL = os.environ.get("CLAWBOT_BASE_URL", "https://ilinkai.weixin.qq.com")

PHASES = [
    (1, 25, "金融世界观基础", "🌍"),
    (26, 45, "大师智慧", "🧠"),
    (46, 65, "投资工具箱", "🔧"),
    (66, 95, "综合实战", "⚔️"),
    (96, 120, "毕业与终身学习", "🎓"),
]

# ============================================================
# 泛金融关键词（用来判断一条新闻是否算财经新闻）
# ============================================================
FINANCE_KEYWORDS = [
    # 宏观
    "央行", "利率", "降息", "加息", "通胀", "CPI", "PPI", "GDP", "PMI",
    "货币政策", "财政", "逆回购", "MLF", "LPR", "汇率", "人民币", "美元",
    "外汇", "国债", "税收", "减税", "赤字", "顺差", "逆差",
    # 银行与金融
    "银行", "贷款", "存款", "信贷", "金融", "理财", "保险", "支付",
    "数字人民币", "数字货币", "支付宝", "微信支付", "银联",
    # 资本市场
    "股市", "股票", "A股", "上证", "深证", "创业板", "科创板", "北交所",
    "港股", "美股", "IPO", "上市", "市值", "指数", "基金", "ETF",
    "债券", "期货", "期权", "涨停", "跌停", "减持", "增持", "回购", "分红",
    # 行业与投资
    "房地产", "房价", "楼市", "房贷",
    "新能源", "芯片", "半导体", "人工智能", "AI", "数字经济", "互联网",
    "消费", "零售", "汽车", "医药", "白酒", "煤炭", "石油", "黄金",
    "投资", "资产", "收益", "风险", "估值",
    # 公司财务
    "融资", "营收", "利润", "亏损", "盈利", "财报", "季度", "年报",
    "创始人", "收购", "并购", "重组", "剥离",
    # 国际经济
    "美联储", "欧元", "日元", "贸易", "关税", "进出口",
    "纳斯达克", "道琼斯", "标普",
    # 个人财务
    "收入", "工资", "就业", "失业", "社保", "养老", "公积金",
    "消费者", "购买力", "物价", "涨价", "降价",
    # 机构
    "证监会", "银保监", "财政部", "统计局", "发改委", "商务部",
    "M2", "社融",
]
FINANCE_KEYWORDS = [kw for kw in FINANCE_KEYWORDS if len(kw) >= 2]

NON_FINANCE_PATTERNS = [
    '耳机', '礼盒', '预售', '电动自行车', '测速', '游戏', '动漫',
    '综艺', '电影', '音乐', '明星', '穿搭', '美妆', '护肤', '宠物',
    '天气', '星座', '高考', '中考', '节日', '美食', '旅游攻略',
    '中超', '冠军', '夺冠', '比赛', '运动员', '球队', '体育',
]

# ============================================================
# 从卡片提取主题关键词
# ============================================================

NOISE_WORDS = {
    '分钟', '约', '的', '是', '和', '与', '不', '了', '在', '有', '这',
    '10', '12', '15', '入门', '基础', '进阶', '教你', '学会', '了解',
    '更多', '最重要', '最重要。', '点击', '查看', '阅读',
}


def extract_topic_keywords(card):
    """从卡片提取主题关键词，用于新闻匹配"""
    keywords = []

    # 1. 副标题（作者手动标注的核心概念，质量最高）
    kw_str = card.get('keywords', '')
    if kw_str:
        kw_str_clean = re.sub(r'<[^>]+>', '', kw_str)
        for p in re.split(r'[ /·,，、]+', kw_str_clean):
            p = p.strip()
            if p and len(p) >= 2 and not p.isdigit() and p not in NOISE_WORDS:
                keywords.append(p)

    # 2. 标题中的核心词
    title = card.get('title', '')
    title_clean = re.sub(r'<[^>]+>', '', title)
    title_clean = re.sub(r'[（(][^)）]*[)）]', '', title_clean)
    for part in re.split(r'[——：:，,、。！？\s\-?]+', title_clean):
        part = part.strip()
        if 2 <= len(part) <= 6 and part not in NOISE_WORDS and not part.isdigit():
            keywords.append(part)

    # 3. 核心知识点的专有名词
    for cp in card.get('core_points', [])[:4]:
        summary = cp.get('summary', '')
        summary_clean = re.sub(r'<[^>]+>', '', summary)
        for a in re.findall(r'\b[A-Z]{2,6}\b', summary_clean):
            if a not in NOISE_WORDS and len(a) >= 2:
                keywords.append(a)
        for b in re.findall(r'《(.+?)》', summary_clean):
            if 2 <= len(b.strip()) <= 8:
                keywords.append(b.strip())

    # 去重
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


def score_news_item(title, desc, topic_keywords):
    """按主题相关性给新闻打分"""
    combined = (title + ' ' + desc) if desc else title
    score = 0

    # 主题关键词命中（权重 x3）
    for kw in topic_keywords:
        if len(kw) >= 2 and kw in combined:
            score += 3

    # 泛金融关键词命中（权重 x1）
    finance_hits = 0
    for kw in FINANCE_KEYWORDS:
        if kw in combined:
            finance_hits += 1
    score += finance_hits

    # 完全非财经内容惩罚
    is_non_finance = False
    for nf in NON_FINANCE_PATTERNS:
        if nf in title:
            is_non_finance = True
            break
    if is_non_finance and finance_hits < 2:
        score -= 10

    # 标题太短（低质量）
    if len(title) < 10:
        score -= 3

    return score


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
    patterns = [
        r'^(他是谁|马克斯的核心思想|格雷厄姆|巴菲特|达里奥|芒格)(的|是).{0,25}$',
        r'^(一个|关键|重要|注意|⚠️).{0,20}$',
        r'^(盈利能力|财务指标|核心定义).{0,20}$',
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
        candidates = []
        for p in core_points:
            raw = p.get('raw_html', p['full'])
            full_clean = re.sub(r'<[^>]+>', '', raw).strip()
            full_clean = re.sub(r'\s+', ' ', full_clean)
            for sent in re.split(r'[。；\n]', full_clean):
                sent = sent.strip()
                if len(sent) < 10 or len(sent) > 72 or is_header_or_empty(sent) or sent in used:
                    continue
                used.add(sent)
                score = 0
                if re.search(r'(区分|分清|不要|警惕|避免|注意)', sent):
                    score += 4
                if re.search(r'(本质|真相|底层|根源)', sent):
                    score += 3
                if re.search(r'\d+%|\d+倍|\d+万亿|\d+亿', sent):
                    score += 2
                if re.search(r'(ROE|PE|PB|PEG|CPI|M2|GDP|ETF)', sent):
                    score += 2
                candidates.append((score, sent))
        candidates.sort(key=lambda x: (-x[0], -len(x[1])))
        for score, sent in candidates:
            if len(lines) >= max_lines:
                break
            lines.append(sent)
    return lines[:max_lines]


# ============================================================
# 新闻获取
# ============================================================

def parse_rss_date(date_str):
    """解析 RSS 日期字符串（支持多种格式），返回 (标准日期, datetime)"""
    if not date_str:
        return None, None
    beijing = timezone(timedelta(hours=8))
    # 36氪格式: '2026-07-10 11:26:25  +0800'
    try:
        d_clean = date_str.strip().replace('  ', ' ')
        dt = datetime.strptime(d_clean, '%Y-%m-%d %H:%M:%S %z')
        dt = dt.astimezone(beijing)
        return dt.strftime('%m月%d日'), dt
    except ValueError:
        pass
    # 标准 RSS 格式 (email.utils)
    try:
        dt = parsedate_to_datetime(date_str)
        dt = dt.astimezone(beijing)
        return dt.strftime('%m月%d日'), dt
    except Exception:
        return None, None


def fetch_rss_items(url, source_name, max_items=10):
    """从 RSS 获取新闻条目（含标题、摘要、日期）"""
    items = []
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; FinanceCourseBot/1.0)'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            root = ET.fromstring(raw)
            for item in root.findall('.//item')[:max_items]:
                title = item.findtext('title', '').strip()
                title = re.sub(r'<[^>]+>', '', title)
                title = re.sub(r'^\d+点\d+氪\s*[|｜]\s*', '', title)
                title = re.sub(r'^\d+[\.\、]\s*', '', title)

                # Google News: title格式为 "文章标题 - 来源名"
                actual_source = source_name
                if source_name == 'Google News':
                    source_elem = item.find('source')
                    if source_elem is not None and source_elem.text:
                        actual_source = source_elem.text.strip()
                        if f' - {actual_source}' in title:
                            title = title.replace(f' - {actual_source}', '').strip()
                    elif ' - ' in title:
                        parts = title.rsplit(' - ', 1)
                        title = parts[0].strip()
                        actual_source = parts[1].strip()

                desc = item.findtext('description', '').strip()
                # 先反转义HTML实体，再去标签
                desc = html.unescape(desc)
                desc = re.sub(r'<[^>]+>', '', desc)
                desc = re.sub(r'\s+', ' ', desc).strip()
                # Google News的description常以标题开头，去掉重复部分
                if source_name == 'Google News' and desc and title and desc.startswith(title[:15]):
                    desc = desc[len(title[:15]):].strip()
                # 取前80字作为摘要（50-100字范围）
                desc = desc[:80]

                pub_date = item.findtext('pubDate', '').strip()
                date_str, dt = parse_rss_date(pub_date)

                if title and len(title) > 8:
                    items.append({
                        'title': title,
                        'desc': desc,
                        'date_str': date_str,
                        'datetime': dt,
                        'source': actual_source,
                    })
    except Exception as e:
        print(f"  {source_name} RSS: {e}")
    return items


def get_finance_news(topic_keywords=None):
    """
    获取与当天课程主题相关的财经新闻。
    Google News按主题关键词搜索（主力，确保相关性）+ 36氪 + 财联社 + 华尔街见闻 + IT之家
    严格门槛：必须命中至少一个主题关键词（score >= 3）才推送，否则跳过。
    只取2条，摘要80字以内。
    """
    if topic_keywords is None:
        topic_keywords = []

    beijing = timezone(timedelta(hours=8))
    now = datetime.now(beijing)

    all_items = []

    # 主力源1：Google News RSS（按主题关键词搜索，确保相关性）
    if topic_keywords:
        query = ' OR '.join(topic_keywords[:5])
        encoded_query = urllib.parse.quote(query)
        google_url = f'https://news.google.com/rss/search?q={encoded_query}+when:3d&hl=zh-CN&gl=CN&ceid=CN:zh'
        print(f"  获取 Google News RSS (搜索: {query})...")
        google_items = fetch_rss_items(google_url, 'Google News', max_items=20)
        all_items.extend(google_items)
        print(f"    Google News: {len(google_items)} 条")

    # 辅助源1：财联社电报（专业财经快讯，首选）
    print("  获取财联社电报 RSS...")
    cls_items = fetch_rss_items('https://rsshub.app/cls/telegraph', '财联社', max_items=15)
    all_items.extend(cls_items)
    print(f"    财联社: {len(cls_items)} 条")

    # 辅助源2：华尔街见闻（深度财经）
    print("  获取华尔街见闻 RSS...")
    wscn_items = fetch_rss_items('https://rsshub.app/wallstreetcn/live', '华尔街见闻', max_items=15)
    all_items.extend(wscn_items)
    print(f"    华尔街见闻: {len(wscn_items)} 条")

    # 辅助源3：金十数据（专业数据/快讯）
    print("  获取金十数据 RSS...")
    jinshi_items = fetch_rss_items('https://rsshub.app/jin10/2', '金十数据', max_items=10)
    all_items.extend(jinshi_items)
    print(f"    金十数据: {len(jinshi_items)} 条")

    # 辅助源4：新浪财经（综合财经）
    print("  获取新浪财经 RSS...")
    sina_items = fetch_rss_items('https://rsshub.app/sina/rollnews', '新浪财经', max_items=15)
    all_items.extend(sina_items)
    print(f"    新浪财经: {len(sina_items)} 条")

    # 辅助源5：财新（深度报道）
    print("  获取财新 RSS...")
    caixin_items = fetch_rss_items('https://rsshub.app/caixin/latest', '财新', max_items=10)
    all_items.extend(caixin_items)
    print(f"    财新: {len(caixin_items)} 条")

    # 辅助源6：36氪（科技商业）
    print("  获取36氪 RSS...")
    kr_items = fetch_rss_items('https://36kr.com/feed', '36氪', max_items=10)
    all_items.extend(kr_items)
    print(f"    36氪: {len(kr_items)} 条")

    # 兜底源：IT之家（科技新闻，最后备选）
    print("  获取IT之家 RSS...")
    it_items = fetch_rss_items('https://www.ithome.com/rss/', 'IT之家', max_items=8)
    all_items.extend(it_items)
    print(f"    IT之家: {len(it_items)} 条")

    print(f"  共 {len(all_items)} 条候选新闻")

    if not all_items:
        return None

    # 按主题相关度打分
    scored = []
    for item in all_items:
        s = score_news_item(item['title'], item.get('desc', ''), topic_keywords)
        scored.append((s, item))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 调试输出
    print(f"  主题关键词: {', '.join(topic_keywords[:8])}" if topic_keywords else "  无主题关键词")
    print("  TOP5 相关度:")
    for score, item in scored[:5]:
        print(f"    [{score:3d}] {item['source']}: {item['title'][:50]}")

    # 严格门槛：必须命中至少一个主题关键词（score >= 3）
    if topic_keywords:
        top_score = scored[0][0] if scored else 0
        if top_score < 3:
            print("  ⚠ 新闻与课程主题无直接关联，跳过新闻板块")
            return None

    # 取分数最高的2条，去重
    selected = []
    seen_titles = set()
    for score, item in scored:
        if len(selected) >= 2:
            break
        title_key = item['title'][:20]
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        date = item.get('date_str') or now.strftime('%m月%d日')
        src = item['source']
        title = item['title'][:55]
        desc = item.get('desc', '')

        if desc and len(desc) > 10:
            line = f"{date} | {src}\n  {title}\n  {desc}"
        else:
            line = f"{date} | {src}\n  {title}"
        selected.append(line)

    if not selected:
        return None

    return selected


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
        for n in news_items[:2]:
            lines.append(f"  · {n}")
        lines.append("")

    lines.append("📎 深度学习卡片链接：")
    lines.append(f"  {SHARE_BASE_URL}/day{day:02d}.html")

    msg = '\n'.join(lines)
    if len(msg) > 1800:
        msg = msg[:1750] + "\n...\n" + f"📎 {SHARE_BASE_URL}/day{day:02d}.html"
    return msg


# ============================================================
# 主入口
# ============================================================

def main():
    print("=" * 50)
    print("Finance Course Auto Push v5")
    beijing = timezone(timedelta(hours=8))
    print(f"Beijing Time: {datetime.now(beijing).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 1. 读取进度
    progress = get_progress()
    day = progress['current_day']
    print(f"\nProgress: Day {day}/120")

    # 日期防重
    today_date = datetime.now(beijing).strftime('%Y-%m-%d')
    if progress.get('last_push_date') == today_date:
        print(f"Already pushed today ({today_date}), skipping")
        return

    if day > 120:
        print("Course completed!")
        return

    # 2. 解析卡片
    card = parse_html_card(day)
    if card is None:
        print(f"Cannot find card for Day {day}")
        sys.exit(1)
    print(f"Topic: {card['title']}")

    # 3. 提取关键词
    topic_keywords = extract_topic_keywords(card)
    if topic_keywords:
        preview = topic_keywords[:10]
        print(f"Keywords ({len(topic_keywords)}): {preview}")

    # 4. 获取相关新闻
    news = get_finance_news(topic_keywords)
    if news:
        print(f"Selected {len(news)} relevant news items")
    else:
        print("No relevant news, skipping news section")

    # 5. 生成推送
    msg = generate_push(card, news)
    print(f"\nPush content ({len(msg)} chars):")
    print("---")
    print(msg)
    print("---")

    # 6. 发送
    print("\nSending...")
    ok = send_clawbot(msg)
    if not ok:
        import time
        time.sleep(3)
        ok = send_clawbot(msg)

    # 7. 更新进度
    new_progress = progress.copy()
    new_progress['current_day'] = day + 1
    new_progress['last_push_date'] = today_date
    save_progress(new_progress)
    print(f"\nProgress: Day {day} -> Day {day + 1}")

    if ok:
        print("Done!")
    else:
        print("Push failed, progress saved to prevent duplicate")
        sys.exit(1)


if __name__ == "__main__":
    main()
