const CHANNELS = {r: 'red', g: 'green', b: 'blue'};
const HUES = {red:0, orange:30, yellow:60, chartreuse:90, green:120, spring:150,
  cyan:180, azure:210, blue:240, violet:270, magenta:300, rose:330};

function channelValue(result) {
  const score = Number(result?.score);
  if (!Number.isFinite(score) || score < 0 || score > 1) return null;
  return Math.round(score * 100);
}

/** Convert named yes/no probabilities into complete, ordered RGB color stops. */
export function buildColorStops(results, count=12) {
  const grouped = Array.from({length: count}, (_, index) => ({index: index + 1}));
  for (const result of results || []) {
    const match = /^stop_(\d{2})_([rgb])$/.exec(result?.name || '');
    if (!match) continue;
    const index = Number(match[1]);
    if (index < 1 || index > count) continue;
    const value = channelValue(result);
    if (value !== null) grouped[index - 1][CHANNELS[match[2]]] = value;
  }
  return grouped.filter(stop => ['red', 'green', 'blue'].every(channel => Number.isFinite(stop[channel])))
    .map(stop => {
      const bytes = ['red', 'green', 'blue'].map(channel => Math.round(stop[channel] * 2.55));
      const luminance = .299 * bytes[0] + .587 * bytes[1] + .114 * bytes[2];
      return {...stop, css: `rgb(${bytes.join(', ')})`, ink: luminance > 150 ? '#211526' : '#fff5e6'};
    });
}

function hsvToRgb(hue, saturation, value) {
  const chroma = value * saturation;
  const intermediate = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
  const light = value - chroma;
  const sectors = [[chroma,intermediate,0],[intermediate,chroma,0],[0,chroma,intermediate],
    [0,intermediate,chroma],[intermediate,0,chroma],[chroma,0,intermediate]];
  return sectors[Math.floor(hue / 60)].map(channel => Math.round((channel + light) * 255));
}

/** Compose one hue choice and two yes probabilities into each ordered HSV stop. */
export function buildHsvColorStops(results, count=12) {
  const grouped = Array.from({length: count}, (_, index) => ({index: index + 1}));
  for (const result of results || []) {
    const match = /^(?:stop|pixel)_(\d{2})_([hsv])$/.exec(result?.name || '');
    if (!match) continue;
    const index = Number(match[1]);
    if (index < 1 || index > count) continue;
    if (match[2] === 'h') {
      if (Object.hasOwn(HUES, result.choice)) {
        grouped[index - 1].hueName = result.choice;
        grouped[index - 1].hue = HUES[result.choice];
      }
    } else {
      const value = channelValue(result);
      if (value !== null) grouped[index - 1][match[2] === 's' ? 'saturation' : 'value'] = value;
    }
  }
  return grouped.filter(stop => Number.isFinite(stop.hue) && Number.isFinite(stop.saturation)
      && Number.isFinite(stop.value))
    .map(stop => {
      const bytes = hsvToRgb(stop.hue, stop.saturation / 100, stop.value / 100);
      const luminance = .299 * bytes[0] + .587 * bytes[1] + .114 * bytes[2];
      return {...stop, css: `rgb(${bytes.join(', ')})`, ink: luminance > 150 ? '#211526' : '#fff5e6'};
    });
}
