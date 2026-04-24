from https://x.com/godofprompt/status/2041265656893489419

1. copy the template
2. If not using claude, rename CLAUDE.md to AGENTS.md
3. Customize the title and the focus areas in CLAUDE.md / AGENTS.ms
4. Dump resources into /raw
5. Process
	a) One source: "Read the schema in CLAUDE.md. Then process [FILENAME] from raw/. Read it fully, discuss key takeaways with me, then: create a summary page in wiki/, update wiki/index.md, update all relevant concept and entity pages, add backlinks, flag any contradictions, and append to wiki/log.md."
	b) Batch: "Read CLAUDE.md. Process all unprocessed files in raw/ sequentially. For each: create summary, update index, update relevant pages, log the ingest. Proceed automatically."
6. Query the knowledge base using claude, e.g., "Read wiki/index.md. Based on what's in the knowledge base, answer: [YOUR QUESTION]. Cite which wiki pages informed your answer. If this reveals new connections worth preserving, create a new page in wiki/ and update the index."
7. Run montly health checks: "Run a full health check on wiki/ per the lint workflow in CLAUDE.md. Output to wiki/lint-report-[date].md with severity levels (🔴 errors, 🟡 warnings, 🔵 info). Suggest 3 articles to fill the biggest knowledge gaps."