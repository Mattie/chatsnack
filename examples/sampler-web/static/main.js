import {Evaluator} from './evaluator.mjs';
import {buildColorStops, buildHsvColorStops} from './color-strip.mjs?v=hsv-icon';
const config = JSON.parse(document.querySelector('#config').textContent);
const el = id => document.getElementById(id);
let help = false;
const machine = new Evaluator(config.demos, config.configured, async (demo, text) => {
  const response = await fetch('/api/evaluate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({demo,text})});
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('Evaluation failed. Try again.');
  }
  if (!response.ok) throw new Error(data.error || 'Evaluation failed. Try again.');
  return data;
}, renderResults);

// Build controls once so live updates never interrupt selection or typing.
for (const demo of config.demos) {
  const button = document.createElement('button'); button.textContent = demo.label;
  button.dataset.demo = demo.id;
  button.addEventListener('click', () => {machine.select(demo.id); renderEditor();});
  el('tabs').append(button);
}
function renderEditor() {
  const demo = config.demos.find(d => d.id === machine.active);
  el('title').textContent = demo.title;
  el('guidance').textContent = demo.description;
  el('input').value = machine.tabs[machine.active].text;
  el('input').placeholder = demo.placeholder;
  el('input').classList.toggle('code', machine.active === 'code');
  document.querySelectorAll('[data-demo]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.demo === machine.active)));
  renderResults();
}
function renderResults() {
  const tab = machine.tabs[machine.active];
  const updating = ['waiting','loading'].includes(tab.status);
  el('status').textContent = !config.configured ? 'Set TYPESAFE_API_KEY on the server, then reload.' : tab.error || (updating ? 'Updating…' : tab.results.length && tab.resultRevision === tab.revision ? tab.model : '');
  el('retry').hidden = !tab.error;
  document.querySelector('.results').setAttribute('aria-busy', String(updating));
  document.querySelector('.results').classList.toggle('stale', tab.resultRevision !== tab.revision);
  el('results').replaceChildren();
  el('writing-results').replaceChildren();
  el('color-results').replaceChildren();
  const writing = machine.active === 'writing';
  const icon = machine.active === 'colors-hsv-icon';
  const colorMode = machine.active === 'colors-hsv' || icon ? 'hsv' : machine.active === 'colors' ? 'rgb' : null;
  const colors = colorMode !== null;
  document.querySelector('.results').classList.toggle('writing', writing);
  document.querySelector('.results').classList.toggle('colors', colors);
  el('writing-results').hidden = !writing;
  el('color-results').hidden = !colors;
  el('result-table').hidden = writing || colors;
  let rendered = tab.results.length;
  if (writing) renderWriting(tab.results);
  else if (colors) rendered = renderColors(tab.results, colorMode, icon);
  else
  for (const result of tab.results) {
    const row = document.createElement('tr');
    const question = document.createElement('th'); question.scope = 'row'; question.textContent = result.label;
    if (help) {const detail = document.createElement('small'); detail.textContent = result.question; question.append(detail);}
    const answer = document.createElement('td'); answer.className = 'answer'; answer.textContent = result.choice;
    const confidence = document.createElement('td');
    const wrap = document.createElement('div'); wrap.className = 'confidence';
    const meter = document.createElement('meter'); meter.min = 0; meter.max = 1; meter.value = result.confidence; meter.setAttribute('aria-label', `${result.label} confidence`);
    const value = document.createElement('span'); value.textContent = `${Math.round(result.confidence*100)}%`;
    wrap.append(meter,value); confidence.append(wrap); row.append(question,answer,confidence); el('results').append(row);
  }
  el('empty').hidden = rendered > 0;
}

// The Sampler returns ordinary yes/no answers; probability of yes becomes channel intensity.
function renderColors(results, mode, icon=false) {
  const stops = mode === 'hsv' ? buildHsvColorStops(results) : buildColorStops(results);
  if (!stops.length) return 0;
  const strip = document.createElement('ol'); strip.className = 'color-strip' + (icon ? ' color-icon-grid' : '');
  for (const stop of stops) {
    const bar = document.createElement('li'); bar.className = 'color-stop';
    bar.style.setProperty('--swatch', stop.css);
    bar.style.setProperty('--swatch-ink', stop.ink);
    const description = mode === 'hsv'
      ? `hue ${stop.hueName}, saturation ${stop.saturation}, value ${stop.value}`
      : `red ${stop.red}, green ${stop.green}, blue ${stop.blue}`;
    const row = Math.ceil(stop.index / 3), column = (stop.index - 1) % 3 + 1;
    bar.setAttribute('aria-label', icon
      ? `Pixel ${stop.index}, row ${row}, column ${column}: ${description}`
      : `Color ${stop.index}: ${description}`);
    const number = document.createElement('span'); number.className = 'color-stop-number'; number.textContent = String(stop.index).padStart(2, '0');
    const values = document.createElement('span'); values.className = 'color-stop-values';
    values.textContent = mode === 'hsv'
      ? `H ${stop.hue}\u00b0\nS ${stop.saturation}\nV ${stop.value}`
      : `R ${stop.red}\nG ${stop.green}\nB ${stop.blue}`;
    bar.append(number, values); strip.append(bar);
  }
  el('color-results').append(strip);
  return stops.length;
}

// Keep authored order while giving a large batch three browsable visual chapters.
function renderWriting(results) {
  const groups = [
    {title:'Under the microscope', start:0, end:12, style:'language'},
    {title:'The reaction', start:12, end:22, style:'delivery'},
    {title:'Unusual readings', start:22, end:Infinity, style:'personality'},
  ];
  for (const group of groups) {
    const items = results.slice(group.start, group.end);
    if (!items.length) continue;
    const section = document.createElement('section'); section.className = 'signal-group ' + group.style;
    const heading = document.createElement('h2'); heading.textContent = group.title;
    const grid = document.createElement('div'); grid.className = 'signal-grid';
    for (const result of items) {
      const card = document.createElement('article'); card.className = 'signal-card';
      const title = document.createElement('h3'); title.textContent = result.label;
      const answer = document.createElement('p'); answer.className = 'signal-answer'; answer.textContent = result.choice;
      const detail = document.createElement('p'); detail.className = 'signal-detail'; detail.textContent = result.question; detail.title = result.question; detail.hidden = !help;
      const confidence = document.createElement('div'); confidence.className = 'confidence';
      const meter = document.createElement('meter'); meter.min = 0; meter.max = 1; meter.value = result.confidence;
      meter.setAttribute('aria-label', result.label + ' confidence');
      const value = document.createElement('span'); value.textContent = Math.round(result.confidence * 100) + '%';
      confidence.append(meter, value); card.append(title, answer, detail, confidence); grid.append(card);
    }
    section.append(heading, grid); el('writing-results').append(section);
  }
}
el('input').addEventListener('input', e => machine.edit(e.target.value));
el('sample').addEventListener('click', () => {machine.edit(config.demos.find(d => d.id === machine.active).sample); renderEditor();});
el('retry').addEventListener('click', () => machine.retry());
el('help').addEventListener('click', () => {
  help = !help; el('help').setAttribute('aria-pressed', String(help));
  el('guidance').hidden = !help; el('help-note').hidden = !help; renderResults();
});
renderEditor(); machine.select(machine.active);
