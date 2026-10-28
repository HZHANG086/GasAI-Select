#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from typing import List, Dict, Any

import streamlit as st

from retriever import retrieve_topk
from utils import generate_recommendation_summary, load_products, norm


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "data/synthetic_products.json")


@st.cache_data
def cached_load_products(path: str) -> List[Dict[str, Any]]:
    return load_products(path)


def render_candidates_table(candidates: List[Dict[str, Any]]) -> None:
    if not candidates:
        st.info("未找到足够匹配产品，请尝试放宽条件或更换关键词。")
        return

    rows = []
    for c in candidates:
        rows.append(
            {
                "product_name": norm(c.get("product_name")),
                "brand_name": norm(c.get("brand_name")),
                "model": norm(c.get("model")),
                "category_hint": norm(c.get("category_hint")),
                "price_text": norm(c.get("price_text")),
                "domestic_or_imported": norm(c.get("domestic_or_imported")),
                "application_industries": " | ".join(c.get("application_industries") or []),
                "score": c.get("score", 0),
            }
        )
    st.dataframe(rows, use_container_width=True)


def render_sources(candidates: List[Dict[str, Any]]) -> None:
    urls = []
    seen = set()
    for c in candidates:
        u = norm(c.get("url"))
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    if not urls:
        st.write("无可展示链接")
        return
    for idx, u in enumerate(urls, 1):
        st.code(u, language=None)


def render_details(candidates: List[Dict[str, Any]]) -> None:
    for i, c in enumerate(candidates, 1):
        title = norm(c.get("product_name")) or norm(c.get("title")) or f"候选产品 {i}"
        with st.expander(f"{i}. {title}"):
            st.write(f"**company_name**: {norm(c.get('company_name')) or '-'}")
            st.write(f"**principle**: {norm(c.get('principle')) or '-'}")
            st.write(f"**detection_range_text**: {norm(c.get('detection_range_text')) or '-'}")
            st.write(f"**accuracy_text**: {norm(c.get('accuracy_text')) or '-'}")
            st.write("**匹配依据**: " + "、".join(c.get("match_reasons") or []))
            facts = c.get("core_facts") or []
            if facts:
                st.write("**core_facts**:")
                for x in facts[:8]:
                    st.write(f"- {x}")
            else:
                st.write("**core_facts**: -")


def main() -> None:
    st.set_page_config(page_title="GasAI-Select Demo", layout="wide")
    st.title("GasAI-Select Demo / 仪器智能检索与推荐原型")

    with st.sidebar:
        st.header("配置")
        top_k = st.slider("返回候选数量 Top-K", min_value=3, max_value=12, value=6, step=1)
        st.caption("离线演示模式：不需要 API 密钥，不发送网络请求。")

    data_path = DEFAULT_DATA_PATH
    st.info("全部产品、品牌、价格与参数均为合成数据，仅用于演示检索流程。")
    products = cached_load_products(data_path)
    st.caption(f"已加载产品数据: {len(products)} 条")

    query = st.text_input(
        "请输入选型需求",
        placeholder="例如：推荐适合石油化工场景的便携式气相色谱仪",
    )
    run_btn = st.button("开始推荐", type="primary")

    if run_btn:
        if not query.strip():
            st.warning("请先输入需求。")
            st.stop()

        candidates = retrieve_topk(products, query, top_k=top_k)
        summary = generate_recommendation_summary(query, candidates)

        st.subheader("A. 候选产品表格")
        render_candidates_table(candidates)

        st.subheader("B. 规则生成的候选说明")
        st.markdown(summary)

        st.subheader("C. 合成记录标识（示例地址）")
        render_sources(candidates)

        st.subheader("D. 单个产品详情展开")
        render_details(candidates)


if __name__ == "__main__":
    main()
