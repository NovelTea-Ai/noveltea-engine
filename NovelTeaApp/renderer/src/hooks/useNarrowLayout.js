import { createContext, useContext, useEffect, useState } from 'react'

// True for anything hosted inside a desktop SIDE PANEL (the always-open Pre-/Post-generation panels): a tool there is
// only a few hundred pixels wide, so it lays itself out the way it does on a phone: a single column.
export const SidePanelContext = createContext(false)

// "Use the phone layout": a phone-width window, or a tool hosted in a side panel.
export default function useNarrowLayout() {
  const inPanel = useContext(SidePanelContext)
  const [win, setWin] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768)
  useEffect(() => {
    const on = () => setWin(window.innerWidth < 768)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return inPanel || win
}
