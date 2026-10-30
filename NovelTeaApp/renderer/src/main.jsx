import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

// Apply the saved theme before first paint (light by default; the sidebar button switches to dark)
document.documentElement.dataset.theme = localStorage.getItem('nm-theme') || 'light'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

// Push notifications need a service worker, and browsers only allow one over HTTPS (or on this PC itself).
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}) })
}
