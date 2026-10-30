// The narration voices the app offers (Reader's voice menu and Settings → Voice Samples).
// Every voice is a "pitch swap" voice: the narration in the voice itself, and anything inside quotes in the same
// voice 0.37 of a semitone higher or lower ("Kokoro.<name>@±0.37"), so dialogue stands apart without a second
// speaker. Kokoro runs locally on the CPU (no API key); bf_/bm_ are British, af_/am_ American.
// (The backend can still speak plain voices, duo voices "Kokoro.<a>+<b>" and NVIDIA voices if they are added here.)
const PITCH = 0.37
const KOKORO = [
  ['bf_emma', 'Emma', 'British female'], ['bf_isabella', 'Isabella', 'British female'],
  ['bf_alice', 'Alice', 'British female'], ['bf_lily', 'Lily', 'British female'],
  ['bm_george', 'George', 'British male'], ['bm_fable', 'Fable', 'British male'],
  ['bm_lewis', 'Lewis', 'British male'], ['bm_daniel', 'Daniel', 'British male'],
  ['af_heart', 'Heart', 'US female'], ['af_bella', 'Bella', 'US female'],
  ['am_michael', 'Michael', 'US male'], ['am_fenrir', 'Fenrir', 'US male'],
]

export const TTS_VOICES = KOKORO.flatMap(([code, name, group]) => [
  { id: `Kokoro.${code}@+${PITCH}`, label: `${name} · quotes higher`, group: `Kokoro ${group}` },
  { id: `Kokoro.${code}@-${PITCH}`, label: `${name} · quotes lower`, group: `Kokoro ${group}` },
])
export const TTS_GROUPS = [...new Set(TTS_VOICES.map(v => v.group))]

// The saved voice (localStorage 'nm-tts-voice'), mapped onto what is offered now: a voice no longer listed (an old
// pitch amount, a plain or duo voice) becomes the same narrator in the same direction ("quotes higher" if none),
// else Lewis · quotes higher.
export function savedTtsVoice() {
  let saved = null
  try { saved = localStorage.getItem('nm-tts-voice') } catch { /* storage blocked */ }
  if (saved && TTS_VOICES.some(v => v.id === saved)) return saved
  const [voiceBase, pitch] = (saved || '').split('@')
  const base = voiceBase.split('+')[0]
  const same = TTS_VOICES.find(v => v.id.startsWith(`${base}@${pitch ? pitch[0] : '+'}`))
  return (same || TTS_VOICES.find(v => v.id.startsWith('Kokoro.bm_lewis@+')) || TTS_VOICES[0]).id
}
