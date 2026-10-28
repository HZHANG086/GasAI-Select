#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from typing import Any, Dict, List, Optional, Tuple


def norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    return ""


def ensure_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [norm(x) for x in v if norm(x)]
    if isinstance(v, str):
        parts = re.split(r"[，,;；、|\n]+", v)
        return [p.strip() for p in parts if p.strip()]
    return []


def load_products(data_path: str) -> List[Dict[str, Any]]:
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    out = []
    for x in data:
        if isinstance(x, dict):
            y = dict(x)
            y["application_industries"] = ensure_list(y.get("application_industries"))
            y["core_facts"] = ensure_list(y.get("core_facts"))
            y["output_info"] = ensure_list(y.get("output_info"))
            out.append(y)
    return out


def _cn_num_to_int(token: str) -> Optional[int]:
    """
    简单中文数字转整数（覆盖常见价格表达：十/二十/五十/一百二十等）
    """
    s = norm(token)
    if not s:
        return None
    digit_map = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100, "千": 1000}

    # 纯单字数字
    if s in digit_map:
        return digit_map[s]

    total = 0
    current = 0
    for ch in s:
        if ch in digit_map:
            current = digit_map[ch]
        elif ch in unit_map:
            u = unit_map[ch]
            if current == 0:
                current = 1
            total += current * u
            current = 0
        else:
            return None
    total += current
    return total if total > 0 else None


def _normalize_cn_price_text(q: str) -> str:
    # 将“十五万/五十万/一百二十万”替换成“15万/50万/120万”
    def repl(m: re.Match) -> str:
        cn = m.group(1)
        v = _cn_num_to_int(cn)
        return f"{v}万" if v is not None else m.group(0)

    return re.sub(r"([零一二两三四五六七八九十百千]+)万", repl, q)


def parse_price_constraint(query: str) -> Dict[str, Any]:
    q = norm(query).replace(" ", "")
    q = _normalize_cn_price_text(q)
    result: Dict[str, Any] = {"type": "", "min": None, "max": None}

    if "面议" in q:
        result["type"] = "negotiable"
        return result

    # 20万到50万 / 20万-50万 / 20-50万
    m = re.search(r"(\d+(?:\.\d+)?)\s*万?\s*(?:到|至|-|~|～)\s*(\d+(?:\.\d+)?)\s*万", q)
    if m:
        lo = float(m.group(1)) * 10000
        hi = float(m.group(2)) * 10000
        result.update({"type": "range", "min": min(lo, hi), "max": max(lo, hi)})
        return result

    # 30万以下 / 50万以上
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(以下|以内|以上|起)", q)
    if m:
        val = float(m.group(1)) * 10000
        flag = m.group(2)
        if flag in {"以下", "以内"}:
            result.update({"type": "lte", "max": val})
        else:
            result.update({"type": "gte", "min": val})
        return result

    return result


def extract_price_range_from_text(price_text: str) -> Tuple[Optional[float], Optional[float]]:
    t = norm(price_text).replace(",", "")
    if not t or "面议" in t:
        return None, None
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None, None
    factor = 1.0
    if "万" in t:
        factor = 10000.0
    elif "亿" in t:
        factor = 100000000.0
    vals = [x * factor for x in nums]
    if len(vals) >= 2 and re.search(r"(?:-|~|～|—|至|到)", t):
        return min(vals[0], vals[1]), max(vals[0], vals[1])
    return vals[0], vals[0]


def price_match_score(query_price: Dict[str, Any], record: Dict[str, Any]) -> int:
    if not query_price.get("type"):
        return 0
    if query_price["type"] == "negotiable":
        return 2 if "面议" in norm(record.get("price_text")) else 0

    lo, hi = extract_price_range_from_text(norm(record.get("price_text")))
    if lo is None:
        return 0

    qtype = query_price["type"]
    qmin = query_price.get("min")
    qmax = query_price.get("max")

    if qtype == "range" and qmin is not None and qmax is not None:
        # 相交就算命中
        return 2 if not (hi < qmin or lo > qmax) else 0
    if qtype == "lte" and qmax is not None:
        return 2 if lo <= qmax else 0
    if qtype == "gte" and qmin is not None:
        return 2 if hi >= qmin else 0
    return 0


def _mock_summary(user_query: str, candidates: List[Dict[str, Any]]) -> str:
    if not candidates:
        return (
            "1. 推荐结果概览\n"
            "- 暂未找到足够匹配的产品，请尝试放宽条件（如去掉价格或国产/进口限制）。\n\n"
            "2. 推荐理由\n"
            "- 当前候选不足，可能是类别词过窄或价格区间过严格。\n\n"
            "3. 候选产品差异\n"
            "- 无可比较候选。\n\n"
            "4. 注意事项\n"
            "- 建议补充应用场景、预算上限和便携/在线需求后再次检索。"
        )

    top = candidates[:3]
    lines = []
    lines.append("1. 推荐结果概览")
    lines.append(f"- 针对需求“{user_query}”，系统筛出 {len(candidates)} 个候选，优先推荐前 {len(top)} 个。")
    for i, c in enumerate(top, 1):
        lines.append(
            f"- Top{i}: {norm(c.get('product_name')) or '未命名产品'}"
            f"（品牌: {norm(c.get('brand_name')) or '未知'}，型号: {norm(c.get('model')) or '未标注'}，价格: {norm(c.get('price_text')) or '未标注'}）"
        )

    lines.append("\n2. 推荐理由")
    lines.append("- 推荐结果优先匹配仪器类别、便携/在线特征、应用行业和价格区间。")
    lines.append("- 对字段完整度高、文本匹配更强的产品给出更高优先级。")

    lines.append("\n3. 候选产品差异")
    lines.append("- 主要差异通常体现在：品牌与型号、价格区间、应用行业覆盖、检测原理与指标描述完整度。")

    lines.append("\n4. 注意事项")
    lines.append("- Demo 检索基于结构化字段与关键词打分，不等同于最终采购建议。")
    lines.append("- 建议结合企业预算、维保能力、认证需求做二次人工筛选。")
    return "\n".join(lines)


def parse_query_with_llm(query: str) -> Optional[Dict[str, Any]]:
    """Offline edition: use the deterministic parser in retriever.py."""
    return None


def generate_recommendation_summary(user_query: str, candidates: List[Dict[str, Any]]) -> str:
    """Generate a deterministic explanation without an external service."""
    return _mock_summary(user_query, candidates)
