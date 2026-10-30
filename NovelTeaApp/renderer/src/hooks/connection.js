// Phones (iOS Safari especially) freeze a page and cut its open requests when you switch to another app.
// The server keeps working and saves the result, so a request that died this way is not a failure:
// wait, and pick the result up from the server when it is ready.

// True for a request that never got an answer (dropped connection), false for a real error reply from the server.
export function isConnectionDrop(e) {
  return !!e && (e.name === 'TypeError' || e.name === 'AbortError'
    || /load failed|failed to fetch|networkerror|network connection was lost|the internet connection appears/i.test(e.message || ''))
}

// Resolves after `ms`, or straight away when the page comes back into view (the user returned to the app).
export function waitOrReturn(ms) {
  return new Promise(resolve => {
    let done = false
    const finish = () => { if (done) return; done = true; clearTimeout(t); document.removeEventListener('visibilitychange', onVis); window.removeEventListener('online', finish); resolve() }
    const onVis = () => { if (document.visibilityState === 'visible') finish() }
    const t = setTimeout(finish, ms)
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('online', finish)
  })
}
