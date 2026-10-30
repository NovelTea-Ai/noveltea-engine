import { useEffect, useState } from 'react'

// One reactive "is this a phone-width screen" check (the 768 breakpoint is hard-coded and read
// non-reactively in many places across the app; new layout code uses this instead).
export default function useIsMobile(breakpoint = 768) {
  const query = `(max-width: ${breakpoint - 1}px)`
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = () => setMobile(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return mobile
}
