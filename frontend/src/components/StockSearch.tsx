import { AutoComplete, Tag } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type StockRef } from '../api'

interface Props {
  value?: StockRef | null
  onChange: (s: StockRef) => void
  placeholder?: string
  style?: React.CSSProperties
}

/** 股票搜索（代码/名称模糊匹配，防抖） */
export default function StockSearch({ value, onChange, placeholder, style }: Props) {
  const [options, setOptions] = useState<{ value: string; label: React.ReactNode; stock: StockRef }[]>([])
  const [text, setText] = useState(value?.name ? `${value.code} ${value.name}` : '')
  const timer = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    if (value) setText(`${value.code} ${value.name ?? ''}`)
  }, [value])

  const doSearch = useCallback((kw: string) => {
    if (!kw.trim()) { setOptions([]); return }
    api.searchStocks(kw.trim())
      .then(rs => setOptions(rs.results.map(s => ({
        value: s.code,
        stock: s,
        label: (
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>{s.name}</span>
            <Tag style={{ marginLeft: 8 }}>{s.code}</Tag>
          </div>
        ),
      }))))
      .catch(() => setOptions([]))
  }, [])

  const scheduleSearch = useCallback((kw: string) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => doSearch(kw), 300)
  }, [doSearch])

  return (
    <AutoComplete
      style={{ width: '100%', ...style }}
      value={text}
      options={options}
      onChange={v => {
        setText(v)
        scheduleSearch(v)
      }}
      onSelect={(_v, opt) => {
        onChange(opt.stock)
        setText(`${opt.stock.code} ${opt.stock.name ?? ''}`)
        setOptions([])
      }}
      onClear={() => setOptions([])}
      placeholder={placeholder ?? '输入代码或名称，如：太保 / sh.601601'}
      allowClear
    />
  )
}
