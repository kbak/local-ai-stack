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

// Custom OpenAI-compatible models (including vLLM) cannot consume LibreChat's
// native `{type: "file"}` PDF blocks. For Agents, turn local PDF attachments
// into references for our pdf-inspector MCP server and keep the raw document
// out of the provider payload. The attachment remains on the message/UI.
function patchAgentPdfAttachments() {
  const path = '/app/api/server/controllers/agents/client.js';
  const source = fs.readFileSync(path, 'utf8');
  const marker = 'PDF_INSPECTOR_UPLOAD_BRIDGE';
  if (source.includes(marker)) {
    console.log('[render] PDF attachment bridge already installed.');
    return;
  }

  const needle = `  checkVisionRequest() {}

  getSaveOptions() {`;
  const replacement = `  checkVisionRequest() {}

  // PDF_INSPECTOR_UPLOAD_BRIDGE: vLLM has no native file content part. Keep
  // local PDFs as message attachments, expose safe paths to the MCP tool, and
  // remove the binary documents from every provider request (including resend).
  getPdfInspectorAttachments(attachments) {
    return (attachments ?? []).filter(
        (file) =>
          file?.source === 'local' &&
          file?.type === 'application/pdf' &&
          typeof file?.filepath === 'string' &&
          file.filepath.startsWith('/uploads/') &&
          !file.filepath.includes('..'),
    );
  }

  async addFileContextToMessage(message, attachments) {
    await super.addFileContextToMessage(message, attachments);
    const refs = this.getPdfInspectorAttachments(attachments)
      .map(
        (file) =>
          '[Attached PDF "' + file.filename + '". Read it with the pdf-inspector MCP read_pdf tool using source="' + file.filepath + '" before answering. Start with pages 1-10 and continue in page ranges as needed.]',
      )
      .join('\\n');
    if (refs) {
      message.fileContext = [message.fileContext, refs].filter(Boolean).join('\\n\\n');
    }
  }

  async processAttachments(message, attachments) {
    const mcpPdfs = this.getPdfInspectorAttachments(attachments);
    const providerAttachments = (attachments ?? []).filter((file) => !mcpPdfs.includes(file));
    const files = await super.processAttachments(message, providerAttachments);
    return [...files, ...mcpPdfs];
  }

  getSaveOptions() {`;

  if (!source.includes(needle)) {
    throw new Error('LibreChat Agents attachment hook changed; PDF bridge was not applied');
  }
  fs.writeFileSync(path, source.replace(needle, replacement));
  console.log('[render] PDF attachment bridge installed.');
}

patchAgentPdfAttachments();

// LibreChat's "Upload as Text" normally expands an entire PDF into the first
// prompt. Large papers can consume the whole context window before the model
// runs. Preserve Agent PDF uploads as local files instead so both attachment
// choices use the page-ranged pdf-inspector MCP bridge above.
function patchPdfUploadAsText() {
  const path = '/app/api/server/services/Files/process.js';
  const source = fs.readFileSync(path, 'utf8');
  const marker = 'PDF_INSPECTOR_CONTEXT_UPLOAD';
  if (source.includes(marker)) {
    console.log('[render] PDF Upload-as-Text redirect already installed.');
    return;
  }

  const needle = '} else if (tool_resource === EToolResources.context) {';
  const replacement = `} else if (
    tool_resource === EToolResources.context &&
    // PDF_INSPECTOR_CONTEXT_UPLOAD: retain PDFs for page-ranged MCP reading.
    file.mimetype !== 'application/pdf'
  ) {`;
  if (!source.includes(needle)) {
    throw new Error('LibreChat context-upload hook changed; PDF redirect was not applied');
  }
  fs.writeFileSync(path, source.replace(needle, replacement));
  console.log('[render] PDF Upload-as-Text redirect installed.');
}

patchPdfUploadAsText();

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
