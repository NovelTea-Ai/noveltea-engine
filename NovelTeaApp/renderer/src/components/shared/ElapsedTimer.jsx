import { useEffect, useState } from 'react'

// 75 -> "1:15", 3725 -> "1:02:05"
export function fmtElapsed(s) {
  s = Math.max(0, Math.round(s || 0))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
  const mm = h ? String(m).padStart(2, '0') : String(m)
  return `${h ? h + ':' : ''}${mm}:${String(sec).padStart(2, '0')}`
}

// Seconds since a Date.now() timestamp.
export function secsSince(t) {
  return t ? Math.max(0, Math.round((Date.now() - t) / 1000)) : 0
}

// A running "⏱ 1:23" shown on a button or line while something works, in place of a spinner.
// `since` is when the work started (Date.now()); without it the timer counts from when it appeared.
export default function ElapsedTimer({ since, prefix = '⏱ ', style }) {
  const [mounted] = useState(() => Date.now())
  const [, tick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => tick(n => n + 1), 1000)
    return () => clearInterval(id)
  }, [])
  return (
    <span style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', ...style }}>
      {prefix}{fmtElapsed(secsSince(since || mounted))}
    </span>
  )
}
