import test from 'node:test';
import assert from 'node:assert/strict';
import {buildColorStops, buildHsvColorStops} from './static/color-strip.mjs';

function answer(name, value) {
  return {name, score: value / 100};
}

test('builds twelve ordered RGB bars from yes probabilities', () => {
  const results = [];
  for (let stop = 12; stop >= 1; stop--)
    for (const [channel, offset] of [['b', 30], ['r', 10], ['g', 20]])
      results.push(answer(`stop_${String(stop).padStart(2, '0')}_${channel}`, stop + offset));
  const stops = buildColorStops(results);
  assert.equal(stops.length, 12);
  assert.deepEqual(stops[0], {
    index: 1, red: 11, green: 21, blue: 31,
    css: 'rgb(28, 54, 79)', ink: '#fff5e6',
  });
  assert.equal(stops[11].index, 12);
  assert.deepEqual([stops[11].red, stops[11].green, stops[11].blue], [22, 32, 42]);
});

test('omits incomplete stops and ignores unrelated answers', () => {
  const results = [answer('stop_01_r', 20), answer('stop_01_g', 30),
    answer('other', 100), answer('stop_99_b', 40)];
  assert.deepEqual(buildColorStops(results), []);
});

test('builds HSV bars from a hue choice and yes probabilities', () => {
  const results = [
    {name:'stop_01_h', choice:'blue'},
    {name:'stop_01_s', score:.5},
    {name:'stop_01_v', score:.8},
  ];
  assert.deepEqual(buildHsvColorStops(results), [{
    index:1, hueName:'blue', hue:240, saturation:50, value:80,
    css:'rgb(102, 102, 204)', ink:'#fff5e6',
  }]);
});

test('rejects unknown hue choices and incomplete HSV bars', () => {
  assert.deepEqual(buildHsvColorStops([
    {name:'stop_01_h', choice:'infrared'},
    {name:'stop_01_s', score:.8},
    {name:'stop_01_v', score:.8},
  ]), []);
});

test('builds the HSV icon from twelve row-major pixel triplets', () => {
  const results = [];
  for (let pixel = 1; pixel <= 12; pixel++) {
    const name = `pixel_${String(pixel).padStart(2, '0')}`;
    results.push({name:`${name}_h`, choice:pixel % 2 ? 'yellow' : 'blue'});
    results.push({name:`${name}_s`, score:.75});
    results.push({name:`${name}_v`, score:.8});
  }
  const pixels = buildHsvColorStops(results);
  assert.equal(pixels.length, 12);
  assert.deepEqual(pixels.map(pixel => pixel.index), [1,2,3,4,5,6,7,8,9,10,11,12]);
  assert.equal(pixels[0].css, 'rgb(204, 204, 51)');
  assert.equal(pixels[1].css, 'rgb(51, 51, 204)');
});
