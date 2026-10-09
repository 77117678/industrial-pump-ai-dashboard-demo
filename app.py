# -*- coding: utf-8 -*-
"""605A101 干燥酸泵 AI Agent 网页驾驶舱（本地离线回放版）

本程序只读取项目 reports 目录中的 CSV/TXT 结果，不连接 PLC/SCADA，不向设备写入任何指令。
"""
from pathlib import Path
from datetime import datetime
import re
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(
    page_title="605A101 干燥酸泵 AI Agent 驾驶舱",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

# 已知结果文件名；如果文件名有轻微差异，也会尝试在 reports 目录中匹配。
FILE_CANDIDATES = {
    "decision": [
        "realtime_agent_decision_replay_v12.csv",
        "realtime_agent_decision_replay_v12_1.csv",
        "realtime_agent_decision_replay_v12_2.csv",
    ],
    "latest": ["realtime_agent_v1_latest.csv"],
    "realtime_events": ["realtime_agent_v1_events.csv"],
    "anomalies": ["anomaly_events_v3.csv"],
    "health": ["health_diagnosis_v1.csv"],
    "energy_opportunities": ["energy_saving_opportunity_v1.csv"],
    "acceptance_checks": ["realtime_agent_decision_acceptance_v12_1_checks.csv"],
}

FALLBACK_SUMMARY = {
    "health_score": 93.26,
    "health_level": "健康",
    "historical_anomalies": 44,
    "historical_process_events": 39,
    "historical_electrical_candidates": 5,
    "realtime_electrical_events": 5,
    "realtime_energy_events": 69,
    "historical_energy_opportunities": 171,
    "theoretical_saving_kwh": 60.3,
    "reference_unit_energy": 0.088073,
}


def locate_file(key: str):
    """从 reports 目录查找指定输出；不存在时返回 None。"""
    if not REPORTS_DIR.exists():
        return None
    for name in FILE_CANDIDATES.get(key, []):
        p = REPORTS_DIR / name
        if p.exists():
            return p
    patterns = {
        "decision": ["*decision*replay*v12*.csv"],
        "latest": ["*realtime*latest*.csv"],
        "realtime_events": ["*realtime*events*.csv"],
        "anomalies": ["*anomaly*events*v3*.csv"],
        "health": ["*health*diagnosis*.csv"],
        "energy_opportunities": ["*energy*saving*opportunity*.csv"],
        "acceptance_checks": ["*decision*acceptance*v12_1*checks*.csv"],
    }
    for pattern in patterns.get(key, []):
        matches = sorted(REPORTS_DIR.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
    return None


@st.cache_data(show_spinner=False)
def load_csv(path_string: str):
    """兼容常见中文 CSV 编码。"""
    path = Path(path_string)
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding, low_memory=False)
        except Exception as exc:  # 尝试下一种编码
            last_error = exc
    raise ValueError(f"读取文件失败：{path.name}。最后错误：{last_error}")


def get_df(key):
    path = locate_file(key)
    if not path:
        return None, None, None
    try:
        return path, load_csv(str(path)), None
    except Exception as exc:
        return path, None, str(exc)


def column_by_keywords(df, keywords, exclude=None):
    if df is None or df.empty:
        return None
    exclude = exclude or []
    cols = [str(c) for c in df.columns]
    # 优先匹配完整字段名，再按包含关键词匹配。
    for kw in keywords:
        for col in cols:
            if col.strip().lower() == kw.strip().lower() and col not in exclude:
                return col
    for kw in keywords:
        for col in cols:
            if kw.lower() in col.lower() and col not in exclude:
                return col
    return None


def time_column(df):
    return column_by_keywords(df, ["时间", "日期", "timestamp", "datetime", "time"])


def parse_time_series(df, col):
    if df is None or col is None:
        return None
    return pd.to_datetime(df[col], errors="coerce")


def latest_row(df, time_col=None):
    if df is None or df.empty:
        return None
    result = df.copy()
    tc = time_col or time_column(result)
    if tc:
        parsed = pd.to_datetime(result[tc], errors="coerce")
        result = result.assign(_parsed_time=parsed).sort_values("_parsed_time")
        result = result.drop(columns=["_parsed_time"])
    return result.iloc[-1]


def to_number(value):
    try:
        n = pd.to_numeric(value, errors="coerce")
        return None if pd.isna(n) else float(n)
    except Exception:
        return None


def fmt(value, digits=2, suffix=""):
    n = to_number(value)
    if n is None:
        return "暂无数据"
    return f"{n:,.{digits}f}{suffix}"


def find_decision_column(df):
    return column_by_keywords(df, ["稳定决策", "最终决策", "决策", "decision"])


def find_priority_column(df):
    return column_by_keywords(df, ["稳定优先级", "最终优先级", "优先级", "priority"])


def metric_value(df, keywords, default=None):
    if df is None or df.empty:
        return default
    row = latest_row(df)
    col = column_by_keywords(df, keywords)
    if col is None:
        return default
    return row.get(col, default)


def load_text_report():
    if not REPORTS_DIR.exists():
        return None
    candidates = sorted(REPORTS_DIR.glob("*decision*acceptance*v12_1*report*.txt"),
                        key=lambda x: x.stat().st_mtime, reverse=True)
    if not candidates:
        candidates = sorted(REPORTS_DIR.glob("*acceptance*report*.txt"),
                            key=lambda x: x.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return candidates[0].name, candidates[0].read_text(encoding=enc)
        except Exception:
            continue
    return candidates[0].name, "报告文件存在，但暂时无法按常见编码读取。"


DATA = {}
for _key in FILE_CANDIDATES:
    DATA[_key] = get_df(_key)

# ------- 侧边栏 -------
with st.sidebar:
    st.title("🏭 泵 AI 驾驶舱")
    st.caption("605A101 干燥酸泵 · 离线回放原型")
    st.divider()
    st.markdown("**运行模式**")
    st.success("本地文件回放")
    st.warning("尚未连接 PLC / SCADA；不控制设备。")
    st.markdown("**数据目录**")
    st.code(str(REPORTS_DIR), language=None)
    if st.button("🔄 重新读取数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("提示：把现有分析脚本生成的 CSV/TXT 放在项目 reports 文件夹内。")

# ------- 页面标题 -------
st.title("605A101 干燥酸泵 AI Agent 驾驶舱")
st.caption("本地历史数据分析 · 异常事件 · 节能机会 · 健康趋势 · 决策回放")
st.info(
    "当前是离线驾驶舱：展示本机 reports 文件夹中的分析结果。页面不会直接读取 PLC/SCADA，也不会向泵发送控制指令。"
)

# DataFrames
replay_path, replay_df, replay_err = DATA["decision"]
latest_path, latest_df, latest_err = DATA["latest"]
rt_events_path, rt_events_df, rt_events_err = DATA["realtime_events"]
anomaly_path, anomaly_df, anomaly_err = DATA["anomalies"]
health_path, health_df, health_err = DATA["health"]
energy_path, energy_df, energy_err = DATA["energy_opportunities"]
checks_path, checks_df, checks_err = DATA["acceptance_checks"]

# KPI 优先使用文件结果，缺少文件时显示已完成的历史项目汇总，并明确属于历史汇总值。
health_score = metric_value(health_df, ["健康评分", "健康分数", "健康分", "health_score"], FALLBACK_SUMMARY["health_score"])
health_level = metric_value(health_df, ["设备健康", "健康等级", "健康状态", "health_level"], FALLBACK_SUMMARY["health_level"])
if health_df is not None and not health_df.empty:
    health_count = len(health_df)
else:
    health_count = 0

electric_events_count = len(rt_events_df) if rt_events_df is not None else FALLBACK_SUMMARY["realtime_electrical_events"] + FALLBACK_SUMMARY["realtime_energy_events"]
if rt_events_df is not None and not rt_events_df.empty:
    type_col = column_by_keywords(rt_events_df, ["事件类型", "类别", "event_type", "类型"])
    if type_col:
        type_values = rt_events_df[type_col].astype(str)
        electrical_count = int(type_values.str.contains("电气|电流|控制|electrical", case=False, regex=True).sum())
        energy_count = int(type_values.str.contains("节能|能耗|energy|低流量", case=False, regex=True).sum())
        if electrical_count == 0 and energy_count == 0:
            electrical_count = FALLBACK_SUMMARY["realtime_electrical_events"]
            energy_count = FALLBACK_SUMMARY["realtime_energy_events"]
    else:
        # 该文件通常含电气和节能事件；用事件类型无法区分时回退已完成的分类统计。
        electrical_count = FALLBACK_SUMMARY["realtime_electrical_events"]
        energy_count = FALLBACK_SUMMARY["realtime_energy_events"]
else:
    electrical_count = FALLBACK_SUMMARY["realtime_electrical_events"]
    energy_count = FALLBACK_SUMMARY["realtime_energy_events"]

if anomaly_df is not None:
    historical_anomaly_count = len(anomaly_df)
else:
    historical_anomaly_count = FALLBACK_SUMMARY["historical_anomalies"]
if energy_df is not None:
    historical_energy_count = len(energy_df)
else:
    historical_energy_count = FALLBACK_SUMMARY["historical_energy_opportunities"]

# 获取最后一条实时判断数据；若回放 CSV 不在 reports，则使用 latest 文件。
last_df = replay_df if replay_df is not None and not replay_df.empty else latest_df
last_row = latest_row(last_df) if last_df is not None else None
last_time_col = time_column(last_df) if last_df is not None else None
last_time = "暂无记录"
if last_row is not None and last_time_col:
    _dt = pd.to_datetime(last_row.get(last_time_col), errors="coerce")
    if not pd.isna(_dt):
        last_time = _dt.strftime("%Y-%m-%d %H:%M:%S")
last_decision_col = find_decision_column(last_df) if last_df is not None else None
last_priority_col = find_priority_column(last_df) if last_df is not None else None
last_decision = str(last_row.get(last_decision_col)) if last_row is not None and last_decision_col else "电气预防性关注（已知项目汇总）"
last_priority = str(last_row.get(last_priority_col)) if last_row is not None and last_priority_col else "低"
flow_col = column_by_keywords(last_df, ["流量m3/h", "流量（m3/h）", "流量", "flow"]) if last_df is not None else None
power_col = column_by_keywords(last_df, ["功率kw", "功率（kw）", "功率", "power"]) if last_df is not None else None
unit_col = column_by_keywords(last_df, ["单位能耗kwh/m3", "单位能耗", "unit_energy"]) if last_df is not None else None
last_flow = last_row.get(flow_col) if last_row is not None and flow_col else 1002.865
last_power = last_row.get(power_col) if last_row is not None and power_col else 88.618
last_unit = last_row.get(unit_col) if last_row is not None and unit_col else 0.088365

k1, k2, k3, k4 = st.columns(4)
k1.metric("设备健康评分", fmt(health_score, 2, " / 100"), str(health_level))
k2.metric("实时 Agent 电气事件", f"{electrical_count}", "历史回放统计")
k3.metric("实时 Agent 节能事件", f"{energy_count}", "历史回放统计")
k4.metric("历史节能候选事件", f"{historical_energy_count}", "估算机会，不等于实际节能")

st.subheader("当前回放位置")
p1, p2, p3, p4 = st.columns(4)
p1.metric("回放时间", last_time)
p2.metric("流量", fmt(last_flow, 3, " m³/h"))
p3.metric("功率", fmt(last_power, 3, " kW"))
p4.metric("单位输送能耗", fmt(last_unit, 6, " kWh/m³"))
st.write(f"**Agent 当前决策：** {last_decision}　　**优先级：** {last_priority}")
st.caption("若页面显示‘已知项目汇总’或使用回退值，表示对应 CSV 当前未找到；请以页面下方‘数据文件状态’中的文件清单为准。")

# ------- Tabs -------
tab_overview, tab_decisions, tab_events, tab_energy, tab_health, tab_files = st.tabs([
    "总览", "决策回放", "异常事件", "节能分析", "健康趋势", "数据文件状态"
])

with tab_overview:
    st.subheader("项目阶段成果")
    a, b, c = st.columns(3)
    with a:
        st.markdown("#### 异常检测")
        st.metric("历史候选异常", historical_anomaly_count)
        st.write("历史分析分类：39 个过程/性能候选事件、5 个电气/控制/数据候选事件。候选异常不等于已确认故障。")
    with b:
        st.markdown("#### Agent 决策逻辑")
        if checks_df is not None and not checks_df.empty:
            st.metric("验收检查记录", len(checks_df))
        else:
            st.metric("V12.1 验收结果", "14 / 14")
        st.write("此前验收结果：14 项通过、0 项未通过。属于代码规则与输出一致性检查。")
    with c:
        st.markdown("#### 节能机会")
        st.metric("历史候选机会", historical_energy_count)
        st.metric("历史理论节能估算", f"约 {FALLBACK_SUMMARY['theoretical_saving_kwh']:.1f} kWh")
        st.write("这是历史数据的理论估算，并非现场实测节能。单位能耗为功率/流量，不等同于泵的真实水力效率。")

    st.subheader("最近决策类别统计")
    if replay_df is not None and not replay_df.empty and find_decision_column(replay_df):
        dc = find_decision_column(replay_df)
        counts = replay_df[dc].fillna("未填写").astype(str).value_counts().rename_axis("决策类别").reset_index(name="记录数")
        counts = counts.head(12)
        fig = px.bar(counts, x="决策类别", y="记录数", title="历史回放中的稳定/候选决策记录数")
        fig.update_layout(xaxis_title="决策类别", yaxis_title="记录数", xaxis_tickangle=-25)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("尚未找到 V12 决策回放 CSV。驾驶舱仍可显示项目已知汇总；将回放 CSV 放入 reports 文件夹后，决策图表会自动启用。")

    st.subheader("工程边界")
    st.warning("当前是离线历史数据驾驶舱，不是已接入工厂的实时监控系统。没有 PLC/SCADA 在线连接、没有自动控制、没有经过现场确认的故障判定或实测节能结论。")

with tab_decisions:
    st.subheader("决策回放明细")
    if replay_df is None or replay_df.empty:
        st.warning("未找到决策回放 CSV。请确认 reports 文件夹中存在 realtime_agent_decision_replay_v12*.csv 文件。")
    else:
        df = replay_df.copy()
        dc = find_decision_column(df)
        pc = find_priority_column(df)
        tc = time_column(df)
        if tc:
            df[tc] = pd.to_datetime(df[tc], errors="coerce")
        if dc:
            options = sorted(df[dc].dropna().astype(str).unique().tolist())
            selected = st.multiselect("筛选决策类别", options=options, default=[])
            if selected:
                df = df[df[dc].astype(str).isin(selected)]
        if pc:
            p_options = [x for x in ["高", "中", "低"] if x in set(df[pc].dropna().astype(str))]
            if p_options:
                selected_p = st.multiselect("筛选优先级", options=p_options, default=[])
                if selected_p:
                    df = df[df[pc].astype(str).isin(selected_p)]
        st.caption(f"筛选后记录：{len(df):,} 条")
        show_df = df.sort_values(tc, ascending=False) if tc else df
        st.dataframe(show_df.head(500), use_container_width=True, hide_index=True)
        st.download_button("下载当前筛选结果 CSV", data=show_df.to_csv(index=False).encode("utf-8-sig"),
                           file_name="pump_ai_decision_replay_filtered.csv", mime="text/csv")

with tab_events:
    st.subheader("实时 Agent 事件与历史候选异常")
    sub1, sub2 = st.tabs(["Realtime Agent 事件", "历史异常候选"])
    with sub1:
        if rt_events_df is not None and not rt_events_df.empty:
            st.caption(f"来源：{rt_events_path.name} · {len(rt_events_df):,} 条")
            st.dataframe(rt_events_df, use_container_width=True, hide_index=True)
            st.download_button("下载 Realtime Agent 事件 CSV", data=rt_events_df.to_csv(index=False).encode("utf-8-sig"),
                               file_name="realtime_agent_events.csv", mime="text/csv")
        else:
            st.info("未找到 realtime_agent_v1_events.csv。按已有项目汇总，电气候选事件 5 个、节能候选事件 69 个；此处的数量是已知汇总，并非本次从文件重新计算。")
    with sub2:
        if anomaly_df is not None and not anomaly_df.empty:
            st.caption(f"来源：{anomaly_path.name} · {len(anomaly_df):,} 条")
            st.dataframe(anomaly_df, use_container_width=True, hide_index=True)
            st.download_button("下载历史异常候选 CSV", data=anomaly_df.to_csv(index=False).encode("utf-8-sig"),
                               file_name="historical_anomaly_candidates.csv", mime="text/csv")
        else:
            st.info("未找到 anomaly_events_v3.csv。已有历史汇总为 44 个候选事件：39 个过程/性能，5 个电气/控制/数据。机械候选为 0 不代表可以保证设备没有机械问题。")

with tab_energy:
    st.subheader("节能机会分析")
    e1, e2, e3 = st.columns(3)
    e1.metric("历史候选节能事件", historical_energy_count)
    e2.metric("理论节能估算", f"约 {FALLBACK_SUMMARY['theoretical_saving_kwh']:.1f} kWh")
    e3.metric("参考单位输送能耗", f"{FALLBACK_SUMMARY['reference_unit_energy']:.6f} kWh/m³")
    st.write("参考范围来自历史运行数据中观测到的低单位能耗流量区间（约 1000–1020 m³/h），不是厂家确认的最佳效率点。估算值不能直接等同于实际节省电量。")
    if energy_df is not None and not energy_df.empty:
        st.caption(f"来源：{energy_path.name} · {len(energy_df):,} 条")
        num_cols = energy_df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            possible_value = column_by_keywords(energy_df, ["理论节能", "节能量", "saving", "kwh"])
            possible_time = time_column(energy_df)
            if possible_value:
                view = energy_df.copy()
                view[possible_value] = pd.to_numeric(view[possible_value], errors="coerce")
                view = view.sort_values(possible_value, ascending=False).head(20)
                st.markdown("**理论节能量较高的前 20 条候选记录**")
                st.dataframe(view, use_container_width=True, hide_index=True)
            else:
                st.dataframe(energy_df.head(100), use_container_width=True, hide_index=True)
        else:
            st.dataframe(energy_df.head(100), use_container_width=True, hide_index=True)
        st.download_button("下载节能机会明细 CSV", data=energy_df.to_csv(index=False).encode("utf-8-sig"),
                           file_name="energy_saving_opportunities.csv", mime="text/csv")
    else:
        st.info("未找到 energy_saving_opportunity_v1.csv。补齐文件后可在本页查看逐事件明细。")

with tab_health:
    st.subheader("设备健康趋势")
    st.metric("最新已知健康评分", fmt(health_score, 2, " / 100"), str(health_level))
    st.caption("健康评分为相对状态指标，不是故障概率，也不是剩余寿命（RUL）。")
    if health_df is not None and not health_df.empty:
        st.caption(f"来源：{health_path.name} · {len(health_df):,} 条")
        hdf = health_df.copy()
        tc = time_column(hdf)
        if tc:
            hdf[tc] = pd.to_datetime(hdf[tc], errors="coerce")
        score_col = column_by_keywords(hdf, ["健康评分", "健康分数", "健康分", "health_score"])
        if score_col:
            hdf[score_col] = pd.to_numeric(hdf[score_col], errors="coerce")
            if tc:
                hdf = hdf.sort_values(tc)
                fig = px.line(hdf, x=tc, y=score_col, markers=True, title="健康评分历史变化")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.line_chart(hdf[score_col])
        st.dataframe(hdf.tail(100), use_container_width=True, hide_index=True)
    else:
        st.info("未找到 health_diagnosis_v1.csv。当前显示的是项目已知最新结果；放入健康诊断 CSV 后即可展示趋势图。")

with tab_files:
    st.subheader("数据文件状态")
    status_rows = []
    labels = {
        "decision": "V12 决策回放",
        "latest": "最新状态快照",
        "realtime_events": "Realtime Agent 事件",
        "anomalies": "历史异常候选",
        "health": "健康诊断趋势",
        "energy_opportunities": "节能机会明细",
        "acceptance_checks": "V12.1 验收明细",
    }
    for key, label in labels.items():
        path, df, err = DATA[key]
        status_rows.append({
            "模块": label,
            "状态": "已读取" if path and df is not None else ("文件存在但读取失败" if path else "未找到"),
            "文件名": path.name if path else "—",
            "记录数": len(df) if df is not None else "—",
            "位置": str(path) if path else str(REPORTS_DIR),
            "错误信息": err or "",
        })
    st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)
    st.markdown("**当前目录建议**")
    st.code(f"{PROJECT_ROOT}\n  ├─ data\\   （原始 Excel 数据）\n  ├─ src\\    （分析脚本）\n  ├─ reports\\（CSV/TXT 分析结果）\n  └─ web_dashboard\\（本网页驾驶舱）", language=None)
    report = load_text_report()
    if report:
        st.markdown(f"**验收报告预览：{report[0]}**")
        st.text_area("报告内容", report[1], height=260)
    else:
        st.info("未检测到 V12.1 验收报告 TXT。验收结果仍可参考此前命令行输出；可把报告文件复制到 reports 目录中。")

st.divider()
st.caption(f"本地离线驾驶舱 · 项目目录：{PROJECT_ROOT} · 页面生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
