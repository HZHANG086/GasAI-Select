#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Any, Dict, List, Tuple

from utils import norm, parse_price_constraint, parse_query_with_llm, price_match_score


CATEGORY_TERMS = [
    "超高效液相色谱仪",
    "高效液相色谱仪",
    "液相色谱仪",
    "气相色谱仪",
    "高光谱仪",
    "近红外光谱仪",
    "拉曼光谱仪",
    "水分测定仪",
    "气体分析仪",
    "气体报警器",
]

FEATURE_TERMS = {
    "便携": ["便携", "手持"],
    "在线": ["在线"],
    "实验室": ["实验室"],
    "机载": ["机载"],
}

ORIGIN_TERMS = {
    "国产": ["国产", "国内"],
    "进口": ["进口", "国外"],
}

INDUSTRY_TERMS = [
    "石油化工",
    "食品",
    "环保",
    "制药",
    "生物制药",
    "农业",
    "林业",
    "能源",
    "室内空气",
    "环境应急",
]


def parse_query(user_query: str) -> Dict[str, Any]:
    q = norm(user_query)
    parsed: Dict[str, Any] = {
        "raw": q,
        "categories": [],
        "features": [],
        "origin": "",
        "industries": [],
        "price": parse_price_constraint(q),
    }

    for c in CATEGORY_TERMS:
        if c in q:
            parsed["categories"].append(c)

    for k, kws in FEATURE_TERMS.items():
        if any(x in q for x in kws):
            parsed["features"].append(k)

    for k, kws in ORIGIN_TERMS.items():
        if any(x in q for x in kws):
            parsed["origin"] = k
            break

    for ind in INDUSTRY_TERMS:
        if ind in q:
            parsed["industries"].append(ind)

    return parsed


