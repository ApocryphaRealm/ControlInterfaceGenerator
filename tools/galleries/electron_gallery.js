// CIG Electron gallery: make the ARIA switch and the tabs behave like the real thing (state in ARIA attributes).
const sw = document.getElementById('switch')
sw.addEventListener('click', () => sw.setAttribute('aria-checked', sw.getAttribute('aria-checked') === 'true' ? 'false' : 'true'))
for (const t of document.querySelectorAll('[role=tab]')) {
  t.addEventListener('click', () => {
    for (const o of document.querySelectorAll('[role=tab]')) o.setAttribute('aria-selected', o === t ? 'true' : 'false')
  })
}
