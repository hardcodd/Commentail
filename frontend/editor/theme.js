/* Follow the containing surface, including sites whose theme uses only a class. */
const CommentailEditorTheme = (() => {
  const palette = ['surface', 'subtle', 'ink', 'muted', 'line', 'accent', 'selected'];
  const luminance = rgb => rgb.reduce((sum, value, index) => {
    const channel = value / 255;
    return sum + (channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4) * [.2126, .7152, .0722][index];
  }, 0);

  function follow(node, owner, signal) {
    const view = node.ownerDocument.defaultView;
    const canvas = node.ownerDocument.createElement('canvas');
    canvas.width = canvas.height = 1;
    const paint = canvas.getContext('2d', { willReadFrequently: true });
    const ancestors = [];
    for (let element = node; element; element = element.parentElement) ancestors.push(element);
    const preference = view.matchMedia('(prefers-color-scheme: dark)');
    let frame = null;

    function update() {
      frame = null;
      const host = view.getComputedStyle(node.parentElement);
      const schemes = host.colorScheme.split(/\s+/);
      let dark = schemes.includes('dark') && !schemes.includes('light') ||
        (!schemes.includes('light') || schemes.includes('dark')) && preference.matches;
      if (paint) {
        // For unpainted themes without color-scheme, infer a fallback from host text.
        paint.fillStyle = host.color;
        paint.fillRect(0, 0, 1, 1);
        if (schemes.includes('normal')) dark = luminance([...paint.getImageData(0, 0, 1, 1).data].slice(0, 3)) > .5;
        paint.fillStyle = dark ? '#000' : '#fff';
        paint.fillRect(0, 0, 1, 1);
        for (const element of [...ancestors].reverse()) {
          paint.fillStyle = view.getComputedStyle(element).backgroundColor;
          paint.fillRect(0, 0, 1, 1);
        }
        dark = luminance([...paint.getImageData(0, 0, 1, 1).data].slice(0, 3)) < .179;
      }
      node.dataset.editorTheme = owner.dataset.editorTheme = dark ? 'dark' : 'light';
      const style = view.getComputedStyle(node);
      // The modal is outside the host subtree; carry its resolved custom palette.
      for (const name of palette) owner.style.setProperty('--' + name, style.getPropertyValue('--' + name));
    }
    function schedule() {
      if (frame === null) frame = view.requestAnimationFrame(update);
    }
    function transition(event) {
      if (ancestors.includes(event.target)) schedule();
    }
    const observer = new view.MutationObserver(records => {
      // Accept arbitrary site theme attributes (data-theme, data-bs-theme, ...),
      // without observing edits inside the composer or our own output attribute.
      if (records.some(record => record.target !== node || record.attributeName !== 'data-editor-theme')) schedule();
    });
    for (const element of ancestors) observer.observe(element, { attributes: true });
    preference.addEventListener('change', schedule);
    view.addEventListener('resize', schedule);
    view.addEventListener('transitionend', transition);
    signal.addEventListener('abort', () => {
      observer.disconnect();
      preference.removeEventListener('change', schedule);
      view.removeEventListener('resize', schedule);
      view.removeEventListener('transitionend', transition);
      if (frame !== null) view.cancelAnimationFrame(frame);
      delete node.dataset.editorTheme;
    }, { once: true });
    update();
  }
  return Object.freeze({ follow });
})();
