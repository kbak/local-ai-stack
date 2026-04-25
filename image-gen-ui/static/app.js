/* image-gen-ui — chat-style frontend over the SwarmUI v0.9.8 API.
 * Talks to SwarmUI on the same host, port 7801. No auth.
 * History is persisted in localStorage so refreshes don't lose work.
 */
(() => {
    "use strict";

    // ── Config ──────────────────────────────────────────────────────────
    // The frontend and the SwarmUI API are exposed under the same origin
    // (nginx in image-gen-ui reverse-proxies /api/* and /view/* to the
    // image-gen container on the internal Docker network). Same-origin =>
    // no CORS, no preflight, no Settings.fds gymnastics.
    const API_BASE       = `${location.origin}/api`;
    const WS_BASE        = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api`;
    const LLM_BASE       = `${location.origin}/llm`;
    const STORAGE_KEY    = "imagegen-history-v1";
    const MAX_HISTORY    = 60;

    // Prompt-expansion system prompt. Tuned for Flux.1-dev, which prefers
    // naturalistic descriptions over Booru-style tag dumps.
    const EXPAND_SYSTEM = [
        "You rewrite short image ideas into detailed prompts for the Flux.1-dev image model.",
        "Output ONLY the prompt — no preamble, no quotes, no explanation, no trailing notes.",
        "Write 2-4 sentences. Cover: subject, setting, lighting, mood, and a photographic or artistic style cue (e.g. lens, film stock, medium).",
        "Use naturalistic prose, not comma-separated tags.",
        "Do not invent details that contradict the user's idea. If the user already wrote a long prompt, refine and tighten it; do not replace it wholesale.",
    ].join(" ");
    const EXPAND_TEMPERATURE = 0.7;
    const EXPAND_MAX_TOKENS  = 400;

    // Flux.1-dev requires distinct parameters from SDXL/SD1.5:
    //  - cfgscale MUST be 1 (Flux is distilled; CFG > 1 destroys quality).
    //  - The actual "creativity dial" for Flux is fluxguidancescale (~3.5).
    //  - Euler + simple scheduler are the recommended pair.
    //  - Use width/height (verified via direct API call); avoid rawresolution
    //    and aspectratio, which can produce thumbnail outputs on the WS path.
    //  - txxlmodel + cliplmodel are required when running the SEPARATED Flux
    //    weights (UNet only, with external T5-XXL + CLIP-L). Without them
    //    SwarmUI silently falls back to whatever encoders are bundled in
    //    the diffusion model file — and the Comfy-Org separated build has
    //    none, so prompts get encoded with nothing useful and quality tanks.
    const GEN_PARAMS = {
        images:             4,
        width:              1024,
        height:             1024,
        steps:              24,
        cfgscale:           1,
        fluxguidancescale:  3.5,
        sampler:            "euler",
        scheduler:          "simple",
        txxlmodel:          "t5xxl_fp8_e4m3fn",
        cliplmodel:         "clip_l",
        // Main "model" is resolved from /API/ListT2IParams at boot.
    };

    // ── DOM ─────────────────────────────────────────────────────────────
    const feed       = document.getElementById("feed");
    const composer   = document.getElementById("composer");
    const promptEl   = document.getElementById("prompt");
    const genBtn     = document.getElementById("genBtn");
    const expandBtn  = document.getElementById("expandBtn");
    const modelBtn   = document.getElementById("modelBtn");
    const modelLabel = modelBtn.querySelector(".model-label");
    const clearBtn   = document.getElementById("clearBtn");
    const lightbox   = document.getElementById("lightbox");
    const lightImg   = document.getElementById("lightboxImg");

    // ── State ───────────────────────────────────────────────────────────
    let sessionId    = null;
    let modelName    = null;
    let busy         = false;
    let activeSocket = null;
    let activeTiles  = null;
    let userAborted  = false;
    let expanding    = false;
    let expandAbort  = null;
    let modelLoaded  = null;   // null = unknown, true/false once we've polled.
    let modelWorking = false;
    let modelPollTimer = null;

    // ── History persistence ─────────────────────────────────────────────
    function loadHistory() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch {
            return [];
        }
    }

    function saveHistory(turns) {
        try {
            const trimmed = turns.slice(-MAX_HISTORY);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
        } catch {
            // Storage may be full; non-fatal.
        }
    }

    // History is stored as: [{ prompt, images: [absoluteUrl, ...] }]
    let history = loadHistory();

    function pushTurn(turn) {
        history.push(turn);
        saveHistory(history);
    }

    function updateLastTurnImages(images) {
        if (!history.length) return;
        history[history.length - 1].images = images;
        saveHistory(history);
    }

    // ── Lightbox ────────────────────────────────────────────────────────
    function openLightbox(src) {
        lightImg.src = src;
        lightbox.showModal();
    }

    lightbox.addEventListener("click", () => lightbox.close());
    lightbox.addEventListener("close", () => { lightImg.src = ""; });

    // ── Render ──────────────────────────────────────────────────────────
    /** Build a turn DOM node. tilesData = [{src?, pending}]. */
    function renderTurn(prompt, tilesData) {
        const turn = document.createElement("section");
        turn.className = "turn";

        const promptDiv = document.createElement("div");
        promptDiv.className = "prompt";
        promptDiv.textContent = prompt;
        turn.appendChild(promptDiv);

        const grid = document.createElement("div");
        grid.className = "grid";
        for (const data of tilesData) {
            grid.appendChild(makeTile(data));
        }
        turn.appendChild(grid);
        return turn;
    }

    function makeTile({ src, pending }) {
        const tile = document.createElement("div");
        tile.className = "tile" + (pending ? " pending" : "");
        if (src) {
            const img = document.createElement("img");
            img.src = src;
            img.alt = "";
            img.loading = "lazy";
            img.addEventListener("click", () => openLightbox(src));
            tile.appendChild(img);
        } else if (pending) {
            const bar = document.createElement("div");
            bar.className = "progress";
            tile.appendChild(bar);
        }
        return tile;
    }

    function fillTile(tile, src) {
        tile.classList.remove("pending");
        tile.innerHTML = "";
        const img = document.createElement("img");
        img.src = src;
        img.alt = "";
        img.loading = "lazy";
        img.addEventListener("click", () => openLightbox(src));
        tile.appendChild(img);
    }

    function setTileProgress(tile, percent) {
        let bar = tile.querySelector(".progress");
        if (!bar) return;
        bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    }

    function setTilePreview(tile, dataUri) {
        // Show a preview image without removing the shimmer/progress bar yet.
        let img = tile.querySelector("img");
        if (!img) {
            img = document.createElement("img");
            img.alt = "";
            tile.insertBefore(img, tile.firstChild);
        }
        img.src = dataUri;
    }

    function scrollFeedToBottom() {
        feed.scrollTop = feed.scrollHeight;
    }

    function renderHistory() {
        feed.innerHTML = "";
        for (const turn of history) {
            const node = renderTurn(
                turn.prompt,
                turn.images.map((src) => ({ src, pending: false }))
            );
            feed.appendChild(node);
        }
        scrollFeedToBottom();
    }

    // ── SwarmUI API ─────────────────────────────────────────────────────
    async function getSession() {
        const resp = await fetch(`${API_BASE}/GetNewSession`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
        });
        if (!resp.ok) throw new Error(`GetNewSession ${resp.status}`);
        const data = await resp.json();
        if (!data.session_id) throw new Error("GetNewSession returned no session_id");
        return data.session_id;
    }

    /** SwarmUI's ListT2IParams returns each model entry as a 2-tuple
     *  [path, displayTitle], e.g. ["Flux/flux1-dev-fp8.safetensors", "Flux.1-dev"].
     *  Older / different builds may use a bare string or an object — handle
     *  all three. The API's "model" param wants just the bare path, no extension.
     */
    function normalizeModelName(entry) {
        if (!entry) return null;
        let name = null;
        if (Array.isArray(entry)) {
            name = entry[0];
        } else if (typeof entry === "string") {
            name = entry;
        } else if (typeof entry === "object") {
            name = entry.name || entry.id || entry.path || entry.value || entry.model || null;
        }
        if (typeof name !== "string") return null;
        const pipe = name.indexOf("|||");
        if (pipe >= 0) name = name.slice(0, pipe);
        name = name.trim().replace(/\.(safetensors|ckpt|pt|pth|gguf)$/i, "");
        return name || null;
    }

    function entryMatchesFlux(entry) {
        return /flux/i.test(JSON.stringify(entry));
    }

    async function listModels(session) {
        const resp = await fetch(`${API_BASE}/ListT2IParams`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: session }),
        });
        if (!resp.ok) throw new Error(`ListT2IParams ${resp.status}`);
        const data = await resp.json();
        const sd = data?.models?.["Stable-Diffusion"] || [];
        console.log("ListT2IParams Stable-Diffusion entries:", sd);
        if (!sd.length) {
            throw new Error("SwarmUI has no models registered yet — drop weights into IMAGE_DIR and restart image-gen.");
        }
        // REQUIRE the SEPARATED build (file lives at the root of Models/,
        // e.g. "flux1-dev-fp8.safetensors"). The all-in-one bundle in a
        // subfolder ("Flux/flux1-dev-fp8.safetensors") ships with stripped
        // encoders that ignore our external T5 + CLIP — so prompt
        // understanding tanks if it gets picked. Hard-fail rather than
        // fall back so the user knows something's wrong.
        const isSeparated = (entry) => {
            const name = Array.isArray(entry) ? entry[0] : entry;
            return typeof name === "string"
                && /flux/i.test(name)
                && !name.includes("/");  // root-level = separated build
        };
        const flux = sd.find(isSeparated);
        if (!flux) {
            throw new Error("Separated Flux build not found at Models/ root. Only found: " + sd.map(e => Array.isArray(e) ? e[0] : e).join(", "));
        }
        const picked = normalizeModelName(flux);
        console.log("Picked model:", picked);
        if (!picked) {
            throw new Error(`Could not extract a model name from SwarmUI response. First entry: ${JSON.stringify(sd[0])}`);
        }
        return picked;
    }

    async function ensureBootstrapped() {
        if (sessionId && modelName) return;
        sessionId = await getSession();
        modelName = await listModels(sessionId);
    }

    /** Resolve a relative image path returned by SwarmUI to a same-origin URL.
     *  SwarmUI returns paths like "View/local/raw/..." or "Output/...";
     *  rewrite the leading segment to lowercase so it hits our nginx proxy.
     */
    function resolveImageUrl(rel) {
        if (!rel) return null;
        if (rel.startsWith("data:")) return rel;
        if (rel.startsWith("http://") || rel.startsWith("https://")) return rel;
        const stripped = rel.replace(/^\//, "");
        if (stripped.startsWith("View/"))   return `${location.origin}/view/${stripped.slice(5)}`;
        if (stripped.startsWith("Output/")) return `${location.origin}/output/${stripped.slice(7)}`;
        return `${location.origin}/${stripped}`;
    }

    /**
     * Open a generation WebSocket and stream images into the supplied tiles.
     * Resolves with the array of final image URLs (length = tiles.length).
     * Stash the socket on activeSocket so the Stop button can close it.
     */
    function generate(prompt, tiles) {
        return new Promise((resolve, reject) => {
            const ws = new WebSocket(`${WS_BASE}/GenerateText2ImageWS`);
            activeSocket = ws;
            activeTiles  = tiles;
            const finals = new Array(tiles.length).fill(null);
            let done = 0;

            const cleanup = () => {
                try { ws.close(); } catch {}
            };

            ws.addEventListener("open", () => {
                ws.send(JSON.stringify({
                    session_id: sessionId,
                    prompt,
                    model:      modelName,
                    ...GEN_PARAMS,
                }));
            });

            ws.addEventListener("message", (evt) => {
                let msg;
                try {
                    msg = JSON.parse(evt.data);
                } catch {
                    return;
                }

                if (msg.error) {
                    cleanup();
                    reject(new Error(msg.error));
                    return;
                }

                if (msg.gen_progress) {
                    const { batch_index, current_percent, preview } = msg.gen_progress;
                    const idx = parseInt(batch_index, 10);
                    if (Number.isNaN(idx) || idx < 0) return;
                    const tile = tiles[idx];
                    if (!tile) return;
                    if (typeof current_percent === "number") {
                        setTileProgress(tile, current_percent * 100);
                    }
                    if (preview) {
                        setTilePreview(tile, preview);
                    }
                    return;
                }

                // Final image message. SwarmUI sends a FLAT shape:
                //   {"image": "View/...", "batch_index": "0", "request_id": "...", "metadata": "..."}
                // batch_index is a string. batch_index "-1" is the optional
                // grid composite for multi-image batches — skip it.
                if (typeof msg.image === "string") {
                    const rawIdx = parseInt(msg.batch_index, 10);
                    if (rawIdx === -1 || Number.isNaN(rawIdx)) return;
                    const idx = rawIdx >= 0 && rawIdx < tiles.length ? rawIdx : done;
                    const url = resolveImageUrl(msg.image);
                    finals[idx] = url;
                    const tile = tiles[idx];
                    if (tile && url) fillTile(tile, url);
                    done += 1;
                    return;
                }

                if (msg.discard_indices) {
                    // Some indices were discarded; treat them as complete with no image.
                    for (const i of msg.discard_indices) {
                        if (tiles[i]) {
                            tiles[i].classList.remove("pending");
                            tiles[i].innerHTML = "";
                        }
                        done += 1;
                    }
                }
            });

            ws.addEventListener("error", () => {
                cleanup();
                reject(new Error("WebSocket error talking to SwarmUI"));
            });

            ws.addEventListener("close", () => {
                if (activeSocket === ws) {
                    activeSocket = null;
                    activeTiles  = null;
                }
                resolve(finals);
            });
        });
    }

    function stopActiveGeneration() {
        if (!activeSocket) return;
        userAborted = true;
        // Mark unfinished tiles so the user sees the abort.
        if (activeTiles) {
            for (const tile of activeTiles) {
                if (tile.classList.contains("pending")) {
                    tile.classList.remove("pending");
                    tile.innerHTML = "";
                    tile.style.opacity = "0.4";
                }
            }
        }
        try { activeSocket.close(1000, "user-aborted"); } catch {}
    }

    // ── Model load/unload ───────────────────────────────────────────────
    /** Ask SwarmUI which Stable-Diffusion-class models are currently loaded
     *  on any backend. Returns the loaded model name, or null. */
    async function fetchLoadedModel() {
        if (!sessionId) return null;
        const resp = await fetch(`${API_BASE}/ListLoadedModels`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
        });
        if (!resp.ok) throw new Error(`ListLoadedModels ${resp.status}`);
        const data = await resp.json();
        const models = data?.models || [];
        if (!models.length) return null;
        const m = models[0];
        return (m && (m.title || m.name)) || null;
    }

    function setModelButton(state, text) {
        modelBtn.dataset.state = state;
        modelLabel.textContent = text;
        if (state === "loaded") {
            modelBtn.title = "Click to unload (free VRAM)";
            modelBtn.setAttribute("aria-label", "Unload model");
        } else if (state === "unloaded") {
            modelBtn.title = "Click to load model into VRAM";
            modelBtn.setAttribute("aria-label", "Load model");
        } else if (state === "working") {
            modelBtn.title = text;
            modelBtn.setAttribute("aria-label", text);
        } else {
            modelBtn.title = "Model status unknown";
            modelBtn.setAttribute("aria-label", "Model status unknown");
        }
    }

    async function refreshModelStatus() {
        try {
            await ensureBootstrapped();
        } catch {
            setModelButton("unknown", "offline");
            return;
        }
        try {
            const loaded = await fetchLoadedModel();
            modelLoaded = !!loaded;
            if (loaded) {
                setModelButton("loaded", "Unload");
            } else {
                setModelButton("unloaded", "Load");
            }
        } catch (err) {
            console.warn("ListLoadedModels failed:", err);
            setModelButton("unknown", "?");
        }
    }

    async function loadModel() {
        modelWorking = true;
        modelBtn.disabled = true;
        setModelButton("working", "Loading…");
        try {
            await ensureBootstrapped();
            // SelectModel blocks until the load is complete (or fails).
            const resp = await fetch(`${API_BASE}/SelectModel`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId, model: modelName }),
            });
            if (!resp.ok) {
                const body = await resp.text().catch(() => "");
                throw new Error(`SelectModel ${resp.status}: ${body.slice(0, 200)}`);
            }
            const data = await resp.json();
            if (data.error) throw new Error(data.error);
        } catch (err) {
            console.error("Model load failed:", err);
            alert(`Model load failed: ${err.message}`);
        } finally {
            modelWorking = false;
            modelBtn.disabled = false;
            await refreshModelStatus();
        }
    }

    async function unloadModel() {
        modelWorking = true;
        modelBtn.disabled = true;
        setModelButton("working", "Unloading…");
        try {
            await ensureBootstrapped();
            const resp = await fetch(`${API_BASE}/FreeBackendMemory`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: sessionId,
                    system_ram: false,   // VRAM only.
                    backend:    "all",
                }),
            });
            if (!resp.ok) {
                const body = await resp.text().catch(() => "");
                throw new Error(`FreeBackendMemory ${resp.status}: ${body.slice(0, 200)}`);
            }
            const data = await resp.json();
            if (data.error) throw new Error(data.error);
        } catch (err) {
            console.error("Model unload failed:", err);
            alert(`Model unload failed: ${err.message}`);
        } finally {
            modelWorking = false;
            modelBtn.disabled = false;
            await refreshModelStatus();
        }
    }

    function onModelButtonClick() {
        if (modelWorking) return;
        if (busy) return;
        if (modelLoaded) {
            unloadModel();
        } else {
            // Covers both "definitely unloaded" and "unknown" — in the unknown
            // case, attempting a load will either succeed or surface a real
            // error, which is more useful than a silent no-op.
            loadModel();
        }
    }

    function startModelPolling() {
        // Cheap call (in-memory), but skip when the tab isn't visible.
        const tick = async () => {
            if (document.hidden || modelWorking) return;
            await refreshModelStatus();
        };
        // Initial fetch + a slow background poll so external changes
        // (e.g. user touched the SwarmUI UI directly) eventually reflect.
        tick();
        if (modelPollTimer) clearInterval(modelPollTimer);
        modelPollTimer = setInterval(tick, 10000);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) tick();
        });
    }

    // ── Prompt expansion (llama-swap) ───────────────────────────────────
    /** Extract a parameter-count hint from a model id like "qwen3.5-4B" -> 4.
     *  Returns Infinity when no count is found so unparseable ids sort last
     *  when we're picking the *smallest* model. */
    function paramCount(id) {
        const m = /(\d+(?:\.\d+)?)B/i.exec(id || "");
        return m ? parseFloat(m[1]) : Infinity;
    }

    function isCoderModel(id) {
        return /coder/i.test(id || "");
    }

    /** Pick a model for prompt expansion. We want the SMALLEST non-coder
     *  model — large enough to write coherent prose, small enough that it
     *  doesn't evict whatever the user has loaded for image generation.
     *  Prefer models already loaded (`/running` -> ready). Falls back to
     *  the full `/v1/models` list (llama-swap will load on demand). */
    async function pickExpansionModel() {
        try {
            const r = await fetch(`${LLM_BASE}/running`, { method: "GET" });
            if (r.ok) {
                const data = await r.json();
                const ready = (data.running || [])
                    .filter((e) => e.state === "ready" && e.model)
                    .map((e) => e.model)
                    .filter((id) => !isCoderModel(id));
                if (ready.length) {
                    ready.sort((a, b) => paramCount(a) - paramCount(b));
                    return ready[0];
                }
            }
        } catch (_) { /* fall through */ }

        const r2 = await fetch(`${LLM_BASE}/v1/models`, { method: "GET" });
        if (!r2.ok) throw new Error(`llama-swap /v1/models ${r2.status}`);
        const data2 = await r2.json();
        const ids = (data2.data || [])
            .map((m) => m.id)
            .filter((id) => id && !isCoderModel(id));
        if (!ids.length) throw new Error("No suitable model exposed by llama-swap.");
        ids.sort((a, b) => paramCount(a) - paramCount(b));
        return ids[0];
    }

    function setExpanding(b) {
        expanding = b;
        expandBtn.classList.toggle("busy", b);
        expandBtn.setAttribute("aria-label", b ? "Stop expansion" : "Expand prompt with LLM");
        expandBtn.title = b ? "Stop expansion" : "Expand prompt with LLM";
    }

    async function expandPrompt() {
        if (busy) return;
        if (expanding) {
            if (expandAbort) expandAbort.abort();
            return;
        }
        const original = promptEl.value.trim();
        if (!original) return;

        setExpanding(true);
        expandAbort = new AbortController();
        try {
            const model = await pickExpansionModel();
            const resp = await fetch(`${LLM_BASE}/v1/chat/completions`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                signal: expandAbort.signal,
                body: JSON.stringify({
                    model,
                    temperature: EXPAND_TEMPERATURE,
                    max_tokens: EXPAND_MAX_TOKENS,
                    messages: [
                        { role: "system", content: EXPAND_SYSTEM },
                        { role: "user",   content: original },
                    ],
                }),
            });
            if (!resp.ok) {
                const body = await resp.text().catch(() => "");
                throw new Error(`LLM ${resp.status}: ${body.slice(0, 200)}`);
            }
            const data = await resp.json();
            let expanded = data?.choices?.[0]?.message?.content || "";
            // Strip any <think>...</think> blocks some models emit even when
            // reasoning is disabled, plus surrounding quotes the model might add.
            expanded = expanded.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
            expanded = expanded.replace(/^["'`]+|["'`]+$/g, "").trim();
            if (!expanded) throw new Error("LLM returned an empty response.");
            promptEl.value = expanded;
            autoresize();
            promptEl.focus();
        } catch (err) {
            if (err.name === "AbortError") {
                // User stopped it — leave the textarea as-is, no error UI.
            } else {
                console.error("Prompt expansion failed:", err);
                alert(`Prompt expansion failed: ${err.message}`);
            }
        } finally {
            expandAbort = null;
            setExpanding(false);
        }
    }

    // ── Composer ────────────────────────────────────────────────────────
    function autoresize() {
        promptEl.style.height = "auto";
        promptEl.style.height = `${Math.min(promptEl.scrollHeight, 200)}px`;
    }

    function setBusy(b) {
        busy = b;
        promptEl.disabled = b;
        // While busy, keep the button enabled (it acts as Stop) and swap the
        // icon. When idle, normal Generate state.
        genBtn.disabled = false;
        genBtn.classList.toggle("busy", b);
        genBtn.setAttribute("aria-label", b ? "Stop" : "Generate");
        genBtn.title = b ? "Stop generation" : "Generate";
        // Expansion makes no sense mid-generation; gray it out.
        expandBtn.disabled = b;
        // Don't let the user yank the model out from under an in-flight gen.
        modelBtn.disabled = b || modelWorking;
    }

    async function handleSubmit(prompt) {
        if (busy) return;
        if (!prompt.trim()) return;

        setBusy(true);

        // Render pending turn immediately for instant feedback.
        const tilesData = Array.from({ length: GEN_PARAMS.images }, () => ({ pending: true }));
        const turnNode  = renderTurn(prompt, tilesData);
        feed.appendChild(turnNode);
        scrollFeedToBottom();

        const tiles = Array.from(turnNode.querySelectorAll(".tile"));
        pushTurn({ prompt, images: [] });

        userAborted = false;
        try {
            await ensureBootstrapped();
            const finals = await generate(prompt, tiles);
            const finalUrls = finals.filter(Boolean);
            updateLastTurnImages(finalUrls);
            if (userAborted && finalUrls.length === 0) {
                const note = document.createElement("div");
                note.className = "error";
                note.textContent = "Generation stopped.";
                turnNode.appendChild(note);
            }
        } catch (err) {
            if (userAborted) {
                const note = document.createElement("div");
                note.className = "error";
                note.textContent = "Generation stopped.";
                turnNode.appendChild(note);
                updateLastTurnImages([]);
            } else {
                const errEl = document.createElement("div");
                errEl.className = "error";
                errEl.textContent = `Generation failed: ${err.message}`;
                turnNode.appendChild(errEl);
                updateLastTurnImages([]);
            }
        } finally {
            setBusy(false);
            promptEl.value = "";
            autoresize();
            promptEl.focus();
        }
    }

    composer.addEventListener("submit", (e) => {
        e.preventDefault();
        if (busy) {
            stopActiveGeneration();
            return;
        }
        handleSubmit(promptEl.value);
    });

    promptEl.addEventListener("input", autoresize);
    promptEl.addEventListener("keydown", (e) => {
        // Enter submits, Shift+Enter inserts newline (ChatGPT-style).
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            composer.requestSubmit();
        }
    });

    expandBtn.addEventListener("click", expandPrompt);
    modelBtn.addEventListener("click", onModelButtonClick);

    clearBtn.addEventListener("click", () => {
        if (busy) return;
        if (!history.length) return;
        if (!confirm("Clear all generated images from history?")) return;
        history = [];
        saveHistory(history);
        feed.innerHTML = "";
    });

    // ── Boot ────────────────────────────────────────────────────────────
    renderHistory();
    autoresize();
    // Pre-warm session + model lookup so the first prompt feels instant.
    ensureBootstrapped()
        .then(() => startModelPolling())
        .catch((err) => {
            console.warn("SwarmUI bootstrap deferred:", err.message);
            // Try polling anyway; refreshModelStatus will retry bootstrap.
            startModelPolling();
        });
})();
