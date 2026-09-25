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
  assert.deepEqual(writes[0].update.$set.tools, ['existing_tool', 'image_gen_oai']);
  assert.ok(writes[0].update.$set.instructions.startsWith('<memory>\nsaved\n</memory>'));
});

test('missing memory files do not erase saved instructions when enabling images', async () => {
  const writes = await runRenderer({ doc: { _id: 'agent', instructions: 'keep me', tools: [] } });
  assert.equal(writes.length, 1);
  assert.ok(writes[0].update.$set.instructions.startsWith('keep me\n\n'));
  assert.deepEqual(writes[0].update.$set.tools, ['image_gen_oai']);
});

test('enabling the toolkit twice is idempotent', async () => {
  const doc = { _id: 'agent', tools: ['image_gen_oai'], model_parameters: { maxContextTokens: 114688 } };
  const first = await runRenderer({ doc });
  Object.assign(doc, first[0].update.$set);
  assert.deepEqual(await runRenderer({ doc }), []);
});

test('memory refresh preserves the tools when image integration is disabled', async () => {
  const writes = await runRenderer({ doc: { _id: 'agent', tools: ['existing_tool'] }, memory: 'new memory', enabled: 'false' });
  assert.equal(writes.length, 1);
  assert.ok(writes[0].update.$set.instructions.startsWith('<memory>\nnew memory\n</memory>'));
  assert.equal(writes[0].update.$set.tools, undefined);
  assert.equal(writes[0].update.$addToSet, undefined);
});

test('does not create an agent when the configured agent is missing', async () => {
  assert.deepEqual(await runRenderer({ doc: null }), []);
});


test('removes finance while preserving arxiv and caps excessive agent context', async () => {
  const writes = await runRenderer({ doc: {
    _id: 'agent', tools: ['sys__server__sys_mcp_finance', 'get_stock_info_mcp_finance', 'search_papers_mcp_arxiv', 'fetch_mcp_fetch'],
    mcpServerNames: ['finance', 'arxiv', 'fetch'],
    model_parameters: { maxContextTokens: 262144, max_tokens: 8192 },
  } });
  const update = writes[0].update.$set;
  assert.deepEqual(update.tools, ['search_papers_mcp_arxiv', 'fetch_mcp_fetch', 'image_gen_oai']);
  assert.deepEqual(update.mcpServerNames, ['arxiv', 'fetch']);
  assert.equal(update['model_parameters.maxContextTokens'], 114688);
  assert.equal(update.model_parameters, undefined);
});

test('preserves a smaller context budget and replaces policy without duplication', async () => {
  const doc = { _id: 'agent', instructions: 'keep me', model_parameters: { maxContextTokens: 32768 } };
  const first = await runRenderer({ doc, enabled: 'false' });
  assert.equal(first[0].update.$set['model_parameters.maxContextTokens'], undefined);
  Object.assign(doc, first[0].update.$set);
  assert.equal(doc.instructions.split('<librechat_tool_policy>').length, 2);
  assert.deepEqual(await runRenderer({ doc, enabled: 'false' }), []);
});

test('migrates the deployed 64K budget without changing output allowance', async () => {
  const doc = { _id: 'agent', tools: ['image_gen_oai'], model_parameters: { maxContextTokens: 65536, max_tokens: 8192 } };
  const writes = await runRenderer({ doc });
  assert.equal(writes[0].update.$set['model_parameters.maxContextTokens'], 114688);
  assert.equal(writes[0].update.$set['model_parameters.max_tokens'], undefined);
  assert.equal(writes[0].update.$set.model_parameters, undefined);
});
