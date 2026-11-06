import { validateTimeline, validateInterface, segments, interfaceSampleForPair, recordedDevice, safeImageName } from './model.js';

const $ = (id) => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
let timeline = null;
let boundary = null;
let selected = 0;
let showB = false;
let imageBase = './demo/';
let imageFiles = new Map();
let loadingGeneration = 0;

function element(tag, attributes = {}, text = null) {
  const node = document.createElementNS(SVG, tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (text !== null) node.textContent = text;
  return node;
}

function format(value, digits = 3) {
  return value === null || value === undefined ? 'Missing' : Number(value).toFixed(digits);
}

function clearImages() {
  imageFiles.forEach((url) => URL.revokeObjectURL(url));
  imageFiles.clear();
}

function drawChart(svg, series, xDomain, yDomain, xLabel, yLabel) {
  svg.replaceChildren();
  const [, , width, height] = svg.getAttribute('viewBox').split(' ').map(Number);
  const box = { left: 62, right: width - 18, top: 12, bottom: height - 45 };
  const x = (value) => box.left + (value - xDomain[0]) / (xDomain[1] - xDomain[0]) * (box.right - box.left);
  // Image rows increase downward, matching the source image coordinates.
  const y = (value) => box.top + (value - yDomain[0]) / (yDomain[1] - yDomain[0]) * (box.bottom - box.top);
  for (let i = 0; i <= 4; i += 1) {
    const xv = xDomain[0] + i / 4 * (xDomain[1] - xDomain[0]);
    const yv = yDomain[0] + i / 4 * (yDomain[1] - yDomain[0]);
    svg.append(element('line', { x1: x(xv), y1: box.top, x2: x(xv), y2: box.bottom, stroke: '#e6edee' }));
    svg.append(element('line', { x1: box.left, y1: y(yv), x2: box.right, y2: y(yv), stroke: '#e6edee' }));
    svg.append(element('text', { x: x(xv), y: box.bottom + 17, 'text-anchor': 'middle' }, Number(xv.toPrecision(3))));
    svg.append(element('text', { x: box.left - 9, y: y(yv) + 3, 'text-anchor': 'end' }, Number(yv.toPrecision(3))));
  }
  series.forEach(({ xs, ys, color }) => {
    segments(xs, ys).forEach((part) => {
      const d = part.map(([xx, yy], i) => `${i ? 'L' : 'M'}${x(xx).toFixed(2)},${y(yy).toFixed(2)}`).join(' ');
      svg.append(element('path', { d, stroke: color, 'stroke-width': 1.8, fill: 'none' }));
      if (part.length === 1) svg.append(element('circle', { cx: x(part[0][0]), cy: y(part[0][1]), r: 2.5, fill: color }));
    });
  });
  svg.append(element('text', { x: (box.left + box.right) / 2, y: height - 5, 'text-anchor': 'middle' }, xLabel));
  svg.append(element('text', { transform: `translate(12 ${(box.top + box.bottom) / 2}) rotate(-90)`, 'text-anchor': 'middle' }, yLabel));
}

function image(id, missingId, name) {
  const img = $(id);
  const url = safeImageName(name) ? (imageFiles.get(name) || (imageBase ? imageBase + name : null)) : null;
  img.hidden = !url;
  $(missingId).hidden = Boolean(url);
  img.onerror = () => { img.hidden = true; $(missingId).hidden = false; };
  if (url) img.src = url;
  else img.removeAttribute('src');
}

function render() {
  if (!timeline) return;
  const pair = timeline.pairs[selected];
  const profile = timeline.profiles[selected];
  $('motion').textContent = `${format(pair.median_dx_px_per_source_frame)} px/frame`;
  $('velocity').textContent = timeline.physical_units ? `${format(pair.velocity_m_per_s, 4)} m/s` : 'Not calibrated';
  $('calibration').textContent = timeline.physical_units
    ? (timeline.calibration_approximate ? 'Approximate spatial calibration' : 'Calibration supplied with the analysis')
    : 'Profile uses pixels per source frame';
  $('coverage').textContent = `${format(pair.texture_coverage * 100, 1)}%`;
  $('device').textContent = boundary ? recordedDevice(boundary) : 'No interface result';
  image('frame', 'frame-missing', pair[showB ? 'frame_b_preview' : 'frame_preview']);
  image('vectors', 'vectors-missing', pair.vector_preview);
  $('frame-info').textContent = `Original frame ${showB ? pair.original_frame_b : pair.original_frame_a} · selected pair ${showB ? 'B' : 'A'}`;
  $('toggle').textContent = showB ? 'Show A' : 'Show B';
  $('pair-info').textContent = `Pair ${selected + 1} / ${timeline.pairs.length} · ${pair.original_frame_a} → ${pair.original_frame_b}`;
  $('pair-time').textContent = pair.midpoint_seconds_from_start === null
    ? 'Acquisition timing unavailable.'
    : `Pair midpoint ${format(pair.midpoint_seconds_from_start, 4)} s from selection start`;
  $('pair').max = timeline.pairs.length - 1;
  $('pair').value = selected;
  $('pair').disabled = false;
  $('previous').disabled = selected === 0;
  $('next').disabled = selected === timeline.pairs.length - 1;
  const rowDomain = [timeline.rows[0], timeline.rows.at(-1)];
  if (rowDomain[0] === rowDomain[1]) rowDomain[1] += 1;
  drawChart($('profile'), [
    { xs: profile.median, ys: timeline.rows, color: '#146f76' },
    { xs: profile.top10, ys: timeline.rows, color: '#b88122' },
  ], [timeline.x_min, timeline.x_max], rowDomain, `Horizontal image velocity (${timeline.units})`, 'Original image row (px)');
  renderBoundary(pair);
}

function renderBoundary(pair) {
  const chart = $('interface-chart');
  chart.replaceChildren();
  $('fallback').textContent = boundary?.runtime?.fallback_reason || '';
  if (!boundary) {
    $('interface-info').textContent = 'Load interface.json to inspect boundary positions and the recorded device. The generated motion example contains no AI prediction.';
    return;
  }
  const sample = interfaceSampleForPair(boundary, pair);
  const match = sample ? `Frame A boundary row: ${format(sample.median_row_px, 1)} px; accepted columns ${format(sample.coverage * 100, 1)}%.` : 'No boundary sample matches this frame A.';
  $('interface-info').textContent = `${boundary.frames.length} boundary samples. ${match} Review required. Confirm both JSON files belong to the same recording; frame IDs alone do not establish source identity.`;
  const haveTime = boundary.frames.every((frame) => frame.seconds_from_start !== null);
  const xs = boundary.frames.map((frame) => haveTime ? frame.seconds_from_start : frame.original_frame);
  const ys = boundary.frames.map((frame) => frame.median_row_px);
  const finiteY = ys.filter((value) => value !== null);
  if (!finiteY.length) {
    chart.append(element('text', { x: 40, y: 100 }, 'No accepted boundary positions. Missing detections are retained.'));
    return;
  }
  const minX = Math.min(...xs); const maxX = Math.max(...xs);
  const minY = Math.min(...finiteY); const maxY = Math.max(...finiteY);
  const pad = Math.max(5, (maxY - minY) * 0.1);
  drawChart(chart, [{ xs, ys, color: '#146f76' }], [minX, maxX === minX ? minX + 1 : maxX],
    [minY - pad, maxY + pad], haveTime ? 'Time from selection start (s)' : 'Original frame', 'Median boundary row (px; down)');
}

async function loadDemo() {
  const generation = ++loadingGeneration;
  $('error').hidden = true;
  try {
    const response = await fetch('./demo/timeline.json');
    if (!response.ok) throw new Error('Generate the example first: python scripts/demo.py');
    const data = validateTimeline(await response.json());
    if (generation !== loadingGeneration) return;
    clearImages(); imageBase = './demo/'; timeline = data; boundary = null; selected = 0; showB = false;
    $('notice').textContent = 'SYNTHETIC VALIDATION · Generated texture moves +2 px/source frame at 100 fps. Supplied scale 0.1 mm/px gives 0.020 m/s. This is a numerical check, not an experimental measurement.';
    render();
  } catch (error) { if (generation === loadingGeneration) showError(error); }
}

function showError(error) {
  $('error').textContent = error.message || 'Could not read the exported files.';
  $('error').hidden = false;
}

async function loadFiles(event) {
  const generation = ++loadingGeneration;
  const files = [...event.target.files];
  $('error').hidden = true;
  try {
    const motionFile = files.find((file) => file.name === 'timeline.json');
    const interfaceFile = files.find((file) => file.name === 'interface.json');
    if (!motionFile) throw new Error('Select timeline.json together with optional interface.json and preview images.');
    if (files.length > 1200 || motionFile.size > 20 * 1024 * 1024 || (interfaceFile?.size || 0) > 20 * 1024 * 1024)
      throw new Error('Export selection exceeds this viewer’s file/count limits.');
    const data = validateTimeline(JSON.parse(await motionFile.text()));
    const prediction = interfaceFile ? validateInterface(JSON.parse(await interfaceFile.text())) : null;
    if (generation !== loadingGeneration) return;
    const previews = files.filter((file) => safeImageName(file.name));
    if (new Set(previews.map((file) => file.name)).size !== previews.length)
      throw new Error('Preview filenames must be unique within one selection.');
    clearImages(); imageBase = null;
    previews.forEach((file) => imageFiles.set(file.name, URL.createObjectURL(file)));
    timeline = data; boundary = prediction; selected = 0; showB = false;
    $('notice').textContent = `LOCAL EXPORT · ${data.pairs.length} frame pairs loaded. Files stay in this browser. ${prediction ? 'Interface results are included; verify their source recording.' : 'Interface results were not selected.'}`;
    render();
  } catch (error) { if (generation === loadingGeneration) showError(error); }
  finally { event.target.value = ''; }
}

$('demo').addEventListener('click', loadDemo);
$('files').addEventListener('change', loadFiles);
$('pair').addEventListener('input', (event) => { selected = Number(event.target.value); showB = false; render(); });
$('previous').addEventListener('click', () => { selected = Math.max(0, selected - 1); showB = false; render(); });
$('next').addEventListener('click', () => { if (timeline) selected = Math.min(timeline.pairs.length - 1, selected + 1); showB = false; render(); });
$('toggle').addEventListener('click', () => { showB = !showB; render(); });
window.addEventListener('pagehide', clearImages);
loadDemo();
