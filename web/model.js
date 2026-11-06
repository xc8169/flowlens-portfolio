/** Validation and plotting helpers shared by the browser and Node's tests.
 * Null means missing scientific evidence, never a measured zero.
 */
const MAX_PAIRS = 200;
const MAX_ROWS = 10000;

function check(condition, message) {
  if (!condition) throw new Error(message);
}

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const nullable = (value) => value === null || finite(value);
const index = (value) => Number.isSafeInteger(value) && value >= 0;
const fraction = (value) => finite(value) && value >= 0 && value <= 1;

export function safeImageName(value) {
  return typeof value === 'string' && /^[a-zA-Z0-9_-]+\.(jpg|jpeg|png)$/i.test(value);
}

export function validateTimeline(data) {
  check(data && typeof data === 'object', 'Expected a FlowLens timeline object.');
  check(Array.isArray(data.rows) && data.rows.length > 0 && data.rows.length <= MAX_ROWS,
    'Timeline must contain 1–10000 image rows.');
  check(data.rows.every(finite), 'Image rows must be finite numbers.');
  check(data.rows.every((row, i) => i === 0 || row > data.rows[i - 1]), 'Image rows must increase.');
  check(Array.isArray(data.pairs) && data.pairs.length > 0 && data.pairs.length <= MAX_PAIRS,
    'Timeline must contain 1–200 frame pairs.');
  check(Array.isArray(data.profiles) && data.profiles.length === data.pairs.length,
    'Each frame pair must have one profile.');
  check(typeof data.physical_units === 'boolean', 'Physical-unit status is required.');
  check(data.units === (data.physical_units ? 'm/s' : 'px / source frame'), 'Units disagree with calibration status.');
  check(finite(data.x_min) && finite(data.x_max) && data.x_min < data.x_max, 'Invalid fixed profile limits.');
  data.pairs.forEach((pair) => {
    check(index(pair.frame_a) && index(pair.frame_b) && pair.frame_b > pair.frame_a, 'Invalid frame pair.');
    check(index(pair.original_frame_a) && index(pair.original_frame_b), 'Original frame IDs are required.');
    check(nullable(pair.midpoint_seconds_from_start), 'Invalid pair time.');
    check(nullable(pair.median_dx_px_per_source_frame) && nullable(pair.velocity_m_per_s), 'Invalid motion measurement.');
    check(data.physical_units || pair.velocity_m_per_s === null, 'Uncalibrated results cannot contain physical velocity.');
    check(fraction(pair.texture_coverage), 'Invalid texture coverage.');
    ['frame_preview', 'frame_b_preview', 'vector_preview'].forEach((key) => {
      check(safeImageName(pair[key]), 'Preview images must use plain local filenames.');
    });
  });
  data.profiles.forEach((profile) => {
    ['median', 'top10', 'coverage'].forEach((key) => {
      check(Array.isArray(profile[key]) && profile[key].length === data.rows.length, 'Profile length differs from image rows.');
      check(profile[key].every(key === 'coverage' ? fraction : nullable), 'Invalid profile value.');
    });
  });
  return data;
}

export function validateInterface(data) {
  check(data && Array.isArray(data.frames) && data.frames.length > 0 && data.frames.length <= MAX_PAIRS,
    'Interface result must contain 1–200 samples.');
  data.frames.forEach((frame) => {
    check(index(frame.frame) && index(frame.original_frame), 'Invalid interface frame ID.');
    check(nullable(frame.seconds_from_start) && nullable(frame.median_row_px), 'Invalid interface position or time.');
    check(fraction(frame.coverage), 'Invalid accepted-column coverage.');
    check(Array.isArray(frame.x) && Array.isArray(frame.y) && frame.x.length === frame.y.length && frame.x.length <= MAX_ROWS,
      'Invalid boundary coordinate arrays.');
    check(frame.x.every(finite) && frame.y.every(nullable), 'Invalid boundary coordinates.');
  });
  return data;
}

/** Separate segments ensure an SVG line never bridges null measurements. */
export function segments(xs, ys) {
  const answer = [];
  let current = [];
  for (let i = 0; i < Math.min(xs.length, ys.length); i += 1) {
    if (finite(xs[i]) && finite(ys[i])) current.push([xs[i], ys[i]]);
    else if (current.length) { answer.push(current); current = []; }
  }
  if (current.length) answer.push(current);
  return answer;
}

export function interfaceSampleForPair(result, pair) {
  // The desktop detector samples frame A. Never interpolate across unmatched frames.
  return result?.frames.find((frame) => frame.original_frame === pair.original_frame_a) ?? null;
}

export function recordedDevice(result) {
  const runtime = result?.runtime;
  if (!runtime) return 'Not recorded';
  if (runtime.device === 'cuda') return runtime.device_name || 'CUDA GPU';
  if (runtime.device === 'cpu') return 'CPU';
  return 'Not recorded';
}
