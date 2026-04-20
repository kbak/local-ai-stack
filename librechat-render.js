// Render librechat.yaml.template → librechat.yaml
//
// Substitutes ${VAR} placeholders with env vars. Special case: TIER1_MEMORY
// is built from /memory/USER.md + /memory/MEMORY.md (wrapped in XML tags,
// indented so it fits inside a YAML block-literal scalar).
//
// Expected usage in librechat.yaml.template:
//     promptPrefix: |
// ${TIER1_MEMORY}

const fs = require('fs');

function readIf(path) {
  try { return fs.readFileSync(path, 'utf8').trim(); }
  catch { return ''; }
}

function buildTier1(indent) {
  const user = readIf('/memory/USER.md');
  const mem = readIf('/memory/MEMORY.md');
  const blocks = [];
  if (user) blocks.push('<user_profile>\n' + user + '\n</user_profile>');
  if (mem) blocks.push('<memory>\n' + mem + '\n</memory>');
  if (blocks.length === 0) return '';
  // Indent every line so it nests correctly under `promptPrefix: |`
  const pad = ' '.repeat(indent);
  return blocks.join('\n\n').split('\n').map(l => pad + l).join('\n');
}

// For YAML block-literal under modelSpecs.list.preset.promptPrefix:
// modelSpecs(0) → list(2) → -(4)/name(6) → preset(6) → promptPrefix: |(8) → content(10).
const TIER1_INDENT = 10;
process.env.TIER1_MEMORY = buildTier1(TIER1_INDENT);

const template = fs.readFileSync('/app/librechat.yaml.template', 'utf8');
const rendered = template.replace(/\$\{([^}]+)\}/g, (_, k) => process.env[k] || '');
fs.writeFileSync('/app/librechat.yaml', rendered);

console.log('[render] librechat.yaml written. TIER1_MEMORY length:', process.env.TIER1_MEMORY.length);
