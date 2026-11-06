import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateTimeline, validateInterface, segments, interfaceSampleForPair, recordedDevice, safeImageName } from '../model.js';

const fixture = () => JSON.parse(readFileSync(new URL('../demo/timeline.json', import.meta.url), 'utf8'));

test('the committed example validates and has known positive translation', () => {
  const data = validateTimeline(fixture());
  assert.equal(data.units, 'm/s');
  assert.equal(data.pairs.length, 12);
  for (const pair of data.pairs) assert.ok(Math.abs(pair.median_dx_px_per_source_frame - 2) < 0.15);
});

test('missing values remain gaps, while a measured zero is retained', () => {
  assert.deepEqual(segments([0, 1, 2, 3, 4], [0, null, 2, 3, null]), [[[0, 0]], [[2, 2], [3, 3]]]);
});

test('wrong units and uncalibrated physical measurements are rejected', () => {
  const data = fixture(); data.physical_units = false;
  assert.throws(() => validateTimeline(data), /Units/);
  data.units = 'px / source frame';
  assert.throws(() => validateTimeline(data), /Uncalibrated/);
});

test('profile length, finite values and texture coverage are checked', () => {
  const data = fixture(); data.profiles[0].median.pop();
  assert.throws(() => validateTimeline(data), /length/);
  const bad = fixture(); bad.profiles[0].median[0] = Infinity;
  assert.throws(() => validateTimeline(bad), /profile value/);
  const coverage = fixture(); coverage.pairs[0].texture_coverage = 4;
  assert.throws(() => validateTimeline(coverage), /coverage/);
});

test('external and traversal image paths are rejected', () => {
  for (const path of ['../frame.jpg', 'https://example.com/frame.jpg', 'file:///secret.png', '<img>.jpg'])
    assert.equal(safeImageName(path), false);
  assert.equal(safeImageName('pair-0000-a.jpg'), true);
  const data = fixture(); data.pairs[0].frame_preview = '../frame.jpg';
  assert.throws(() => validateTimeline(data), /local filenames/);
});

test('boundary samples match original frame A exactly, without interpolation', () => {
  const frame = { frame: 0, original_frame: 100, seconds_from_start: 0, median_row_px: null, coverage: 0, x: [0, 1], y: [null, null] };
  const result = validateInterface({ frames: [frame] });
  assert.equal(interfaceSampleForPair(result, { original_frame_a: 100 }), frame);
  assert.equal(interfaceSampleForPair(result, { original_frame_a: 101 }), null);
  assert.equal(recordedDevice(result), 'Not recorded');
  assert.equal(recordedDevice({ runtime: { device: 'cuda', device_name: 'RTX 4090' } }), 'RTX 4090');
  assert.equal(recordedDevice({ runtime: { device: 'cpu' } }), 'CPU');
});

test('invalid boundary arrays and oversized motion inputs fail before rendering', () => {
  assert.throws(() => validateInterface({ frames: [{ frame: 0, original_frame: 0, seconds_from_start: 0, median_row_px: 10, coverage: 1, x: [1, 2], y: [10] }] }), /coordinate arrays/);
  const data = fixture(); data.pairs = Array(201).fill(data.pairs[0]);
  assert.throws(() => validateTimeline(data), /1–200/);
});
