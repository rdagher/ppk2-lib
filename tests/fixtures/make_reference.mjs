#!/usr/bin/env node
// Regenerate parsed_poweron.csv by running Nordic's own parser, from a
// pc-nrfconnect-ppk checkout, on stream_poweron.bin (see README.md):
//
//     node tests/fixtures/make_reference.mjs /path/to/pc-nrfconnect-ppk
import { readFileSync, writeFileSync } from 'node:fs';
import { register } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const nordic = resolve(process.argv[2] ?? 'pc-nrfconnect-ppk');

register('./nordic_hooks.mjs', import.meta.url);
const { default: SerialDevice } = await import(
    pathToFileURL(join(nordic, 'src/device/serialDevice.ts')).href
);

const samples = [];
const device = new SerialDevice({ serialPorts: [] }, sample => samples.push(sample));

// Their metadata path: request it, then hand the parser they install
// the response captured from the device.
const metadata = device.getMetadata();
device.parser(readFileSync(join(here, 'metadata.raw')));
device.parseMeta(await metadata);

await device.ppkUpdateRegulator(3300); // the supply voltage the stream was captured at
await device.ppkAverageStart(); // fresh spike-filter and counter state
device.parser(readFileSync(join(here, 'stream_poweron.bin')));

const rows = samples.map(
    ({ value, bits }, i) => `${(i * 0.01).toFixed(2)},${value.toFixed(3)},${bits}`,
);
writeFileSync(
    join(here, 'parsed_poweron.csv'),
    `Timestamp(ms),Current(uA),Logic\n${rows.join('\n')}\n`,
);
console.log(`parsed_poweron.csv: ${samples.length} samples`);