def _merge_llm_parsed(rule_parsed: Dict[str, Any], llm_parsed: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(rule_parsed)
    category = norm(llm_parsed.get("category"))
    if category and category not in merged["categories"]:
        merged["categories"].append(category)

    scenario = norm(llm_parsed.get("scenario"))
    if scenario and scenario not in merged["industries"]:
        merged["industries"].append(scenario)

    dom = norm(llm_parsed.get("domestic_or_imported"))
    if dom:
        if "国产" in dom:
            merged["origin"] = "国产"
        elif "进口" in dom:
            merged["origin"] = "进口"

    portable = llm_parsed.get("portable")
    if portable is True and "便携" not in merged["features"]:
        merged["features"].append("便携")
    online = llm_parsed.get("online")
    if online is True and "在线" not in merged["features"]:
        merged["features"].append("在线")

    pmin = llm_parsed.get("price_min")
    pmax = llm_parsed.get("price_max")
    if isinstance(pmin, (int, float)) or isinstance(pmax, (int, float)):
        if isinstance(pmin, (int, float)) and isinstance(pmax, (int, float)):
            merged["price"] = {"type": "range", "min": float(min(pmin, pmax)), "max": float(max(pmin, pmax))}
        elif isinstance(pmin, (int, float)):
            merged["price"] = {"type": "gte", "min": float(pmin), "max": None}
        elif isinstance(pmax, (int, float)):
            merged["price"] = {"type": "lte", "min": None, "max": float(pmax)}

    keywords = llm_parsed.get("keywords") or []
    extra = " ".join([norm(x) for x in keywords if norm(x)])
    if extra:
        merged["raw"] = f"{norm(merged.get('raw'))} {extra}".strip()
    return merged


def _contains_any(text: str, terms: List[str]) -> bool:
    t = norm(text).lower()
    return any(x.lower() in t for x in terms)


def score_record(rec: Dict[str, Any], parsed: Dict[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    product_name = norm(rec.get("product_name"))
    brand_name = norm(rec.get("brand_name"))
    instrument_type_raw = norm(rec.get("instrument_type_raw"))
    category_hint = norm(rec.get("category_hint"))
    search_text = norm(rec.get("search_text"))
    price_text = norm(rec.get("price_text"))
    domestic_or_imported = norm(rec.get("domestic_or_imported"))
    app_inds = " ".join(rec.get("application_industries") or [])

    cats = parsed.get("categories", [])
    if cats and _contains_any(category_hint, cats):
        score += 5
        reasons.append("category_hint命中")

    if cats and _contains_any(product_name, cats):
        score += 4
        reasons.append("product_name命中")

    raw_q = parsed.get("raw", "")
    if brand_name and brand_name in raw_q:
        score += 3
        reasons.append("brand命中")

    if cats and _contains_any(instrument_type_raw, cats):
        score += 3
        reasons.append("instrument_type命中")

    inds = parsed.get("industries", [])
    if inds and _contains_any(app_inds, inds):
        score += 3
        reasons.append("应用行业命中")

    origin = parsed.get("origin", "")
    if origin and origin in domestic_or_imported:
        score += 2
        reasons.append("国产/进口命中")

    # 搜索文本弱匹配
    if raw_q and any(tok for tok in [*cats, *inds] if tok and tok in search_text):
        score += 1
        reasons.append("search_text命中")

    pscore = price_match_score(parsed.get("price", {}), rec)
    if pscore > 0:
        score += pscore
        reasons.append("价格命中")
    elif parsed.get("price", {}).get("type") and parsed.get("price", {}).get("type") != "negotiable":
        # 查询带价格但产品没命中时增加惩罚
        score -= 3

    features = parsed.get("features", [])
    if "便携" in features and rec.get("is_portable") is True:
        score += 2
        reasons.append("便携命中")
    if "在线" in features and rec.get("is_online") is True:
        score += 2
        reasons.append("在线命中")
    if "实验室" in features:
        # 用桌面式近似实验室设备
        if rec.get("is_benchtop") is True:
            score += 2
            reasons.append("实验室(桌面式)命中")
    if "机载" in features and _contains_any(product_name + " " + instrument_type_raw, ["机载"]):
        score += 2
        reasons.append("机载命中")

    # 若 query 没有被结构化解析出任何条件，允许用全文弱匹配兜底
    if not cats and not inds and not origin and not parsed.get("price", {}).get("type"):
        if raw_q and raw_q in (product_name + " " + brand_name + " " + instrument_type_raw + " " + search_text):
            score += 2
            reasons.append("全文兜底命中")

    return score, reasons


def retrieve_topk(products: List[Dict[str, Any]], user_query: str, top_k: int = 8) -> List[Dict[str, Any]]:
    parsed = parse_query(user_query)
    llm_parsed = parse_query_with_llm(user_query)
    if llm_parsed:
        parsed = _merge_llm_parsed(parsed, llm_parsed)
    scored: List[Dict[str, Any]] = []
    recall_added: List[Dict[str, Any]] = []
    for rec in products:
        score, reasons = score_record(rec, parsed)
        if score > 0:
            x = dict(rec)
            x["score"] = score
            x["match_reasons"] = reasons
            scored.append(x)

    # 宽松召回：若强匹配结果不足 3 条，基于 category_hint / search_text 做弱匹配补召回
    if len(scored) < 3:
        raw_q = norm(parsed.get("raw", ""))
        cats = parsed.get("categories", [])
        inds = parsed.get("industries", [])
        weak_terms = [t for t in [*cats, *inds] if t]
        if raw_q:
            weak_terms.append(raw_q)
        if parsed.get("origin"):
            weak_terms.append(parsed["origin"])
        weak_terms = list(dict.fromkeys(weak_terms))  # 去重并保持顺序

        strong_urls = {norm(x.get("url")) for x in scored if norm(x.get("url"))}
        for rec in products:
            rec_url = norm(rec.get("url"))
            if rec_url and rec_url in strong_urls:
                continue

            cat_text = norm(rec.get("category_hint"))
            search_text = norm(rec.get("search_text"))
            weak_hit = any(term and ((term in cat_text) or (term in search_text)) for term in weak_terms)
            if not weak_hit:
                continue

            x = dict(rec)
            x["score"] = 1
            x["match_reasons"] = ["弱匹配补召回"]
            recall_added.append(x)
            if len(scored) + len(recall_added) >= top_k:
                break

        scored.extend(recall_added)

    scored.sort(
        key=lambda r: (
            r.get("score", 0),
            len(" ".join(r.get("core_facts") or [])),
            len(norm(r.get("text_preview"))),
        ),
        reverse=True,
    )

    # 若 query 包含价格约束，优先返回价格命中记录
    if parsed.get("price", {}).get("type"):
        price_hit = [r for r in scored if "价格命中" in (r.get("match_reasons") or [])]
        others = [r for r in scored if "价格命中" not in (r.get("match_reasons") or [])]
        merged = price_hit + others
        return merged[:top_k]

    return scored[:top_k]
