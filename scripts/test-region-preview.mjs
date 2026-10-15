import assert from 'node:assert/strict';
import { regionPreviewBars } from '../apps/studio-web/src/features/arrangement/region-preview.js';

const clip = {start_beats: 16, duration_beats: 8, notes: [
  {pitch: 60, start_beats: 17, duration_beats: 0.5},
  {pitch: 64, start_beats: 20, duration_beats: 1},
]};
const before = structuredClone(clip);
const original = regionPreviewBars(clip, 32);
assert.match(original, /left:32\.000px;.*width:16\.000px/);
assert.match(original, /left:128\.000px;.*width:32\.000px/);
assert.equal(regionPreviewBars({...clip, duration_beats: 16}, 32), original);
assert.equal(regionPreviewBars({...clip, duration_beats: 2}, 32), original);
assert.match(regionPreviewBars(clip, 64), /left:64\.000px;.*width:32\.000px/);
assert.equal(regionPreviewBars({start_beats: 0, notes: []}, 32), '');
assert.match(regionPreviewBars({start_beats: 16, notes: [
  {pitch: 0, start_beats: 15, duration_beats: 2},
]}, 32), /left:-32\.000px;.*width:64\.000px/);
assert.deepEqual(clip, before);
console.log('PASS: clip length does not stretch preview timing; timeline zoom does; crop/empty/low-note handling; source unchanged');
