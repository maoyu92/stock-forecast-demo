"""A股 TimesFM 预测 Demo - Streamlit 主界面"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import streamlit as st
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json

from data.stock_fetcher import search_stocks, fetch_stock_data, get_stock_name, get_stock_list
from data.multi_fetcher import fetch_multi_factors, get_factor_meta
from data.db import init_db, save_forecast, get_history, get_record_by_id, delete_record, get_stats
from model.timesfm_predictor import get_predictor
from config import HORIZON_OPTIONS, CONTEXT_OPTIONS, FREQUENCY_MAP

FREQ_TO_TIMESFM = {"daily": 0, "weekly": 1, "monthly": 1, "1": 0, "5": 0, "15": 0, "30": 0, "60": 0}
FREQ_LABELS = {"daily": "日线", "weekly": "周线", "monthly": "月线", "1": "1分钟", "5": "5分钟", "15": "15分钟", "30": "30分钟", "60": "60分钟"}

st.set_page_config(page_title="A股 TimesFM 预测", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
.main-header {font-size:2rem;font-weight:bold;color:#1f77b4;text-align:center;padding:1rem 0;}
.metric-card {background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:1rem;border-radius:10px;color:white;text-align:center;}
.stTabs [data-baseweb="tab-list"] {gap:8px;}
</style>
""",
    unsafe_allow_html=True,
)


def init_app():
    init_db()
    if "stock_list" not in st.session_state:
        st.session_state.stock_list = get_stock_list()
    if "factor_mode" not in st.session_state:
        st.session_state.factor_mode = False
    if "selected_preset" not in st.session_state:
        st.session_state.selected_preset = "中国太保"


