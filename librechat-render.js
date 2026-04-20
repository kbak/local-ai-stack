// Render librechat.yaml.template → librechat.yaml, and inject Tier 1 into the
// 006 agent's `instructions` field in Mongo.
//
// Why both: modelSpecs.promptPrefix carries ${TIER1_MEMORY} for legacy custom-
// endpoint chats, but the agents endpoint ignores promptPrefix — agents build
// their system prompt from the `instructions` field stored on the agent
// document. To keep Tier 1 automated (the whole point), we also upsert the
// same block into the agent's instructions on every container start, inside a
// managed <!-- TIER1:START --> ... <!-- TIER1:END --> region so the human-
// authored persona below it is preserved.
//
// Expected usage in librechat.yaml.template:
//     promptPrefix: |
// ${TIER1_MEMORY}

const fs = require('fs');

const TIER1_START = '<!-- TIER1:START -->';
const TIER1_END = '<!-- TIER1:END -->';
const AGENT_NAME = process.env.TIER1_AGENT_NAME || '006';
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/LibreChat';

function readIf(path) {
  try { return fs.readFileSync(path, 'utf8').trim(); }
  catch { return ''; }
}

// Raw (unindented) Tier 1 block — used for the agent instructions field.
function buildTier1Raw() {
  const user = readIf('/memory/USER.md');
  const mem = readIf('/memory/MEMORY.md');
  const blocks = [];
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
const tier1Raw = buildTier1Raw();
process.env.TIER1_MEMORY = indent(tier1Raw, TIER1_INDENT);

const template = fs.readFileSync('/app/librechat.yaml.template', 'utf8');
const rendered = template.replace(/\$\{([^}]+)\}/g, (_, k) => process.env[k] || '');
fs.writeFileSync('/app/librechat.yaml', rendered);

console.log('[render] librechat.yaml written. TIER1_MEMORY length:', process.env.TIER1_MEMORY.length);

// Replace the managed block inside `instructions`, or prepend it if markers
// are missing. Returns the new instructions string.
function applyTier1(current, tier1Block) {
  const managed = tier1Block
    ? `${TIER1_START}\n${tier1Block}\n${TIER1_END}`
    : `${TIER1_START}\n${TIER1_END}`;
  if (current.includes(TIER1_START) && current.includes(TIER1_END)) {
    const re = new RegExp(`${TIER1_START}[\\s\\S]*?${TIER1_END}`);
    return current.replace(re, managed);
  }
  // No markers yet — prepend, with a blank line separating from the base.
  return `${managed}\n\n${current}`;
}

async function patchAgentInstructions() {
  if (!tier1Raw) {
    console.log('[render] Tier 1 is empty — skipping agent patch.');
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
    const current = typeof doc.instructions === 'string' ? doc.instructions : '';
    const next = applyTier1(current, tier1Raw);
    if (next === current) {
      console.log(`[render] agent "${AGENT_NAME}" instructions already up to date.`);
      return;
    }
    await agents.updateOne(
      { _id: doc._id },
      { $set: { instructions: next, updatedAt: new Date() } },
    );
    console.log(
      `[render] agent "${AGENT_NAME}" instructions patched. Tier 1 block: ${tier1Raw.length} chars, total: ${next.length} chars.`,
    );
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
