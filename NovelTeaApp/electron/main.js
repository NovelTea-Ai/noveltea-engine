// NovelTea Engine desktop client.
//
// This is a window onto a NovelTea Engine server that is already running (on this computer, on another PC, or over a private network
// such as Tailscale). It is the same as opening the server's address in a browser: it does NOT start, stop, restart or configure the
// Python server, and it has no access to the corpus or the server's files. Start the server separately (see the README).
const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path = require('path')
const fs = require('fs')
const http = require('http')
const https = require('https')

const DEFAULT_SERVER = 'http://127.0.0.1:7432'
const CONNECT_PAGE = path.join(__dirname, 'connect.html')

let mainWindow = null
let serverUrl = null

// ── the server address ────────────────────────────────────────────────────────

function configFile() {
  return path.join(app.getPath('userData'), 'client.json')
}

function readSaved() {
  try {
    return JSON.parse(fs.readFileSync(configFile(), 'utf8')).serverUrl || null
  } catch {
    return null
  }
}

function saveUrl(url) {
  try {
    fs.mkdirSync(path.dirname(configFile()), { recursive: true })
    fs.writeFileSync(configFile(), JSON.stringify({ serverUrl: url }, null, 2))
  } catch (e) {
    console.error('[client] could not save the server address:', e.message)
  }
}

// "192.168.1.20:7432" -> "http://192.168.1.20:7432"; only http(s) addresses are accepted. Returns the origin, or null.
function normalize(input) {
  let s = String(input || '').trim()
  if (!s) return null
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = 'http://' + s
  try {
    const u = new URL(s)
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null
    return u.origin
  } catch {
    return null
  }
}

function argServer() {
  const a = process.argv.find(x => x.startsWith('--server='))
  return a ? a.slice('--server='.length) : null
}

// the order of preference: --server=URL, NOVELTEA_SERVER_URL, the address you last connected to, the local default
function initialServer() {
  return normalize(argServer()) || normalize(process.env.NOVELTEA_SERVER_URL) || normalize(readSaved()) || DEFAULT_SERVER
}

// Is a NovelTea Engine server answering at this address? (GET /api/health, 4 s)
function probe(url) {
  return new Promise(resolve => {
    let done = false
    const finish = r => { if (!done) { done = true; resolve(r) } }
    try {
      const lib = url.startsWith('https:') ? https : http
      const req = lib.get(url + '/api/health', { timeout: 4000 }, res => {
        res.resume()
        finish(res.statusCode === 200 ? { ok: true } : { ok: false, error: `The server answered with HTTP ${res.statusCode}.` })
      })
      req.on('timeout', () => { req.destroy(); finish({ ok: false, error: 'No answer from the server (timed out).' }) })
      req.on('error', e => finish({ ok: false, error: `Could not reach the server (${e.code || e.message}).` }))
    } catch (e) {
      finish({ ok: false, error: String(e.message || e) })
    }
  })
}

// ── the window ────────────────────────────────────────────────────────────────

function showConnect(error) {
  if (!mainWindow) return
  mainWindow.loadFile(CONNECT_PAGE, { query: { url: serverUrl || DEFAULT_SERVER, error: error || '' } })
}

async function openServer(url) {
  serverUrl = url
  const r = await probe(url)
  if (!r.ok) {
    showConnect(`${url}: ${r.error}`)
    return r
  }
  mainWindow.loadURL(url)
  return r
}

function openExternalSafe(url) {
  // only ordinary web links ever leave the app; never file:, custom protocols or anything a server page might ask for
  if (/^https?:\/\//i.test(url)) shell.openExternal(url)
}

function fromConnectPage(event) {
  try {
    return event.senderFrame.url.startsWith('file:') && event.senderFrame.url.includes('connect.html')
  } catch {
    return false
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#f3f4f6',
    titleBarStyle: 'hidden',
    frame: false,
    resizable: true,
    maximizable: true,
    minimizable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
    icon: path.join(__dirname, 'icon.png'),
  })

  const wc = mainWindow.webContents

  // stay on the server's own address; any other link opens in your normal browser
  wc.on('will-navigate', (e, url) => {
    if (url.startsWith('file:') && url.includes('connect.html')) return
    let sameOrigin = false
    try { sameOrigin = new URL(url).origin === serverUrl } catch { /* not a URL */ }
    if (!sameOrigin) {
      e.preventDefault()
      openExternalSafe(url)
    }
  })
  wc.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url)
    return { action: 'deny' }
  })

  // the server went away while the app was open, or the address is wrong
  wc.on('did-fail-load', (_e, code, desc, url, isMainFrame) => {
    if (isMainFrame && code !== -3) showConnect(`${serverUrl}: ${desc}`)
  })

  // Ctrl+Shift+K: change the server
  wc.on('before-input-event', (e, input) => {
    if (input.type === 'keyDown' && input.control && input.shift && String(input.key).toLowerCase() === 'k') {
      e.preventDefault()
      showConnect('')
    }
  })

  openServer(serverUrl)
}

app.whenReady().then(() => {
  serverUrl = initialServer()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  app.quit()
})

// ── what the page may ask the app to do ───────────────────────────────────────

ipcMain.on('window-minimize', () => mainWindow && mainWindow.minimize())
ipcMain.on('window-maximize', () => {
  if (!mainWindow) return
  mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize()
})
ipcMain.on('window-close', () => mainWindow && mainWindow.close())
ipcMain.on('open-external', (_e, url) => openExternalSafe(String(url || '')))

// any page may ask to show the address screen; only that screen can actually change the server
ipcMain.on('server:change', () => showConnect(''))
ipcMain.handle('server:get-url', () => serverUrl || DEFAULT_SERVER)
ipcMain.handle('server:connect', async (e, input) => {
  if (!fromConnectPage(e)) return { ok: false, error: 'Not allowed from this page.' }
  const url = normalize(input)
  if (!url) return { ok: false, error: 'Enter an address like 192.168.1.20:7432 or https://my-pc.tailnet.ts.net:8443' }
  const r = await openServer(url)
  if (r.ok) saveUrl(url)
  return r
})
