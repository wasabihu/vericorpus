"""面向中文/双语与专业术语的纯净零依赖 XERJ 检索增强模块。"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Any

from . import compliance

STOP_PHRASES = (
    "中华人民共和国",
    "请从原文",
    "怎么看",
    "怎么写",
    "合计是多少",
    "累计是多少",
    "是多少",
    "有多少",
    "多少",
    "发给我",
    "发我",
    "帮我",
    "查一下",
    "找一下",
    "看一下",
    "一下",
    "那个",
    "这个",
    "什么",
    "有哪些",
    "有没有",
    "哪些",
    "叫什么",
    "关于",
    "请问",
    "根据",
    "按照",
    "相比",
    "之间",
    "相差",
    "分别",
    "只答数字",
)

_LEADING_VERB_RE = re.compile(r"(?:^|(?<=[\s，。；：？!！]))(?:请)?(?:计算|对比)(?:一下)?(?=\s|[A-Za-z0-9《「\u4e00-\u9fff])")

# Pure grammatical particles only: never include entity-forming characters (里, 和, 过, 对, 还, 到, 都, 去, 从).
STOP_CHARS = set("把的了呢啊吗是在我你他它被给与及或就也很着")

_FALLBACK_SIMP_TRAD_PAIRS = (
    "万萬与與专專业業东東两兩严嚴个個临臨为爲举舉么麼义義乐樂习習乡鄉书書买買乱亂争爭"
    "亏虧云雲亚亞产產亲親亿億仅僅从從仓倉仪儀们們价價众衆优優会會伟偉传傳伤傷伦倫伪僞"
    "体體余餘佣傭侦偵侧側侨僑俩倆俭儉倾傾偿償储儲儿兒兑兌党黨兰蘭关關兴興养養兽獸内內"
    "冈岡册冊写寫军軍农農决決况況净淨准準凉涼减減凑湊几幾凤鳳凭憑凯凱击擊划劃则則创創"
    "删刪别別剂劑剑劍剥剝剧劇劝勸办辦务務动動励勵劲勁劳勞势勢勋勳汇匯区區医醫华華"
    "单單卖賣卢盧卫衛却卻厅廳历曆压壓厌厭厕廁厢廂厦廈厨廚参參双雙发發变變叙敘叠疊台臺"
    "号號叹歎后後吓嚇吗嗎听聽启啟员員响響哑啞哗嘩问問唤喚喷噴嘱囑园園团團围圍国國图圖"
    "圆圓场場坏壞坚堅坛壇坝壩垒壘垫墊堕墮报報块塊涂塗声聲壳殼处處备備复複够夠头頭夸誇"
    "夹夾夺奪奋奮奖獎奥奧妇婦妈媽娱娛婴嬰孙孫学學宝寶实實宠寵审審宪憲宫宮宽寬宾賓寻尋"
    "导導寿壽将將尔爾尘塵尝嘗尴尷尽盡届屆属屬屡屢层層岁歲岗崗岛島峡峽崭嶄币幣帅帥师師"
    "帐帳帜幟帧幀帮幫带帶广廣庄莊庆慶库庫应應庙廟庞龐废廢开開异異弃棄张張弥彌弯彎弹彈"
    "强強归歸当當录錄彻徹径徑忆憶忧憂怀懷态態总總恋戀恒恆恳懇恶惡悦悅悬懸惊驚惧懼惨慘"
    "惩懲惭慚惯慣愿願慑懾戏戲战戰户戶执執扩擴扫掃扬揚扰擾拟擬拥擁择擇损損换換据據携攜"
    "摇搖摊攤摆擺撑撐敌敵败敗数數斋齋断斷无無旧舊时時显顯晋晉晒曬晓曉暂暫术術机機杀殺"
    "杂雜权權条條来來杨楊极極构構枢樞枪槍枫楓标標栈棧栋棟栏欄树樹样樣档檔桥橋梦夢检檢"
    "楼樓樱櫻欢歡欧歐残殘毁毀毕畢气氣氢氫汉漢汤湯沟溝没沒泽澤洁潔洒灑测測济濟浏瀏览覽"
    "浑渾浓濃涛濤涨漲渐漸温溫湾灣湿濕溃潰溅濺潜潛灭滅灯燈灵靈灾災炉爐点點炼煉烂爛烧燒"
    "热熱爱愛爷爺牵牽牺犧状狀犹猶独獨狭狹狮獅狱獄猎獵献獻环環现現琐瑣瑶瑤电電画畫疗療"
    "痴癡瘫癱盘盤监監矫矯硕碩确確祸禍离離种種称稱税稅稳穩积積穷窮笔筆简簡节節范範筹籌"
    "类類纠糾红紅约約级級纪紀纯純纲綱纳納纵縱纷紛纸紙纽紐线線练練组組细細终終经經结結"
    "绕繞绘繪给給络絡绝絕统統继繼绩績绪緒续續维維综綜绿綠缓緩编編缘緣缩縮缴繳网網罗羅"
    "罚罰罢罷职職联聯聪聰肾腎胆膽胜勝胶膠脉脈脏臟脑腦脱脫脸臉腻膩腾騰艰艱艺藝药藥获獲"
    "营營萧蕭萨薩蓝藍盖蓋虫蟲虽雖补補装裝裤褲见見观觀规規视視觉覺触觸计計订訂认認讨討"
    "让讓议議讯訊训訓记記讲講许許论論设設访訪证證评評识識诉訴词詞译譯试試诗詩诚誠话話"
    "诞誕询詢该該详詳语語误誤诱誘说說请請诸諸诺諾读讀课課谁誰调調谈談谋謀谓謂谢謝谨謹"
    "谱譜贝貝负負贡貢财財责責贤賢货貨质質贩販贪貪贫貧购購贯貫贴貼贵貴贷貸费費贺賀贼賊"
    "资資赔賠赏賞赋賦赌賭赚賺赛賽赞贊赠贈赢贏趋趨跃躍车車轨軌轩軒转轉轮輪软軟轻輕载載"
    "较較辅輔辈輩辉輝辑輯输輸辞辭辩辯边邊达達迁遷过過迈邁运運还還这這进進远遠违違连連"
    "适適选選逊遜递遞遗遺遥遙邓鄧邮郵邻鄰郁鬱郑鄭释釋针針钓釣钟鐘钢鋼钱錢铁鐵铜銅铭銘"
    "银銀锁鎖锅鍋锋鋒错錯锡錫锦錦镇鎮镜鏡长長门門闭閉闲閑间間闷悶闹鬧闻聞阁閣阅閱阔闊"
    "阳陽阴陰阵陣阶階际際陆陸险險隐隱难難静靜韦韋韵韻页頁顶頂项項顺順须須顽頑顾顧预預"
    "领領颇頗频頻颗顆题題额額颜顏颠顛风風飞飛饭飯饮飲饰飾饱飽饼餅馆館马馬驱驅驶駛驻駐"
    "驾駕验驗骑騎骗騙骚騷鱼魚鲁魯鲜鮮鸟鳥鸡雞鸣鳴鸭鴨鹅鵝麦麥黄黃齐齊齿齒龙龍龟龜协協账賬"
)

_EXTRA_T2S_MAP = {
    "歷": "历",
    "曆": "历",
    "復": "复",
    "複": "复",
    "覆": "覆",
    "髮": "发",
    "發": "发",
    "乾": "干",
    "幹": "干",
    "註": "注",
    "製": "制",
    "徵": "征",
    "裏": "里",
    "裡": "里",
    "後": "后",
    "範": "范",
    "餘": "余",
    "臺": "台",
    "檯": "台",
    "賬": "账",
    "帳": "账",
    "於": "于",
    "眾": "众",
    "衆": "众",
    "衞": "卫",
    "衛": "卫",
    "綫": "线",
    "線": "线",
    "滙": "汇",
    "匯": "汇",
    "髒": "脏",
    "臟": "脏",
    "闆": "板",
    "藉": "借",
    "昇": "升",
    "甦": "苏",
    "萊": "莱",
    "貝": "贝",
}

_S2T_PHRASE_FIXES: tuple[tuple[str, str], ...] = (
    ("注册制", "註冊制"),
    ("注冊製", "註冊制"),
    ("注冊制", "註冊制"),
    ("註冊製", "註冊制"),
    ("注册", "註冊"),
    ("注冊", "註冊"),
    ("注释", "註釋"),
    ("附注", "附註"),
    ("制造", "製造"),
    ("制备", "製備"),
    ("制剂", "製劑"),
    ("制品", "製品"),
    ("定制", "定製"),
    ("复制", "複製"),
    ("研制", "研製"),
    ("病历", "病歷"),
    ("病曆", "病歷"),
    ("经历", "經歷"),
    ("經曆", "經歷"),
    ("学历", "學歷"),
    ("學曆", "學歷"),
    ("简历", "簡歷"),
    ("簡曆", "簡歷"),
    ("历史", "歷史"),
    ("曆史", "歷史"),
    ("干细胞", "幹細胞"),
    ("干細胞", "幹細胞"),
    ("骨干", "骨幹"),
    ("干燥", "乾燥"),
    ("回复", "回復"),
    ("回覆", "回復"),
    ("回覆", "回復"),
    ("恢复", "恢復"),
    ("恢複", "恢復"),
    ("脱发", "脫髮"),
    ("脫發", "脫髮"),
    ("毛发", "毛髮"),
    ("毛發", "毛髮"),
    ("头发", "頭髮"),
    ("頭發", "頭髮"),
    ("贝莱德", "貝萊德"),
)


def _parse_pairs() -> tuple[dict[int, int], dict[int, int]]:
    s2t: dict[str, str] = {}
    t2s: dict[str, str] = dict(_EXTRA_T2S_MAP)
    for i in range(0, len(_FALLBACK_SIMP_TRAD_PAIRS) - 1, 2):
        s, t = _FALLBACK_SIMP_TRAD_PAIRS[i], _FALLBACK_SIMP_TRAD_PAIRS[i + 1]
        if s != t:
            s2t.setdefault(s, t)
            t2s.setdefault(t, s)
    return str.maketrans(s2t), str.maketrans(t2s)


_FALLBACK_S2T_TABLE, _FALLBACK_T2S_TABLE = _parse_pairs()


def _init_cf_transform():
    try:
        lib_path = ctypes.util.find_library("CoreFoundation")
        if not lib_path:
            return None
        cf = ctypes.cdll.LoadLibrary(lib_path)
        k_utf8 = 0x08000100
        cf.CFStringCreateWithBytes.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32, ctypes.c_bool]
        cf.CFStringCreateWithBytes.restype = ctypes.c_void_p
        cf.CFStringCreateMutableCopy.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]
        cf.CFStringCreateMutableCopy.restype = ctypes.c_void_p
        cf.CFStringTransform.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        cf.CFStringTransform.restype = ctypes.c_bool
        cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
        cf.CFStringGetLength.restype = ctypes.c_long
        cf.CFStringGetMaximumSizeForEncoding.argtypes = [ctypes.c_long, ctypes.c_uint32]
        cf.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None

        def run(text: str, rule: str) -> str:
            if not text:
                return text
            raw = text.encode("utf-8")
            rule_raw = rule.encode("utf-8")
            src = cf.CFStringCreateWithBytes(None, raw, len(raw), k_utf8, False)
            mut = None
            tr = None
            try:
                if not src:
                    return text
                mut = cf.CFStringCreateMutableCopy(None, 0, src)
                tr = cf.CFStringCreateWithBytes(None, rule_raw, len(rule_raw), k_utf8, False)
                if not mut or not tr:
                    return text
                cf.CFStringTransform(mut, None, tr, False)
                length = cf.CFStringGetLength(mut)
                max_sz = cf.CFStringGetMaximumSizeForEncoding(length, k_utf8) + 1
                buf = ctypes.create_string_buffer(max_sz)
                if not cf.CFStringGetCString(mut, buf, max_sz, k_utf8):
                    return text
                return buf.value.decode("utf-8", errors="replace")
            finally:
                if tr:
                    cf.CFRelease(tr)
                if mut:
                    cf.CFRelease(mut)
                if src:
                    cf.CFRelease(src)

        if run("协作", "Simplified-Traditional") == "協作":
            return run
    except Exception:
        return None
    return None


_CF_TRANSFORM = _init_cf_transform()


def _apply_s2t_phrase_fixes(text: str) -> str:
    out = text
    for src, dst in _S2T_PHRASE_FIXES:
        if src in out:
            out = out.replace(src, dst)
    return out


def to_traditional(text: str) -> str:
    if not text or not re.search(r"[\u4e00-\u9fff]", text):
        return text
    pre = _apply_s2t_phrase_fixes(text)
    if _CF_TRANSFORM is not None:
        try:
            return _apply_s2t_phrase_fixes(_CF_TRANSFORM(pre, "Simplified-Traditional"))
        except Exception:
            pass
    return _apply_s2t_phrase_fixes(pre.translate(_FALLBACK_S2T_TABLE))


def to_simplified(text: str) -> str:
    if not text or not re.search(r"[\u4e00-\u9fff]", text):
        return text
    if _CF_TRANSFORM is not None:
        try:
            return _CF_TRANSFORM(text, "Traditional-Simplified").translate(_FALLBACK_T2S_TABLE)
        except Exception:
            pass
    return text.translate(_FALLBACK_T2S_TABLE)


def cjk_variants(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for item in (text, to_traditional(text), to_simplified(text)):
        if item and item not in out:
            out.append(item)
    return out


_ZH_DIGITS = "零一二三四五六七八九"
_ZH_DIGIT_VAL = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_UNIT_VAL = {"十": 10, "百": 100, "千": 1000, "万": 10000, "萬": 10000, "亿": 100_000_000, "億": 100_000_000}


def int_to_zh(n: int) -> str:
    if not isinstance(n, int) or n <= 0 or n > 99999:
        return str(n)
    if n >= 10000:
        hi, lo = divmod(n, 10000)
        head = int_to_zh(hi) + "万"
        if lo == 0:
            return head
        if lo < 1000:
            return head + "零" + _int_to_zh_under_10000(lo, compact_ten=False)
        return head + _int_to_zh_under_10000(lo, compact_ten=False)
    return _int_to_zh_under_10000(n, compact_ten=(n < 100))


def _int_to_zh_under_10000(n: int, compact_ten: bool = True) -> str:
    if n == 0:
        return "零"
    units = [(1000, "千"), (100, "百"), (10, "十"), (1, "")]
    out: list[str] = []
    pending_zero = False
    for divisor, unit in units:
        d, n = divmod(n, divisor)
        if d == 0:
            if out and n > 0:
                pending_zero = True
            continue
        if pending_zero:
            out.append("零")
            pending_zero = False
        if divisor == 10 and d == 1 and compact_ten and not out:
            out.append("十")
        else:
            out.append(_ZH_DIGITS[d] + unit)
    return "".join(out)


def zh_to_int(text: str) -> int | None:
    s = (text or "").strip()
    if not s:
        return None
    if all(ch in _ZH_DIGIT_VAL for ch in s):
        val = _ZH_DIGIT_VAL[s] if len(s) == 1 else 0
        return val if val > 0 else None

    grand_total = total = section = num = 0
    for ch in s:
        if ch in _ZH_DIGIT_VAL:
            num = _ZH_DIGIT_VAL[ch]
        elif ch in _ZH_UNIT_VAL:
            unit = _ZH_UNIT_VAL[ch]
            if unit == 100_000_000:
                part = (total + section + num) if (total or section or num) else 1
                grand_total += part * unit
                total = section = num = 0
            elif unit == 10000:
                section = (section + num) * unit if (section or num) else unit
                total += section
                section = num = 0
            else:
                if num == 0 and unit == 10 and section == 0:
                    num = 1
                elif num == 0:
                    return None
                section += num * unit
                num = 0
        else:
            return None
    val = grand_total + total + section + num
    return val if val > 0 else None


DOC_FORMATS = [
    "md",
    "markdown",
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "epub",
    "txt",
    "txt-prose",
    "txt-lines",
    "html",
]

DOMAIN_SYNONYMS: dict[str, list[str]] = {
    "归母净利润": [
        "归属于上市公司股东的净利润",
        "歸屬於上市公司股東的淨利潤",
        "股東應佔溢利",
        "本公司權益持有人應佔溢利",
        "歸屬於普通股股東的淨利潤",
        "归属于普通股股东的净利润",
        "net income attributable",
        "net profit attributable",
    ],
    "经调整净利润": ["非國際財務報告準則", "非公認會計準則", "non-ifrs", "non-gaap", "adjusted net income"],
    "经调整盈利": ["非國際財務報告準則", "非公認會計準則", "non-ifrs", "non-gaap", "adjusted profit"],
    "非国际财务报告准则": ["非公認會計準則", "non-ifrs", "non-gaap", "adjusted net income"],
    "股份支付": ["股權激勵", "以股份為基礎的酬金", "share-based compensation"],
    "营业收入": ["營業收入", "營業額", "營收", "收益", "來自客戶合同的收入", "revenue"],
    "毛利润": ["毛利", "gross profit"],
    "营业利润": ["經營溢利", "operating income", "operating profit"],
    "净利润": ["淨利潤", "net income", "net profit"],
    "研发费用": ["研發費用", "研发支出", "research and development"],
    "总资产": ["總資產", "total assets"],
    "股东权益": ["股東權益", "stockholders' equity", "shareholders' equity"],
    "经营性现金流": ["經營現金流", "operating cash flow", "cash flows from operating activities"],
    "摊薄每股收益": ["稀釋每股收益", "diluted earnings per share", "diluted EPS"],
    "普通股": ["ordinary shares", "common stock"],
    "首次公开发行": ["initial public offering", "IPO"],
    "自由现金流": ["free cash flow"],
    "资本开支": ["資本支出", "capex", "capital expenditure"],
    "回购股份": ["股份回購", "購回股份", "share repurchase", "buyback"],
    "即时检验": ["POCT", "point-of-care", "point-of-care testing"],
    "生物3d打印": ["bioprinting", "生物打印"],
    "肺癌": ["lung cancer"],
    "低剂量ct": ["low-dose computed tomography", "LDCT"],
    "急性淋巴细胞白血病": ["acute lymphoblastic leukemia", "ALL"],
}

_BOOK_TITLE_RE = re.compile(r"《([^》]{2,40})》")
_EN_PHRASE_RE = re.compile(r"[A-Za-z][A-Za-z0-9&'-]*(?:\s+(?:&|and|of|the|for|in)?\s*[A-Za-z][A-Za-z0-9&'-]*){1,3}")
_GENERIC_UPPER_TERMS = frozenset(
    {
        "SEC", "IPO", "ADS", "ADRS", "AI", "ML", "CT", "PE", "VC", "PDF", "USD", "TWD", "CNY", "RMB",
        "HKD", "EUR", "GAAP", "IFRS", "TAM", "EPS", "DCU", "DFB", "EML", "CPU", "GPU", "NPU", "ISA",
        "SDK", "API", "URL", "CLI", "LLM", "RAG", "OCR", "CAGR", "NOA", "GLM", "MAAS", "RWA", "FSD",
        "POCT", "LDCT", "ALL", "PD", "XERJ", "BM25", "TOP", "XBRL", "JSON", "HTML", "USA", "PRC",
        "UK", "US", "CN", "HK", "CXL", "SOC", "PC", "TV",
    }
)
_GENERIC_ASCII_LOWER = frozenset(
    {
        "inc", "corp", "ltd", "llc", "plc", "co", "sec", "ipo", "ads", "adrs", "424b4", "10-k", "20-f",
        "10-q", "6-k", "xbrl", "gaap", "ifrs", "non-gaap", "non-ifrs", "total", "net", "revenue",
        "revenues", "income", "assets", "equity", "expense", "expenses", "cash", "flow", "year",
        "years", "ended", "march", "december", "june", "september", "fiscal", "per", "and", "of",
        "the", "in", "for", "from", "to", "as",
    }
)
_ARABIC_YEAR_RE = re.compile(r"(?P<yr>(?:19|20)\d{2})\s*年")
_ZH_YEAR_RE = re.compile(r"(?P<zyr>[一二][零〇一二三四五六七八九]{3})\s*年")
_ARABIC_CLAUSE_RE = re.compile(
    r"(?P<pre>第\s*)?(?P<num>\d{1,5})\s*(?P<let>[A-Za-z])?\s*(?P<unit>[条條章节節款项項期])(?:之(?P<sub>[零〇一二三四五六七八九十百\d]{1,4}))?"
)
_ZH_CLAUSE_RE = re.compile(
    r"(?P<pre>第\s*)?(?P<zh>[零〇一二两兩三四五六七八九十百千万萬]{1,10})\s*(?P<let>[A-Za-z])?\s*(?P<unit>[条條章节節款项項期])(?:之(?P<sub>[零〇一二三四五六七八九十百\d]{1,4}))?"
)
_STRICT_CLAUSE_UNITS = {"条", "條", "章", "节", "節", "期"}
_DIGIT_TO_ZH_CHAR = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}
_ZH_CHAR_TO_DIGIT = {"零": "0", "〇": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}


def _build_subclause_suffixes(sub: str) -> list[str]:
    if not sub:
        return [""]
    forms = [f"之{sub}"]
    if sub.isdigit():
        sub_int = int(sub)
        if 1 <= sub_int <= 999:
            forms.append(f"之{int_to_zh(sub_int)}")
    else:
        sub_int_opt = zh_to_int(sub)
        if sub_int_opt is not None:
            forms.append(f"之{sub_int_opt}")
    return list(dict.fromkeys(forms))


def _build_clause_variants(num: int, let: str, unit: str, sub: str = "") -> list[str]:
    let_up = let.upper() if let else ""
    zh_num = int_to_zh(num)
    units: list[str] = []
    for u in (unit, to_traditional(unit), to_simplified(unit)):
        if u and u not in units:
            units.append(u)
    sub_forms = _build_subclause_suffixes(sub)
    raw_forms: list[str] = []
    for u in units:
        for sf in sub_forms:
            if let_up:
                raw_forms.extend(
                    [
                        f"{num}{let_up}{u}{sf}",
                        f"第{num}{let_up}{u}{sf}",
                        f"第{zh_num}{let_up}{u}{sf}",
                        f"第{zh_num} {let_up} {u}{sf}",
                        f"{zh_num}{let_up}{u}{sf}",
                    ]
                )
            else:
                raw_forms.extend([f"第{num}{u}{sf}", f"{num}{u}{sf}", f"第{zh_num}{u}{sf}"])
    out: list[str] = []
    for form in raw_forms:
        for v in cjk_variants(form):
            if v not in out:
                out.append(v)
    return out


def _build_year_variants(year_str: str) -> list[str]:
    zh_zero = "".join(_DIGIT_TO_ZH_CHAR[ch] for ch in year_str)
    zh_circle = zh_zero.replace("零", "〇")
    return list(dict.fromkeys([f"{year_str}年", f"{year_str}年度", f"{zh_zero}年", f"{zh_zero}年度", f"{zh_circle}年"]))


def _extract_clause_groups(text: str) -> tuple[list[list[str]], str]:
    groups: list[list[str]] = []
    spans: list[tuple[int, int]] = []

    for m in _ARABIC_YEAR_RE.finditer(text):
        groups.append(_build_year_variants(m.group("yr")))
        spans.append(m.span())

    for m in _ZH_YEAR_RE.finditer(text):
        s, e = m.span()
        if any(not (e <= os_ or s >= oe_) for os_, oe_ in spans):
            continue
        yr = "".join(_ZH_CHAR_TO_DIGIT[ch] for ch in m.group("zyr"))
        groups.append(_build_year_variants(yr))
        spans.append((s, e))

    for m in _ARABIC_CLAUSE_RE.finditer(text):
        s, e = m.span()
        if any(not (e <= os_ or s >= oe_) for os_, oe_ in spans):
            continue
        pre = (m.group("pre") or "").strip()
        num = int(m.group("num"))
        let = m.group("let") or ""
        unit = m.group("unit")
        sub = m.group("sub") or ""
        if not pre and unit not in _STRICT_CLAUSE_UNITS:
            continue
        if num <= 0 or num > 99999:
            continue
        groups.append(_build_clause_variants(num, let, unit, sub))
        spans.append((s, e))

    for m in _ZH_CLAUSE_RE.finditer(text):
        pre = (m.group("pre") or "").strip()
        let = m.group("let") or ""
        unit = m.group("unit")
        sub = m.group("sub") or ""
        if not pre and not let:
            continue
        num = zh_to_int(m.group("zh"))
        if num is None or num <= 0 or num > 99999:
            continue
        s, e = m.span()
        if any(not (e <= os_ or s >= oe_) for os_, oe_ in spans):
            continue
        groups.append(_build_clause_variants(num, let, unit, sub))
        spans.append((s, e))

    if not spans:
        return groups, text
    chars = list(text)
    for s, e in spans:
        for idx in range(s, e):
            chars[idx] = " "
    return groups, "".join(chars)


def _extract_book_titles(text: str) -> tuple[list[list[str]], str]:
    groups: list[list[str]] = []
    spans: list[tuple[int, int]] = []
    for m in _BOOK_TITLE_RE.finditer(text):
        raw_title = m.group(1).strip()
        if not raw_title:
            continue
        short = re.sub(r"^中华人民共和国", "", raw_title).strip()
        candidates = [c for c in (short, raw_title) if len(c) >= 2]
        if not candidates:
            continue
        grp: list[str] = []
        for cand in candidates:
            for v in cjk_variants(cand):
                if v not in grp:
                    grp.append(v)
        groups.append(grp)
        spans.append(m.span())
    if not spans:
        return groups, text
    chars = list(text)
    for s, e in spans:
        for idx in range(s, e):
            chars[idx] = " "
    return groups, "".join(chars)


def analyze_query(query: str) -> dict[str, list[Any]]:
    raw_chunks = [p.strip() for p in re.split(r"\s+", query or "") if len(p.strip()) >= 2]
    book_title_groups, pre_cleaned = _extract_book_titles(query or "")
    cleaned = _LEADING_VERB_RE.sub(" ", pre_cleaned)
    for sp in STOP_PHRASES:
        cleaned = cleaned.replace(sp, " ")

    # Match domain synonyms directly on `cleaned` with re.IGNORECASE to avoid Unicode .lower() offset drift.
    synonym_groups: list[list[str]] = []
    syn_spans: list[tuple[int, int]] = []
    for term, syns in sorted(DOMAIN_SYNONYMS.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(re.escape(term), cleaned, flags=re.IGNORECASE):
            s, e = m.span()
            if any(not (e <= os_ or s >= oe_) for os_, oe_ in syn_spans):
                continue
            syn_spans.append((s, e))
            grp = cjk_variants(term)
            for syn in syns:
                for v in cjk_variants(syn):
                    if v not in grp:
                        grp.append(v)
            synonym_groups.append(grp)

    if syn_spans:
        chars = list(cleaned)
        for s, e in syn_spans:
            for idx in range(s, e):
                chars[idx] = " "
        cleaned_wo_syn = "".join(chars)
    else:
        cleaned_wo_syn = cleaned

    clause_groups, cleaned_wo_clauses = _extract_clause_groups(cleaned_wo_syn)

    ascii_terms: list[str] = []
    seen_ascii: set[str] = set()
    ascii_pattern = (
        r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?"
        r"|[A-Za-z0-9][A-Za-z0-9._&+-]*(?:/[A-Za-z0-9][A-Za-z0-9._&+-]*)*)"
    )
    for raw_tok in re.findall(ascii_pattern, cleaned_wo_clauses):
        token = re.sub(r"[.,;:/_-]+$", "", raw_tok)
        low = token.lower()
        if len(token) >= 2 and low not in seen_ascii:
            seen_ascii.add(low)
            ascii_terms.append(token)

    english_phrases: list[str] = []
    for m_ep in _EN_PHRASE_RE.finditer(cleaned_wo_clauses):
        ep = re.sub(r"\s+", " ", m_ep.group(0)).strip(" .,:;")
        words_ep = [w for w in ep.split(" ") if w]
        if len(words_ep) >= 2 and any(w.lower() not in _GENERIC_ASCII_LOWER for w in words_ep) and ep not in english_phrases:
            english_phrases.append(ep)

    cjk_words: list[str] = []
    bigrams: list[str] = []
    stop_pattern = "[" + "".join(sorted(STOP_CHARS)) + "]+"
    for span in re.findall(r"[\u4e00-\u9fff]+", cleaned_wo_clauses):
        for sub in re.split(stop_pattern, span):
            if not sub:
                continue
            if len(sub) >= 2 and sub not in cjk_words:
                cjk_words.append(sub)
            if len(sub) == 1:
                if sub not in bigrams:
                    bigrams.append(sub)
            else:
                for idx in range(len(sub) - 1):
                    bg = sub[idx : idx + 2]
                    if bg not in bigrams:
                        bigrams.append(bg)

    return {
        "raw_chunks": raw_chunks,
        "ascii_terms": ascii_terms,
        "english_phrases": english_phrases,
        "cjk_words": cjk_words,
        "bigrams": bigrams,
        "bigram_groups": [cjk_variants(bg) for bg in bigrams],
        "clause_groups": clause_groups,
        "synonym_groups": synonym_groups,
        "book_title_groups": book_title_groups,
    }


def _ascii_anchor_unit(term: str, fields: list[str]) -> dict[str, Any]:
    if "," in term and re.fullmatch(r"\d[\d,.]+", term):
        plain = term.replace(",", "")
        num_should: list[dict[str, Any]] = [
            {"match_phrase": {"body": {"query": term, "boost": 6.0}}},
            {"match_phrase": {"text": {"query": term, "boost": 5.5}}},
            {"match_phrase": {"body": {"query": plain, "boost": 4.5}}},
            {"match_phrase": {"text": {"query": plain, "boost": 4.0}}},
        ]
        return {"bool": {"should": num_should, "minimum_should_match": 1}}

    if re.fullmatch(r"(?:19|20)\d{2}-\d{2}-\d{2}", term):
        return {
            "bool": {
                "should": [
                    {"match_phrase": {"body": {"query": term, "boost": 5.0}}},
                    {"match_phrase": {"text": {"query": term, "boost": 4.5}}},
                ],
                "minimum_should_match": 1,
            }
        }

    is_short_code = len(term) <= 6 and (term.isupper() or any(ch.isdigit() for ch in term))
    if any(ch in term for ch in "/-+&"):
        unit_should: list[dict[str, Any]] = [
            {"match_phrase": {"body": {"query": term, "boost": 4.5}}},
            {"match_phrase": {"text": {"query": term, "boost": 4.0}}},
            {"match_phrase": {"defs": {"query": term, "boost": 4.5}}},
            {"match_phrase": {"title": {"query": term, "boost": 5.5}}},
            {"match_phrase": {"ax_path": {"query": term, "boost": 5.0}}},
        ]
        if is_short_code:
            unit_should.append({"wildcard": {"title": {"value": f"*{term}*", "case_insensitive": True, "boost": 6.0}}})
            unit_should.append({"wildcard": {"ax_path": {"value": f"*{term}*", "case_insensitive": True, "boost": 5.5}}})
        if "/" in term:
            parts = [p.strip() for p in term.split("/") if p.strip()]
            if len(parts) >= 2 and all(len(p) >= 2 and re.search(r"[A-Za-z]", p) for p in parts):
                for part in parts:
                    unit_should.append({"match_phrase": {"body": {"query": part, "boost": 2.8}}})
                    unit_should.append({"match_phrase": {"text": {"query": part, "boost": 2.4}}})
        return {"bool": {"should": unit_should, "minimum_should_match": 1}}

    should_list: list[dict[str, Any]] = [
        {"multi_match": {"query": term, "fields": [*fields, "ax_path^1.5"], "lenient": True, "boost": 4.0}},
    ]
    if is_short_code:
        should_list.append({"wildcard": {"title": {"value": f"*{term}*", "case_insensitive": True, "boost": 6.5}}})
        should_list.append({"wildcard": {"ax_path": {"value": f"*{term}*", "case_insensitive": True, "boost": 6.0}}})
    return {"bool": {"should": should_list, "minimum_should_match": 1}}


def _phrase_group_unit(
    variants: list[str],
    boost: float = 4.5,
    path_year: str | None = None,
    include_title_wildcards: bool = False,
) -> dict[str, Any]:
    unit_should: list[dict[str, Any]] = []
    for v in variants[:14]:
        unit_should.append({"match_phrase": {"body": {"query": v, "boost": boost}}})
        unit_should.append({"match_phrase": {"text": {"query": v, "boost": boost - 0.5}}})
        unit_should.append({"match_phrase": {"title": {"query": v, "boost": boost - 0.5}}})
        if include_title_wildcards:
            unit_should.append({"wildcard": {"title": {"value": f"*{v}*", "case_insensitive": True, "boost": boost - 0.5}}})
            unit_should.append({"wildcard": {"ax_path": {"value": f"*{v}*", "case_insensitive": True, "boost": boost - 1.0}}})
    if path_year:
        unit_should.append({"wildcard": {"ax_path": {"value": f"*{path_year}*", "case_insensitive": True, "boost": boost - 1.0}}})
    return {"bool": {"should": unit_should, "minimum_should_match": 1}}


def _bigram_unit(variants: list[str], fields: list[str]) -> dict[str, Any]:
    if len(variants[0]) == 1:
        if len(variants) == 1:
            return {"multi_match": {"query": variants[0], "fields": fields, "lenient": True, "boost": 1.0}}
        return {
            "bool": {
                "should": [{"multi_match": {"query": v, "fields": fields, "lenient": True, "boost": 1.0}} for v in variants],
                "minimum_should_match": 1,
            }
        }
    unit_should: list[dict[str, Any]] = []
    for v in variants:
        if len(v) < 2:
            continue
        unit_should.append({"match_phrase": {"body": {"query": v, "boost": 2.0}}})
        unit_should.append({"match_phrase": {"text": {"query": v, "boost": 1.8}}})
        unit_should.append({"match_phrase": {"title": {"query": v, "boost": 2.0}}})
    return {"bool": {"should": unit_should, "minimum_should_match": 1}}


def _resolve_exclude_format_prefixes(exclude_format_prefixes: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if exclude_format_prefixes is not None:
        return tuple(p.strip() for p in exclude_format_prefixes if p and p.strip())
    env_val = os.environ.get("VERICORPUS_EXCLUDE_FORMAT_PREFIXES", "").strip()
    if not env_val:
        return ()
    return tuple(p.strip() for p in env_val.split(",") if p.strip())


def build_search_body(
    query: str,
    limit: int = 5,
    scope: str = "docs",
    require_anchors: bool = True,
    require_bigrams: bool = True,
    include_body: bool = False,
    exclude_format_prefixes: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    info = analyze_query(query)
    ascii_terms = info["ascii_terms"]
    english_phrases = info.get("english_phrases") or []
    cjk_words = info["cjk_words"]
    bigram_groups = info["bigram_groups"]
    clause_groups = info["clause_groups"]
    synonym_groups = info["synonym_groups"]
    book_title_groups = info.get("book_title_groups") or []
    raw_chunks = info["raw_chunks"]

    doc_fields = ["body^2", "text^1.8", "defs^3", "title"]
    must_clauses: list[dict[str, Any]] = []
    should: list[dict[str, Any]] = [
        {"multi_match": {"query": query, "fields": ["body", "text", "defs^2"], "type": "most_fields", "lenient": True, "boost": 2.0}},
        {"match_phrase": {"body": {"query": query, "boost": 5.0}}},
        {"match_phrase": {"text": {"query": query, "boost": 4.5}}},
    ]

    for ep in english_phrases[:6]:
        should.append({"match_phrase": {"body": {"query": ep, "boost": 8.5}}})
        should.append({"match_phrase": {"text": {"query": ep, "boost": 7.5}}})
        should.append({"match_phrase": {"title": {"query": ep, "boost": 8.0}}})

    anchor_clauses: list[dict[str, Any]] = []
    entity_all: list[dict[str, Any]] = []
    entity_specific: list[dict[str, Any]] = []
    ticker_clauses: list[dict[str, Any]] = []
    for w in ascii_terms[:10]:
        u = _ascii_anchor_unit(w, doc_fields)
        anchor_clauses.append(u)
        if not re.fullmatch(r"(?:19|20)\d{2}(?:-\d{2}-\d{2})?", w):
            entity_all.append(u)
            if w.lower() not in _GENERIC_ASCII_LOWER:
                entity_specific.append(u)
            if 2 <= len(w) <= 5 and w.isalpha() and w.isupper() and w not in _GENERIC_UPPER_TERMS:
                ticker_clauses.append(u)
    entity_ascii = entity_specific or entity_all

    statute_clause = False
    for cg in clause_groups[:4]:
        m_yr = re.match(r"^((?:19|20)\d{2})年$", cg[0]) if cg else None
        if cg and any(u in cg[0] for u in ("条", "條", "款", "项", "項", "期")):
            statute_clause = True
        u = _phrase_group_unit(cg, boost=4.8, path_year=m_yr.group(1) if m_yr else None)
        anchor_clauses.append(u)
        should.append(u)
    for sg in synonym_groups[:4]:
        u = _phrase_group_unit(sg, boost=4.5)
        anchor_clauses.append(u)
        should.append(u)

    for btg in book_title_groups[:2]:
        u = _phrase_group_unit(btg[:4], boost=7.0, include_title_wildcards=True)
        if require_anchors:
            must_clauses.append(u)
        should.append(u)

    if anchor_clauses:
        if require_anchors:
            if len(ticker_clauses) == 1:
                must_clauses.append(ticker_clauses[0])
            elif len(ticker_clauses) >= 2:
                # Multi-ticker comparison queries must match any one of the compared tickers per chunk.
                must_clauses.append({"bool": {"should": ticker_clauses, "minimum_should_match": 1}})
            effective_anchor_count = len(anchor_clauses) - max(0, len(ticker_clauses) - 1)
            a_msm = 1 if effective_anchor_count <= 1 else (effective_anchor_count + 1) // 2
            must_clauses.append({"bool": {"should": anchor_clauses, "minimum_should_match": a_msm}})
            if entity_ascii and len(anchor_clauses) > len(entity_ascii):
                e_msm = 1 if (len(entity_ascii) <= 2 or len(ticker_clauses) >= 2) else (len(entity_ascii) + 1) // 2
                must_clauses.append({"bool": {"should": entity_ascii, "minimum_should_match": e_msm}})
        else:
            should.extend(anchor_clauses)

    if bigram_groups:
        bg_clauses = [_bigram_unit(bg_group, doc_fields) for bg_group in bigram_groups[:16]]
        if require_bigrams:
            has_hard_anchor = bool(require_anchors and (anchor_clauses or book_title_groups))
            if len(bg_clauses) <= 2:
                b_msm = len(bg_clauses) if not has_hard_anchor else 1
            elif statute_clause:
                b_msm = max(1, int(len(bg_clauses) * 0.35))
            else:
                ratio = 0.55 if has_hard_anchor else 0.60
                b_msm = max(2, math.ceil(len(bg_clauses) * ratio))
            must_clauses.append({"bool": {"should": bg_clauses, "minimum_should_match": b_msm}})
        else:
            should.extend(bg_clauses)

    if not must_clauses:
        must_clauses.append({"multi_match": {"query": query, "fields": doc_fields, "lenient": True}})

    phrase_candidates: list[str] = []
    for w in (cjk_words + raw_chunks):
        for v in cjk_variants(w):
            if 2 <= len(v) <= 24:
                phrase_candidates.append(v)
    for grp in (book_title_groups + clause_groups + synonym_groups):
        for v in grp:
            if 2 <= len(v) <= 24:
                phrase_candidates.append(v)
    for w in ascii_terms:
        if 2 <= len(w) <= 24:
            phrase_candidates.append(w)

    for kp in list(dict.fromkeys(phrase_candidates))[:18]:
        should.append({"match_phrase": {"body": {"query": kp, "boost": 4.0}}})
        should.append({"match_phrase": {"text": {"query": kp, "boost": 3.5}}})
        should.append({"match_phrase": {"title": {"query": kp, "boost": 4.5}}})

    bool_clause: dict[str, Any] = {
        "must": must_clauses,
        "should": should,
    }
    excl_prefixes = _resolve_exclude_format_prefixes(exclude_format_prefixes)
    if excl_prefixes:
        bool_clause["must_not"] = [{"prefix": {"ax_format": pfx}} for pfx in excl_prefixes]
    if scope == "docs":
        bool_clause["filter"] = [{"terms": {"ax_format": DOC_FORMATS}}]

    source_fields = ["ax_path", "ax_format", "title", "start_line", "end_line", "page", "pdf_pages_total"]
    if include_body:
        source_fields.extend(["body", "section"])

    return {
        "query": {"bool": bool_clause},
        "size": limit,
        "_source": source_fields,
        "fields": ["_passage"],
    }


def search_index(
    base_url: str,
    prefix: str,
    query: str,
    limit: int = 5,
    scope: str = "docs",
    include_body: bool = False,
    exclude_format_prefixes: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """向 XERJ 节点发起单库检索，包含 strict_unknown_fields=false、跨语种缩环与可控兜底放宽。"""
    url = f"{base_url.rstrip('/')}/{prefix}-*/_search?strict_unknown_fields=false&ignore_unavailable=true"

    def _run(require_anchors: bool, require_bigrams: bool = True) -> dict[str, Any]:
        body = build_search_body(
            query,
            limit=limit,
            scope=scope,
            require_anchors=require_anchors,
            require_bigrams=require_bigrams,
            include_body=include_body,
            exclude_format_prefixes=exclude_format_prefixes,
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with compliance._safe_urlopen(req, timeout=20, allow_localhost_http=True) as r:
            return json.loads(r.read().decode("utf-8"))

    raw = _run(True, True)
    hits = raw.get("hits", {}).get("hits", [])
    relaxed = False
    info = analyze_query(query)
    has_anchors = bool(info["ascii_terms"] or info["clause_groups"] or info["synonym_groups"] or info.get("book_title_groups"))

    alpha_ascii_cnt = sum(1 for t in info["ascii_terms"] if re.search(r"[A-Za-z]{2,}", t))
    allow_bigram_drop = bool(
        info["synonym_groups"]
        or any(("/" in t or "-" in t) for t in info["ascii_terms"])
        or (not info.get("book_title_groups") and alpha_ascii_cnt >= 3)
    )

    if not hits and allow_bigram_drop and info["bigrams"]:
        raw = _run(True, False)
        hits = raw.get("hits", {}).get("hits", [])

    if (
        not hits
        and has_anchors
        and info["bigrams"]
        and not info["clause_groups"]
        and not info.get("book_title_groups")
        and len(info["ascii_terms"]) < 2
        and allow_bigram_drop
    ):
        relaxed = True
        raw = _run(False, True)
        hits = raw.get("hits", {}).get("hits", [])

    cleaned_hits: list[dict[str, Any]] = []
    for item in hits:
        src = item.get("_source") or {}
        passages = (item.get("fields") or {}).get("_passage") or []
        snip = str(passages[0].get("text") if isinstance(passages[0], dict) else passages[0]) if passages else ""
        raw_body = str(src.get("body") or "")
        snip_src = snip or raw_body if include_body else snip
        entry: dict[str, Any] = {
            "path": str(src.get("ax_path") or ""),
            "format": str(src.get("ax_format") or ""),
            "title": str(src.get("title") or ""),
            "page": src.get("page"),
            "pdf_pages_total": src.get("pdf_pages_total"),
            "start_line": src.get("start_line"),
            "score": round(float(item.get("_score") or 0.0), 3),
            "snippet": re.sub(r"\s+", " ", snip_src).strip()[:280],
        }
        if include_body:
            entry["end_line"] = src.get("end_line")
            entry["section"] = str(src.get("section") or "")
            entry["body"] = raw_body
        cleaned_hits.append(entry)

    return {
        "query": query,
        "took_ms": raw.get("took", 0),
        "total": (raw.get("hits") or {}).get("total", {}).get("value", 0),
        "relaxed": relaxed,
        "hits": cleaned_hits,
    }
