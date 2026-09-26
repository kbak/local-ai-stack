// Render librechat.yaml.template → librechat.yaml, and overwrite the 006
// agent's `instructions` field in Mongo with the current memory MD files.
//
// Why both: modelSpecs.promptPrefix carries ${TIER1_MEMORY} for legacy custom-
// endpoint chats, but the agents endpoint ignores promptPrefix — agents build
// their system prompt from the `instructions` field stored on the agent
// document. Memory instructions plus the LibreChat tool policy below refresh
// the Mongo field on every container start.
//
// Expected usage in librechat.yaml.template:
//     promptPrefix: |
// ${TIER1_MEMORY}

const fs = require('fs');

const AGENT_NAME = process.env.TIER1_AGENT_NAME || '006';
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/LibreChat';
// The agent's Mongo setting overrides the custom endpoint's YAML limit.
// Reserve 8192 for output and another 8192 for overhead/tokenizer differences
// below vLLM's 131072 total-token cap.
const AGENT_CONTEXT_LIMIT = 114688;
const TOOL_POLICY = `<librechat_tool_policy>
These LibreChat-specific tool rules override general encouragement to search in the memory instructions above.
Answer simple facts, explanations, estimates, and arithmetic directly when possible. Use tools when external information, user data, or an action is needed, or the user explicitly requests research.
For a simple lookup, normally use one search and at most one short page read, then answer. Stop when you have enough evidence. For estimates, state reasonable assumptions and calculate rather than researching every input to excessive precision.
Use arXiv for requests about papers or questions requiring scientific literature, not everyday facts or estimates.
For ordinary fetch calls, use raw=false and max_length of at most 5000 characters. Avoid full-document reads and repeated pagination unless the task requires them. After a tool error, make at most one corrected retry, then use available evidence and state any uncertainty.
Do more extensive research when requested or necessary for the task.
</librechat_tool_policy>`;

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
  const enableImageTools = process.env.LOCAL_IMAGE_TOOLS === 'true';
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
    const update = {};
    const baseInstructions = (instructions || doc.instructions || '')
      .replace(/\s*<librechat_tool_policy>[\s\S]*?<\/librechat_tool_policy>/g, '').trim();
    const agentInstructions = [baseInstructions, TOOL_POLICY].filter(Boolean).join('\n\n');
    if (doc.instructions !== agentInstructions) {
      update.$set = { instructions: agentInstructions };
    }
    const tools = (doc.tools ?? []).filter((tool) => !tool.endsWith('_mcp_finance'));
    if (enableImageTools && !tools.includes('image_gen_oai')) {
      // LibreChat expands this toolkit into generation and editing tools.
      tools.push('image_gen_oai');
    }
    if (JSON.stringify(tools) !== JSON.stringify(doc.tools ?? [])) {
      update.$set = { ...update.$set, tools };
    }
    const servers = (doc.mcpServerNames ?? []).filter((server) => server !== 'finance');
    if (JSON.stringify(servers) !== JSON.stringify(doc.mcpServerNames ?? [])) {
      update.$set = { ...update.$set, mcpServerNames: servers };
    }
    const currentLimit = Number(doc.model_parameters?.maxContextTokens);
    // Migrate our previous 64K default while preserving smaller custom budgets.
    if (!Number.isFinite(currentLimit) || currentLimit <= 0 || currentLimit === 65536 || currentLimit > AGENT_CONTEXT_LIMIT) {
      update.$set = { ...update.$set, 'model_parameters.maxContextTokens': AGENT_CONTEXT_LIMIT };
    }
    if (Object.keys(update).length === 0) {
      console.log(`[render] agent "${AGENT_NAME}" configuration already up to date.`);
      return;
    }
    update.$set = { ...update.$set, updatedAt: new Date() };
    await agents.updateOne(
      { _id: doc._id },
      update,
    );
    console.log(`[render] agent "${AGENT_NAME}" configuration updated; local image tools: ${enableImageTools}.`);
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
