import { useEffect, useState } from 'react'
import { api } from '../../api'

// Settings → Phone & Notifications: the app's HTTPS link for the phone, how to put it on the Home Screen, and the
// switch for push notifications (a part written, a narration ready) — sent by the PC even while you're in another app.
function b64ToBytes(s) {
  const pad = '='.repeat((4 - (s.length % 4)) % 4)
  const raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, c => c.charCodeAt(0))
}

const box = { padding: '14px 16px', marginBottom: 14, background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)' }
const btn = { padding: '8px 14px', minHeight: 40, fontSize: 12, fontWeight: 700, borderRadius: 'var(--radius-sm)', border: 'none', cursor: 'pointer' }

export default function PhoneSetup() {
  const [info, setInfo] = useState(null)
  const [copied, setCopied] = useState(false)
  const [msg, setMsg] = useState('')
  const [subscribed, setSubscribed] = useState(false)
  const secure = typeof window !== 'undefined' && window.isSecureContext
  const supported = typeof navigator !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window
  const standalone = typeof window !== 'undefined' && (window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone)
  const permission = typeof Notification !== 'undefined' ? Notification.permission : 'unsupported'

  useEffect(() => {
    api.pushInfo().then(setInfo).catch(() => setInfo({}))
    if (supported && secure) {
      navigator.serviceWorker.getRegistration().then(r => r?.pushManager.getSubscription()).then(s => setSubscribed(!!s)).catch(() => {})
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const url = info?.phone_url || ''

  async function copy() {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000) }
    catch { setMsg('Copy failed: select the link and copy it by hand.') }
  }

  async function enable() {
    setMsg('')
    try {
      const perm = await Notification.requestPermission()
      if (perm !== 'granted') { setMsg('Notifications were not allowed. You can allow them in the phone’s Settings → Notifications → NovelTea Engine.'); return }
      const reg = await navigator.serviceWorker.register('/sw.js')
      await navigator.serviceWorker.ready
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(info.public_key) })
      await api.pushSubscribe(sub.toJSON(), navigator.userAgent.slice(0, 80))
      setSubscribed(true)
      setMsg('✓ Notifications are on for this device.')
    } catch (e) { setMsg(`Could not turn notifications on: ${e.message || e}`) }
  }

  async function disable() {
    try {
      const reg = await navigator.serviceWorker.getRegistration()
      const sub = await reg?.pushManager.getSubscription()
      if (sub) { await api.pushUnsubscribe(sub.toJSON()); await sub.unsubscribe() }
      setSubscribed(false)
      setMsg('Notifications are off for this device.')
    } catch (e) { setMsg(`Could not turn them off: ${e.message || e}`) }
  }

  async function test() {
    try {
      const r = await api.pushTest()
      setMsg(r.errors?.length ? `Test not delivered: ${r.errors[0]}`
        : r.sent ? `✓ Test sent to ${r.sent} device${r.sent === 1 ? '' : 's'}.` : 'No device has notifications on yet.')
    }
    catch (e) { setMsg(`Test failed: ${e.message}`) }
  }

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Phone & Notifications</h2>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Long jobs (a chapter part, a narration) run on this PC in the background, so switching apps on the phone no longer
          breaks them. To be told when one finishes, open NovelTea Engine on the phone from the link below, add it to the Home Screen,
          and turn notifications on.
        </div>
      </div>

      <div style={box}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>1. The phone link (HTTPS, on your Tailscale network only)</div>
        {url ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <a href={url} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontFamily: 'monospace', wordBreak: 'break-all', color: 'var(--accent-light)' }}>{url}</a>
            <button onClick={copy} style={{ ...btn, background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}>
              {copied ? '✓ Copied' : 'Copy'}</button>
          </div>
        ) : <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{info ? 'Tailscale is not running on this PC, so there is no phone link.' : 'Looking up the link…'}</div>}
      </div>

      <div style={box}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>2. Add it to the Home Screen (iPhone)</div>
        <ol style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8, paddingLeft: 18, margin: 0 }}>
          <li>Open the link above in <b>Safari</b> on the phone.</li>
          <li>Tap the <b>Share</b> button, then <b>Add to Home Screen</b>, then <b>Add</b>.</li>
          <li>Open NovelTea Engine from the new Home Screen icon (notifications only work from there).</li>
        </ol>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
          This screen: {standalone ? '✓ opened from the Home Screen' : 'opened in a browser tab'} · {secure ? '✓ HTTPS' : 'not HTTPS (use the link above)'}
        </div>
      </div>

      <div style={box}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>3. Notifications on this device</div>
        {!supported || !secure ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {!secure ? 'Open NovelTea Engine from the HTTPS link above (from the Home Screen icon on an iPhone) to turn notifications on.'
              : 'This browser does not support push notifications. On an iPhone, open NovelTea Engine from its Home Screen icon.'}
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            {subscribed
              ? <button onClick={disable} style={{ ...btn, background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}>Turn off</button>
              : <button onClick={enable} disabled={!info?.public_key} style={{ ...btn, background: 'var(--accent)', color: '#fff' }}>🔔 Enable notifications</button>}
            <button onClick={test} style={{ ...btn, background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}>Send a test</button>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {subscribed ? '✓ On for this device' : permission === 'denied' ? 'Blocked in the phone’s settings' : 'Off'}
              {info?.subscriptions != null ? ` · ${info.subscriptions} device${info.subscriptions === 1 ? '' : 's'} signed up` : ''}
            </span>
          </div>
        )}
        {msg && <div style={{ fontSize: 12, marginTop: 8, color: msg.startsWith('✓') ? 'var(--green)' : 'var(--text-secondary)' }}>{msg}</div>}
      </div>
    </>
  )
}
