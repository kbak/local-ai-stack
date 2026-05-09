// Render librechat.yaml.template → librechat.yaml, and overwrite the 006
// agent's `instructions` field in Mongo with the current memory MD files.
//
// Why both: modelSpecs.promptPrefix carries ${TIER1_MEMORY} for legacy custom-
// endpoint chats, but the agents endpoint ignores promptPrefix — agents build
// their system prompt from the `instructions` field stored on the agent
// document. All instructions live in the memory MD files; the Mongo field is
// fully overwritten on every container start.
//
// Expected usage in librechat.yaml.template:
//     promptPrefix: |
// ${TIER1_MEMORY}

const fs = require('fs');

const AGENT_NAME = process.env.TIER1_AGENT_NAME || '006';
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/LibreChat';

function readIf(path) {
  try { return fs.readFileSync(path, 'utf8').trim(); }
  catch { return ''; }
}

function buildInstructions() {
  const soul = readIf('/memory/SOUL.md');
  const user = readIf('/memory/USER.md');
  const mem = readIf('/memory/MEMORY.md');
  const blocks = [];
  if (soul) blocks.push('<soul>\n' + soul + '\n</soul>');
  if (user) blocks.push('<user_profile>\n' + user + '\n</user_profile>');
  if (mem) blocks.push('<memory>\n' + mem + '\n</memory>');
  return blocks.join('\n\n');
}

// Indented variant — used for YAML block-literal injection into modelSpecs.
function indent(raw, n) {
  if (!raw) return '';
  const pad = ' '.repeat(n);
  return raw.split('\n').map(l => pad + l).join('\n');
}

// For YAML block-literal under modelSpecs.list.preset.promptPrefix:
// modelSpecs(0) → list(2) → -(4)/name(6) → preset(6) → promptPrefix: |(8) → content(10).
const TIER1_INDENT = 10;
const instructions = buildInstructions();
process.env.TIER1_MEMORY = indent(instructions, TIER1_INDENT);

const template = fs.readFileSync('/app/librechat.yaml.template', 'utf8');
const rendered = template.replace(/\$\{([^}]+)\}/g, (_, k) => process.env[k] || '');
fs.writeFileSync('/app/librechat.yaml', rendered);

console.log('[render] librechat.yaml written. TIER1_MEMORY length:', process.env.TIER1_MEMORY.length);

async function patchAgentInstructions() {
  if (!instructions) {
    console.log('[render] instructions empty — skipping agent patch.');
    return;
  }
  let MongoClient;
  try {
    ({ MongoClient } = require('mongodb'));
  } catch (e) {
    console.error('[render] mongodb driver not available:', e.message);
    return;
  }
  const client = new MongoClient(MONGO_URI, { serverSelectionTimeoutMS: 5000 });
  try {
    await client.connect();
    const db = client.db();
    const agents = db.collection('agents');
    const doc = await agents.findOne({ name: AGENT_NAME });
    if (!doc) {
      console.warn(`[render] agent "${AGENT_NAME}" not found — nothing patched.`);
      return;
    }
    if (doc.instructions === instructions) {
      console.log(`[render] agent "${AGENT_NAME}" instructions already up to date.`);
      return;
    }
    await agents.updateOne(
      { _id: doc._id },
      { $set: { instructions, updatedAt: new Date() } },
    );
    console.log(`[render] agent "${AGENT_NAME}" instructions updated. Length: ${instructions.length} chars.`);
  } catch (e) {
    console.error('[render] failed to patch agent instructions:', e.message);
  } finally {
    await client.close().catch(() => {});
  }
}

patchAgentInstructions()
  .catch((e) => {
    console.error('[render] unexpected error in patchAgentInstructions:', e);
  })
  .finally(() => {
    // The yaml has already been written synchronously above, so exiting here
    // is safe regardless of whether the Mongo patch succeeded. This keeps the
    // container entrypoint (`node render.js && exec node server.js`) moving
    // even if Mongo is briefly unreachable.
    process.exit(0);
  });
