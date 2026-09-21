// Exercise the startup agent update without connecting to a real database.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'librechat-render.js'), 'utf8');

async function runRenderer({ doc, memory = '', enabled = 'true' }) {
  const writes = [];
  const files = {
    '/memory/MEMORY.md': memory,
    '/app/librechat.yaml.template': 'version: 1.3.6',
    '/app/api/server/controllers/agents/client.js': 'PDF_INSPECTOR_UPLOAD_BRIDGE',
    '/app/api/server/services/Files/process.js': 'PDF_INSPECTOR_CONTEXT_UPLOAD',
  };
  let finish;
  const done = new Promise((resolve) => { finish = resolve; });
  class MongoClient {
    async connect() {}
    db() {
      return {
        collection: () => ({
          findOne: async () => doc,
          updateOne: async (filter, update) => {
            writes.push(JSON.parse(JSON.stringify({ filter, update })));
          },
        }),
      };
    }
    async close() {}
  }
  vm.runInNewContext(source, {
    require(name) {
      if (name === 'mongodb') return { MongoClient };
      assert.equal(name, 'fs');
      return {
        readFileSync: (filename) => files[filename] || '',
        writeFileSync: (filename, contents) => { files[filename] = contents; },
      };
    },
    process: { env: { LOCAL_IMAGE_TOOLS: enabled }, exit: finish },
    console: { log() {}, warn() {}, error: (...args) => { throw new Error(args.join(' ')); } },
  });
  await done;
  return writes;
}

test('enables images even when memory instructions are already current', async () => {
  const writes = await runRenderer({
    doc: { _id: 'agent', instructions: '<memory>\nsaved\n</memory>', tools: ['existing_tool'] },
    memory: 'saved',
  });
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0].filter, { _id: 'agent' });
  assert.deepEqual(writes[0].update.$addToSet, { tools: 'image_gen_oai' });
  assert.equal(writes[0].update.$set.instructions, undefined);
  assert.equal(writes[0].update.$set.tools, undefined);
});

test('missing memory files do not erase saved instructions when enabling images', async () => {
  const writes = await runRenderer({ doc: { _id: 'agent', instructions: 'keep me', tools: [] } });
  assert.equal(writes.length, 1);
  assert.equal(writes[0].update.$set.instructions, undefined);
  assert.deepEqual(writes[0].update.$addToSet, { tools: 'image_gen_oai' });
});

test('enabling the toolkit twice is idempotent', async () => {
  const writes = await runRenderer({ doc: { _id: 'agent', tools: ['image_gen_oai'] } });
  assert.deepEqual(writes, []);
});

test('memory refresh preserves the tools when image integration is disabled', async () => {
  const writes = await runRenderer({ doc: { _id: 'agent', tools: ['existing_tool'] }, memory: 'new memory', enabled: 'false' });
  assert.equal(writes.length, 1);
  assert.equal(writes[0].update.$set.instructions, '<memory>\nnew memory\n</memory>');
  assert.equal(writes[0].update.$addToSet, undefined);
});

test('does not create an agent when the configured agent is missing', async () => {
  assert.deepEqual(await runRenderer({ doc: null }), []);
});