def generate_echarts_html(
    historical_dates: list,
    historical_values: list,
    forecast_dates: list,
    forecast_values: list,
    forecast_quantiles: list = None,
    stock_name: str = "",
    frequency: str = "daily",
) -> str:
    hist_len = min(len(historical_dates), 120)
    hist_display_dates = historical_dates[-hist_len:]
    hist_display_values = [round(v, 2) for v in historical_values[-hist_len:]]
    forecast_display = [None] * (hist_len - 1) + [round(historical_values[-1], 2)] + [round(v, 2) for v in forecast_values]
    hist_line = [round(v, 2) for v in historical_values[-hist_len:]] + [None] * len(forecast_values)
    x_labels = hist_display_dates + forecast_dates

    confidence_upper = []
    confidence_lower = []
    if forecast_quantiles is not None:
        q = np.array(forecast_quantiles)
        if q.ndim == 2 and q.shape[1] >= 3:
            lower_idx = max(0, q.shape[1] // 10)
            upper_idx = min(q.shape[1] - 1, q.shape[1] * 9 // 10)
            confidence_lower = [None] * (hist_len - 1) + [round(historical_values[-1], 2)] + [round(float(v), 2) for v in q[:, lower_idx].tolist()]
            confidence_upper = [None] * (hist_len - 1) + [round(historical_values[-1], 2)] + [round(float(v), 2) for v in q[:, upper_idx].tolist()]
    if not confidence_lower:
        confidence_lower = [None] * len(forecast_display)
        confidence_upper = [None] * len(forecast_display)

    freq_label = {"daily": "日线", "weekly": "周线", "monthly": "月线",
                  "1": "1分钟", "5": "5分钟", "15": "15分钟", "30": "30分钟", "60": "60分钟"}.get(frequency, frequency)

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
</head>
<body>
<div id="chart" style="width:100%;height:500px;"></div>
<script>
var chart = echarts.init(document.getElementById('chart'));
var option = {{
  title: {{ text: '{stock_name} - {freq_label} TimesFM 预测', left: 'center', textStyle: {{ fontSize: 16 }} }},
  tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
  legend: {{ data: ['历史数据','预测值','置信区间'], top: 30 }},
  grid: {{ left: '3%', right: '4%', bottom: '3%', containLabel: true }},
  xAxis: {{ type: 'category', data: {json.dumps(x_labels, ensure_ascii=False)}, axisLabel: {{ rotate: 45, fontSize: 10, formatter: function(value) {{ return value.length > 10 ? value.substring(5,16) : value; }} }} }},
  yAxis: {{ type: 'value', name: '价格', scale: true }},
  dataZoom: [{{ type:'inside', start:0, end:100 }}, {{ type:'slider', start:0, end:100 }}],
  series: [
    {{ name:'历史数据', type:'line', data:{json.dumps(hist_line)}, smooth:true, lineStyle:{{ color:'#5470c6', width:2 }}, showSymbol:false }},
    {{ name:'预测值', type:'line', data:{json.dumps(forecast_display)}, smooth:true, lineStyle:{{ color:'#ee6666', width:3, type:'dashed' }}, symbol:'circle', symbolSize:8 }},
    {{ name:'置信区间', type:'line', data:{json.dumps(confidence_upper)}, lineStyle:{{ opacity:0 }}, stack:'confidence', symbol:'none' }},
    {{ name:'置信区间', type:'line', data:{json.dumps(confidence_lower)}, lineStyle:{{ opacity:0 }}, areaStyle:{{ color:'rgba(238,102,102,0.15)', origin:'auto' }}, stack:'confidence', symbol:'none' }}
  ]
}};
chart.setOption(option);
window.addEventListener('resize', function() {{ chart.resize(); }});
</script>
</body>
</html>
"""


@st.cache_resource
def init_model():
    predictor = get_predictor()
    predictor.load_model()
    return predictor


def render_sidebar():
    with st.sidebar:
        st.header("⚙️ 预测配置")
        st.subheader("🔍 选择股票")
        search_input = st.text_input("输入股票代码或名称", value="", placeholder="如: 贵州茅台 / 600519")
        selected_stock = None
        if search_input:
            results = search_stocks(search_input, limit=10)
            if results:
                options = [f"{r['code']} - {r['name']}" for r in results]
                selected = st.selectbox("搜索结果", options)
                if selected:
                    code, name = selected.split(" - ", 1)
                    selected_stock = {"code": code, "name": name}
            else:
                st.warning("未找到匹配股票")
        else:
            hot_stocks = [
                ("000001", "平安银行"), ("600519", "贵州茅台"), ("000858", "五粮液"),
                ("601318", "中国平安"), ("600036", "招商银行"), ("000333", "美的集团"),
                ("600900", "长江电力"), ("601888", "中国中免"), ("300750", "宁德时代"),
                ("002594", "比亚迪"), ("688981", "中芯国际"), ("601398", "工商银行"),
            ]
            options = [f"{c} - {n}" for c, n in hot_stocks]
            selected = st.selectbox("热门股票", options)
            if selected:
                code, name = selected.split(" - ", 1)
                selected_stock = {"code": code, "name": name}

        st.divider()
        with st.expander("🧩 多因子模式（TimesFM 3.0）", expanded=True):
            st.session_state.factor_mode = st.toggle("启用多因子", value=st.session_state.factor_mode)
            if st.session_state.factor_mode:
                preset_name = st.selectbox(
                    "快速预设",
                    ["中国太保", "贵州茅台", "五粮液", "宁德时代", "比亚迪"],
                    index=0,
                )
                st.session_state.selected_preset = preset_name
                meta = get_factor_meta(preset_name)
                if meta:
                    st.caption("默认因子组合：")
                    for f in meta["factors"]:
                        st.write(f"- {f['label']} ({f['code']})")
                else:
                    st.warning("未找到预设，将回退到单标的")
            else:
                st.session_state.selected_preset = selected_stock["code"] if selected_stock else ""

        st.divider()
        st.subheader("📊 数据频率")
        freq_label = st.selectbox("选择K线周期", list(FREQUENCY_MAP.keys()), index=0)
        frequency = FREQUENCY_MAP[freq_label]
        st.divider()
        st.subheader("🔮 预测参数")
        horizon = st.selectbox("预测步长", HORIZON_OPTIONS, index=0)
        context_len = st.selectbox("上下文长度", CONTEXT_OPTIONS, index=2)
        if frequency in ["1", "5", "15", "30", "60"]:
            st.info(f"💡 分钟数据建议上下文 ≤ 512，当前: {context_len}")
        return selected_stock, frequency, horizon, context_len


def main():
    init_app()
    st.markdown('<div class="main-header">📈 A股 TimesFM 预测 Demo</div>', unsafe_allow_html=True)
    st.caption("基于 Google TimesFM 3.0 多因子时间序列预测模型")
    selected_stock, frequency, horizon, context_len = render_sidebar()
    tab_predict, tab_history, tab_about = st.tabs(["🔮 预测", "📋 历史记录", "ℹ️ 关于"])

    with tab_predict:
        if selected_stock is None:
            st.info("👈 请在左侧选择一只股票")
            return
        st.subheader(f"📊 {selected_stock['name']} ({selected_stock['code']})")

        if st.button("🚀 开始预测", type="primary", use_container_width=True):
            with st.spinner("正在获取股票数据..."):
                if frequency in ["1", "5", "15", "30", "60"]:
                    start = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
                else:
                    days_back = max(context_len * 2, 365)
                    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

                if st.session_state.factor_mode:
                    preset_name = st.session_state.selected_preset or "中国太保"
                    multi_df = fetch_multi_factors(
                        symbol=preset_name,
                        period=frequency,
                        start_date=start,
                    )
                    if multi_df.empty:
                        st.error("❌ 多因子数据获取失败，请检查预设或频率")
                        st.stop()
                    st.success(f"✅ 多因子数据获取成功: {multi_df.shape[1]} 个序列 × {multi_df.shape[0]} 步")
                    selected_stock = selected_stock or {"code": multi_df.columns[0], "name": multi_df.columns[0]}
                    dates = multi_df.index.to_series().dt.strftime('%Y-%m-%d %H:%M' if frequency in ['1','5','15','30','60'] else '%Y-%m-%d').tolist()
                    factor_names = multi_df.columns.tolist()
                else:
                    df = fetch_stock_data(
                        symbol=selected_stock["code"],
                        period=frequency,
                        start_date=start,
                    )
                    if df.empty:
                        st.error("❌ 获取数据失败，请检查股票代码或稍后重试")
                        st.stop()
                    st.success(f"✅ 获取到 {len(df)} 条 {FREQ_LABELS.get(frequency, frequency)} 数据")
                    multi_df = None
                    values = df["close"].values.astype(np.float32)
                    dates = df["date"].dt.strftime('%Y-%m-%d %H:%M' if frequency in ['1','5','15','30','60'] else '%Y-%m-%d').tolist()
                    factor_names = []

            context_len_actual = context_len
            if multi_df is not None:
                if len(multi_df) < context_len:
                    st.warning(f"⚠️ 多因子数据不足 {context_len} 步，使用全部 {len(multi_df)} 步")
                    context_len_actual = len(multi_df)
            else:
                if len(values) < context_len:
                    st.warning(f"⚠️ 数据不足 {context_len} 条，使用全部 {len(values)} 条作为上下文")
                    context_len_actual = len(values)

            progress_bar = st.progress(0, text="加载模型...")

            try:
                predictor = init_model()
                progress_bar.progress(30, text="执行预测...")

                if multi_df is not None:
                    target_col = str(multi_df.columns[0])
                    result = predictor.predict(
                        multi_df,
                        target_col=target_col,
                        horizon=horizon,
                        context_len=context_len_actual,
                        return_quantiles=True,
                    )
                else:
                    result = predictor.predict_with_metrics(
                        values[-context_len_actual:],
                        horizon=horizon,
                        freq=FREQ_TO_TIMESFM.get(frequency, 0),
                    )
                progress_bar.progress(70, text="生成图表...")

                last_date = pd.to_datetime(dates[-1])
                if frequency in ['1', '5', '15', '30', '60']:
                    delta = int(frequency)
                    forecast_dates = [(last_date + timedelta(minutes=delta * (i + 1))).strftime('%Y-%m-%d %H:%M') for i in range(horizon)]
                else:
                    days_map = {"daily": 1, "weekly": 7, "monthly": 30}
                    delta = days_map.get(frequency, 1)
                    forecast_dates = [(last_date + timedelta(days=delta * (i + 1))).strftime('%Y-%m-%d') for i in range(horizon)]

                last_value = float(result["last_value"])
                pred_change = (float(result["forecast"][-1]) - last_value) / (abs(last_value) if last_value != 0 else 1) * 100

                record_id = save_forecast(
                    stock_code=selected_stock["code"],
                    stock_name=selected_stock["name"],
                    frequency=FREQ_LABELS.get(frequency, frequency),
                    horizon=horizon,
                    context_len=context_len_actual,
                    historical_dates=dates[-context_len_actual:],
                    historical_values=(multi_df.iloc[-context_len_actual:, 0].values.astype(float).tolist() if multi_df is not None else values[-context_len_actual:].tolist()),
                    forecast_dates=forecast_dates,
                    forecast_values=result["forecast"].tolist(),
                    forecast_quantiles=result["quantiles"].tolist() if result.get("quantiles") is not None else None,
                    metrics={
                        "last_value": last_value,
                        "forecast_mean": float(result["forecast_mean"]),
                        "forecast_min": float(result["forecast_min"]),
                        "forecast_max": float(result["forecast_max"]),
                        "forecast_std": float(result["forecast_std"]),
                        "predicted_change_pct": pred_change,
                    },
                    model_version="TimesFM-3.0",
                    factor_list=factor_names if multi_df is not None else None,
                )
                progress_bar.progress(100, text="完成！")

                st.divider()
                st.subheader("📊 预测结果")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("当前价格", f"{last_value:.2f}")
                m2.metric("预测均值", f"{result['forecast_mean']:.2f}")
                m3.metric("预测变化", f"{pred_change:+.2f}%", delta=f"{pred_change:+.2f}%")
                m4.metric("预测步长", f"{horizon} 步")
                st.caption(f"🖥️ 推理设备: {result.get('device', 'unknown').upper()} | 模型: TimesFM-3.0 | 因子: {', '.join(factor_names) if multi_df is not None else '无'}")

                st.subheader("📈 交互式图表")
                chart_html = generate_echarts_html(
                    historical_dates=dates[-context_len_actual:],
                    historical_values=(multi_df.iloc[-context_len_actual:, 0].values.astype(float).tolist() if multi_df is not None else values[-context_len_actual:].tolist()),
                    forecast_dates=forecast_dates,
                    forecast_values=result["forecast"].tolist(),
                    forecast_quantiles=result["quantiles"].tolist() if result.get("quantiles") is not None else None,
                    stock_name=selected_stock["name"] + (" [多因子]" if multi_df is not None else ""),
                    frequency=frequency,
                )
                st.components.v1.html(chart_html, height=520)

                st.subheader("📋 预测数据")
                forecast_df = pd.DataFrame({"日期": forecast_dates, "预测价格": [round(float(v), 2) for v in result["forecast"]]})
                st.dataframe(forecast_df, use_container_width=True)
                st.caption(f"💾 预测记录已保存，ID: #{record_id}")

            except Exception as e:
                st.error(f"❌ 预测失败: {str(e)}")
                import traceback
                st.code(traceback.format_exc())

    with tab_history:
        st.subheader("📋 预测历史记录")
        stats = get_stats()
        c1, c2 = st.columns(2)
        c1.metric("总预测次数", stats["total_forecasts"])
        c2.metric("涉及股票数", stats["unique_stocks"])
        st.divider()
        records = get_history(limit=20)
        if not records:
            st.info("暂无预测记录")
        else:
            for rec in records:
                with st.expander(
                    f"📌 #{rec['id']} | {rec['stock_name']}({rec['stock_code']}) | {rec['frequency']} | {rec['horizon']}步 | {rec['created_at']}"
                ):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**当前价格:** {rec.get('last_value', 'N/A')}")
                        st.write(f"**预测均值:** {rec.get('forecast_mean', 'N/A')}")
                        st.write(f"**预测变化:** {rec.get('predicted_change_pct', 'N/A')}%")
                    with col_b:
                        st.write(f"**上下文长度:** {rec['context_len']}")
                        st.write(f"**预测步长:** {rec['horizon']}")
                        st.write(f"**模型版本:** {rec.get('model_version', 'N/A')}")
                    if rec.get("historical_dates") and rec.get("forecast_values"):
                        chart_html = generate_echarts_html(
                            historical_dates=rec["historical_dates"],
                            historical_values=rec["historical_values"],
                            forecast_dates=rec["forecast_dates"],
                            forecast_values=rec["forecast_values"],
                            forecast_quantiles=rec.get("forecast_quantiles"),
                            stock_name=rec["stock_name"],
                            frequency=rec["frequency"],
                        )
                        st.components.v1.html(chart_html, height=400)
                    if st.button(f"🗑️ 删除记录 #{rec['id']}", key=f"del_{rec['id']}"):
                        delete_record(rec["id"])
                        st.rerun()

    with tab_about:
        st.subheader("ℹ️ 关于本项目")
        st.markdown("""
### 🎯 项目简介
本项目基于 **Google TimesFM 3.0** 多因子时间序列基础模型，实现 A 股股票价格预测。

### 🔧 技术栈
- **模型**: TimesFM 3.0 (300M params, PyTorch)
- **数据源**: baostock (A股历史数据，免费无需 token)
- **前端**: Streamlit + ECharts
- **存储**: SQLite (预测历史)

### 📊 支持的数据频率
| 频率 | 说明 |
|------|------|
| 日线 | 每日K线 |
| 周线 | 每周K线 |
| 月线 | 每月K线 |
| 5/15/30/60分钟 | 分钟级K线 |

### ⚠️ 免责声明
本工具仅供学习和研究使用，**不构成任何投资建议**。
股票市场存在风险，预测结果仅供参考，请谨慎决策。
""")


if __name__ == "__main__":
    main()
