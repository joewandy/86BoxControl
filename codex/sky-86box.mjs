/**
 * Helpers for a Codex node_repl session using @oai/sky.
 *
 * Initialize in node_repl:
 *   globalThis.sky = globalThis.sky || (await import('@oai/sky')).sky
 *   var ctl = await import('file:///absolute/path/to/codex/sky-86box.mjs')
 *
 * Element indexes are deliberately discovered from fresh app state. They are
 * transient and should never be carried across UI transitions.
 */

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function indexedLines(stateText) {
  return stateText.split(/\r?\n/).flatMap((line) => {
    const match = line.match(/^\s*(\d+)\s+(.*)$/);
    return match ? [{ index: Number(match[1]), description: match[2], line }] : [];
  });
}

export function findElementIndex(stateText, predicate, { last = false } = {}) {
  const matches = indexedLines(stateText).filter((entry) => predicate(entry.description, entry.line));
  if (matches.length === 0) {
    throw new Error('Accessible element was not found in the current 86Box state.');
  }
  return (last ? matches[matches.length - 1] : matches[0]).index;
}

export function findElementById(stateText, id, options) {
  return findElementIndex(stateText, (description) => description.includes(`ID: ${id}`), options);
}

export async function snapshot(sky, { screenshot = false } = {}) {
  // Element indexes are only meaningful against a complete tree. A diff can
  // omit an unchanged toolbar/menu item and make the next action impossible.
  return sky.get_app_state({ app: '86Box', disableDiff: true });
}

export async function emitSnapshot(sky, nodeRepl) {
  const state = await snapshot(sky, { screenshot: true });
  nodeRepl.write(state.text);
  if (state.screenshot) {
    const fs = await import('node:fs/promises');
    const url = await import('node:url');
    await nodeRepl.emitImage({
      bytes: await fs.readFile(url.fileURLToPath(state.screenshot.url)),
      mimeType: 'image/png',
    });
  }
  return state;
}

export async function sendGuestKeys(sky, keys, delayMilliseconds = 120) {
  for (const key of keys) {
    await sky.press_key({ app: '86Box', key });
    await sleep(delayMilliseconds);
  }
}

export async function mountCdImage(sky, absoluteImagePath) {
  if (!absoluteImagePath.startsWith('/')) {
    throw new Error('mountCdImage requires an absolute path.');
  }

  let state = await snapshot(sky);
  const mediaMenu = findElementIndex(state.text, (description) => description === 'Media', { last: true });
  await sky.click({ app: '86Box', element_index: mediaMenu });
  await sleep(250);

  state = await snapshot(sky);
  const imageItem = findElementIndex(
    state.text,
    (description) => description === 'Image…, ID: qt_itemFired:'
  );
  await sky.click({ app: '86Box', element_index: imageItem });
  await sleep(500);

  await sky.press_key({ app: '86Box', key: 'super+shift+g' });
  await sleep(300);

  state = await snapshot(sky);
  const pathField = findElementById(state.text, 'PathTextField');
  await sky.set_value({ app: '86Box', element_index: pathField, value: absoluteImagePath });
  await sky.press_key({ app: '86Box', key: 'Return' });
  await sleep(600);

  state = await snapshot(sky);
  const openButton = findElementById(state.text, 'OKButton');
  await sky.click({ app: '86Box', element_index: openButton });
  await sleep(900);
  return snapshot(sky);
}

export async function clickToolbarButton(sky, accessibleName) {
  const state = await snapshot(sky);
  const index = findElementIndex(
    state.text,
    (description) => description.startsWith(`button ${accessibleName}`)
  );
  await sky.click({ app: '86Box', element_index: index });
  await sleep(300);
  return snapshot(sky);
}

export async function ejectByVisibleName(sky, mountedFileName) {
  let state = await snapshot(sky);
  const mediaMenu = findElementIndex(state.text, (description) => description === 'Media', { last: true });
  await sky.click({ app: '86Box', element_index: mediaMenu });
  await sleep(250);

  state = await snapshot(sky);
  const ejectItem = findElementIndex(
    state.text,
    (description) => description.startsWith(`Eject ${mountedFileName}`)
  );
  await sky.click({ app: '86Box', element_index: ejectItem });
  await sleep(400);
  return snapshot(sky);
}
