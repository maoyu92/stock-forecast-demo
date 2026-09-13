import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

interface Props {
  history?: { dates: string[]; values: (number | null)[] }
  forecast?: { dates: string[]; values: number[] }
  band?: { lower: number[] | null; upper: number[] | null }
  kline?: { dates: string[]; values: (number | null)[] }
  height?: number
}

/** 历史 + 预测曲线 + 分位置信带（ECharts） */
export default function ForecastChart({ history, forecast, band, kline, height = 420 }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    chartRef.current = echarts.init(ref.current)
    const onResize = () => chartRef.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    let hist = history ?? null
    if (!hist && kline) {
      // 预览模式：K线仅取最近 180 个点
      const n = Math.min(180, kline.dates.length)
      hist = {
        dates: kline.dates.slice(-n),
        values: kline.values.slice(-n),
      }
    }
    if (!hist) { chart.clear(); return }

    const dates = [...hist.dates, ...(forecast?.dates ?? [])]
    const hVals = [...hist.values, ...forecast ? [null] : []].slice(0, dates.length)
    // 预测线从历史最后一个点"桥接"，视觉连续
    const bridge = hist.values.length ? hist.values[hist.values.length - 1] : null
    const fVals = forecast
      ? [...Array(hist.values.length - 1).fill(null), bridge, ...forecast.values]
      : []

    const series: echarts.SeriesOption[] = [
      {
        name: '历史', type: 'line', data: hVals, showSymbol: false,
        lineStyle: { color: '#5470c6', width: 1.6 }, z: 3,
      },
    ]
    if (forecast && band?.lower && band?.upper) {
      const nPad = hist.values.length
      const lower = [...Array(nPad).fill(null), ...[bridge, ...band.lower]]
      const upper = [...Array(nPad).fill(null), ...[bridge, ...band.upper]]
      series.push(
        {
          name: 'band-base', type: 'line', data: lower, stack: 'band',
          symbol: 'none', lineStyle: { opacity: 0 }, z: 1, silent: true,
        },
        {
          name: '置信区间', type: 'line', data: upper.map((u, i) =>
            u != null && lower[i] != null ? +(u - (lower[i] as number)).toFixed(4) : null),
          stack: 'band', symbol: 'none', z: 1, silent: true,
          lineStyle: { opacity: 0 },
          areaStyle: { color: 'rgba(238,102,102,0.18)' },
        },
      )
    }
    if (forecast) {
      series.push({
        name: '预测', type: 'line', data: fVals,
        symbol: 'circle', symbolSize: 5,
        lineStyle: { color: '#ee6666', width: 2.4, type: 'dashed' },
        itemStyle: { color: '#ee6666' }, z: 4,
      })
    }

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { data: ['历史', '预测', '置信区间'], top: 4 },
      grid: { left: 56, right: 24, top: 40, bottom: 56 },
      xAxis: {
        type: 'category', data: dates,
        axisLabel: { fontSize: 10, formatter: (v: string) => v.slice(5) },
      },
      yAxis: { type: 'value', scale: true, axisLabel: { fontSize: 10 } },
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, height: 18, bottom: 10 },
      ],
      series,
    }, true)
  }, [history, forecast, band, kline])

  return <div ref={ref} style={{ width: '100%', height }} />
}
