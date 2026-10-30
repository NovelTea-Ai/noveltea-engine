import { useEffect, useRef } from 'react'
import NoSleep from 'nosleep.js'

// Keeps the screen on while `active` is true, like a video player does. Uses the Screen Wake Lock API where the browser allows it (it needs
// https or localhost); otherwise NoSleep.js plays a tiny hidden video, which also works over plain http on a phone. Phones only allow either
// after a tap, so if starting fails the lock is taken on the next tap or touch.
export default function useKeepAwake(active) {
  const ns = useRef(null)
  const on = useRef(false)

  useEffect(() => {
    if (!ns.current) ns.current = new NoSleep()
    const noSleep = ns.current
    if (!active) {
      if (on.current) { try { noSleep.disable() } catch { /* nothing to release */ } on.current = false }
      return undefined
    }
    const take = () => {
      if (on.current) return
      Promise.resolve(noSleep.enable()).then(() => { on.current = true; drop() }).catch(() => { /* wait for the next tap */ })
    }
    const events = ['click', 'touchend', 'keydown']
    const drop = () => events.forEach(e => document.removeEventListener(e, take))
    const back = () => { if (document.visibilityState === 'visible' && active) { on.current = false; take() } }   // the lock is lost when the tab is hidden
    take()
    if (!on.current) events.forEach(e => document.addEventListener(e, take, { passive: true }))
    document.addEventListener('visibilitychange', back)
    return () => { drop(); document.removeEventListener('visibilitychange', back) }
  }, [active])

  useEffect(() => () => { try { ns.current?.disable() } catch { /* already off */ } }, [])
}
