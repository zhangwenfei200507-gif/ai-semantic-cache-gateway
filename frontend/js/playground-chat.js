"use strict";

// Keep chat state separate from the advanced request-testing tabs.
const chat = {turns: [], draft: "", model: "auto", temperature: 0.7, maxTokens: 2048, system: ""};
let chatLoaded = false;
let chatController = null;
let chatStorageWarned = false;
let chatSessionGeneration = 0;

function chatStorageKey() {
  try {
    const owner = String(state.user?.id || "");
    const workspace = String(state.user?.workspace?.id || "");
    if (owner && workspace) return "ascg_chat_v3_" + owner + "_" + workspace;
    const payload = tokenStore().split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return "ascg_chat_v3_" + JSON.parse(atob(payload)).sub;
  } catch { return "ascg_chat_v3_guest"; }
}

function saveChat() {
  try { localStorage.setItem(chatStorageKey(), JSON.stringify({...chat, ownerId:String(state.user?.id || ""), workspaceId:String(state.user?.workspace?.id || "")})); }
  catch {
    if (!chatStorageWarned) toast("Browser storage is full or unavailable. This conversation cannot be saved locally.", "error");
    chatStorageWarned = true;
  }
}

function loadChat() {
  if (chatLoaded) return;
  chatLoaded = true;
  try {
    const saved = JSON.parse(localStorage.getItem(chatStorageKey()) || "null");
    const ownerId = String(state.user?.id || "");
    const workspaceId = String(state.user?.workspace?.id || "");
    const belongsToUser = saved && (!saved.ownerId || saved.ownerId === ownerId)
      && (!saved.workspaceId || saved.workspaceId === workspaceId);
    if (belongsToUser && Array.isArray(saved.turns)) Object.assign(chat, saved);
    chat.turns.forEach(turn => {
      if (turn.pending) {
        turn.pending = false;
        turn.error = "The page was closed while waiting. Check Requests for the result before retrying.";
      }
    });
  } catch { toast("The saved conversation could not be read.", "error"); }
}

function resetPlaygroundSession({removeStored = false} = {}) {
  chatSessionGeneration += 1;
  chatController?.abort();
  chatController = null;
  chat.turns = [];
  chat.draft = "";
  chat.model = "auto";
  chat.temperature = 0.7;
  chat.maxTokens = 2048;
  chat.system = "";
  chatLoaded = true;
  if (removeStored) localStorage.removeItem(chatStorageKey());
  else saveChat();
  const input = document.getElementById("pg-message");
  if (input) input.value = "";
  const model = document.getElementById("pg-model");
  if (model) model.value = "auto";
  renderChatTurns();
  updateChatBusy();
}

window.resetPlaygroundSession = resetPlaygroundSession;

function chatIcon(name) {
  return `<img src="/assets/icons/${name}.svg" alt="" width="18" height="18">`;
}

function chatButton(id, icon, title, extra = "") {
  return `<button type="button" class="chat-icon" id="${id}" title="${esc(title)}" aria-label="${esc(title)}" ${extra}>${chatIcon(icon)}</button>`;
}

function renderChat(root, opts) {
  loadChat();
  root.innerHTML = `
    <div class="chat-workspace">
      <div class="chat-toolbar">
        <label class="chat-model-label">Model
          <select id="pg-model"><option value="auto">Auto · Smart Routing</option>${opts}</select>
        </label>
        <div class="chat-tools">
          <a class="chat-history-link" href="/pages/requests.html">Requests</a>
          ${chatButton("chat-settings", "sliders-horizontal", "Generation settings")}
          ${chatButton("chat-new", "plus", "New conversation")}
          ${chatButton("expand-response", "maximize-2", "Expand conversation")}
        </div>
      </div>
      <div class="chat-thread" id="chat-thread" role="log" aria-label="Conversation" tabindex="0"></div>
      <form class="chat-composer" id="chat-composer">
        <label class="chat-input-label" for="pg-message">Message</label>
        <textarea id="pg-message" rows="3" maxlength="12000" placeholder="Ask anything, or describe an image..." required></textarea>
        <div class="chat-composer-actions">
          <div class="chat-tools">
            ${chatButton("pg-preview", "route", "Preview routing")}
            ${chatButton("expand-request", "maximize-2", "Expand message")}
            <span id="chat-status" role="status"></span>
          </div>
          ${chatButton("pg-send", "arrow-up", "Send message")}
          ${chatButton("pg-stop", "square", "Stop waiting", "hidden")}
        </div>
      </form>
    </div>`;
  const model = document.getElementById("pg-model");
  model.value = chat.model;
  if (!model.value) { model.value = "auto"; chat.model = "auto"; }
  model.onchange = () => { chat.model = model.value; saveChat(); };
  const input = document.getElementById("pg-message");
  input.value = chat.draft;
  input.oninput = () => { chat.draft = input.value; saveChat(); };
  input.onkeydown = event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!chatController) document.getElementById("chat-composer").requestSubmit();
    }
  };
  document.getElementById("chat-composer").onsubmit = event => { event.preventDefault(); sendChat(); };
  document.getElementById("pg-send").onclick = () => document.getElementById("chat-composer").requestSubmit();
  document.getElementById("pg-stop").onclick = () => chatController?.abort();
  document.getElementById("pg-preview").onclick = previewChat;
  document.getElementById("chat-settings").onclick = chatSettings;
  document.getElementById("expand-request").onclick = () => expandChat("chat-composer", "expand-request");
  document.getElementById("expand-response").onclick = () => expandChat("chat-thread", "expand-response");
  document.getElementById("chat-new").onclick = () => {
    resetPlaygroundSession();
    input.focus();
  };
  renderChatTurns();
  updateChatBusy();
  loadRequestedHistory();
}

function chatMessages(question) {
  const messages = chat.system.trim() ? [{role: "system", content: chat.system.trim()}] : [];
  // Image links are not text-model conversation context.
  for (const turn of chat.turns.slice(-12)) {
    if (turn.result && !turn.result.images?.length) {
      messages.push({role: "user", content: turn.question}, {role: "assistant", content: turn.result.answer});
    }
  }
  messages.push({role: "user", content: question});
  return messages;
}

async function sendChat() {
  if (chatController) return;
  const question = chat.draft.trim();
  if (!question) return;
  const messages = chatMessages(question);
  const turn = {id: crypto.randomUUID(), question, requestedModel: chat.model, started: Date.now(), pending: true};
  const generation = chatSessionGeneration;
  chat.turns.push(turn);
  chatController = new AbortController();
  chat.draft = "";
  document.getElementById("pg-message").value = "";
  saveChat();
  renderChatTurns();
  updateChatBusy();
  const timer = setInterval(updateChatBusy, 1000);
  try {
    // Auto may select an image provider. Never apply the old 45-second text deadline to it.
    const data = await api("/api/playground", {
      method: "POST", signal: chatController.signal, timeoutMs: 240000,
      body: JSON.stringify({model: turn.requestedModel, messages, user: String(state.user?.id || ""),
        temperature: Number(chat.temperature), max_tokens: Number(chat.maxTokens)})
    });
    if (generation !== chatSessionGeneration) return;
    const response = data.response || data;
    const llm = response.llm || {};
    turn.result = {
      answer: llm.answer || response.answer || "", images: llm.images || llm.raw?.images || [],
      imageAssets: llm.raw?.assets || response.image_assets || [],
      model: llm.model || response.model, provider: llm.provider || response.provider,
      tokens: llm.total_tokens ?? 0, promptTokens: llm.prompt_tokens ?? 0,
      completionTokens: llm.completion_tokens ?? 0, cost: llm.cost ?? 0,
      latency: response.latency_ms ?? llm.latency_ms, cacheHit: response.cache_hit,
      cacheType: response.cache_type, similarity: response.similarity,
      routing: response.routing, requestId: response.request_id || response.context?.request_id
    };
    if (!turn.result.answer && !turn.result.images.length) throw new Error("The provider returned an empty response.");
  } catch (error) {
    if (generation !== chatSessionGeneration) return;
    delete turn.result;
    turn.error = error.message;
  } finally {
    if (generation !== chatSessionGeneration) return;
    clearInterval(timer);
    turn.pending = false;
    chatController = null;
    saveChat();
    renderChatTurns();
    updateChatBusy();
  }
}

function updateChatBusy() {
  const busy = Boolean(chatController);
  const send = document.getElementById("pg-send");
  if (!send) return;
  send.hidden = busy;
  document.getElementById("pg-stop").hidden = !busy;
  document.getElementById("chat-new").disabled = busy;
  const pending = chat.turns.find(turn => turn.pending);
  const elapsed = pending ? Math.floor((Date.now() - pending.started) / 1000) : 0;
  const status = pending ? `Waiting for ${pending.requestedModel === "auto" ? "gateway" : pending.requestedModel} · ${elapsed}s` : "";
  document.getElementById("chat-status").textContent = status;
  const progress = document.querySelector(".chat-pending-text");
  if (progress) progress.textContent = status;
}

function safeImageUrl(value) {
  if (typeof value === "string" && value.startsWith("/") && !value.startsWith("//")) return value;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function chatText(text) {
  const html = DOMPurify.sanitize(marked.parse(String(text || ""), {gfm: true, breaks: true}), {
    USE_PROFILES: {html: true},
    FORBID_TAGS: ["img", "style", "input", "form", "iframe"],
    FORBID_ATTR: ["style"]
  });
  return '<div class="chat-prose">' + html + '</div>';
}

function renderChatTurns() {
  const thread = document.getElementById("chat-thread");
  if (!thread) return;
  thread.innerHTML = chat.turns.length ? chat.turns.map(turn => {
    const r = turn.result;
    const images = (r?.images || []).map(safeImageUrl).filter(Boolean);
    const imageAssets = r?.imageAssets || [];
    const result = turn.pending
      ? `<div class="chat-pending"><span class="chat-spinner"></span><span class="chat-pending-text">Waiting for gateway...</span></div>`
      : turn.error
        ? `<div class="chat-failure" role="alert">${esc(turn.error)}<div><button type="button" class="btn small" data-chat-action="retry" data-id="${esc(turn.id)}">Edit and retry</button><a href="/pages/requests.html">View Requests</a></div></div>`
        : `<div class="chat-reply">${images.length ? images.map((url, index) => {
            const asset = imageAssets[index] || {};
            const download = safeImageUrl(asset.download_url || url);
            return `<figure class="chat-image"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="Open image preview"><img src="${esc(url)}" alt="Generated image" loading="lazy"></a><figcaption>Qwen · ${esc(r.model)} <span><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Preview</a> <a href="${esc(download)}" download>Download</a></span></figcaption></figure>`;
          }).join("") : chatText(r?.answer)}</div>
          <div class="chat-reply-actions">
            <button class="chat-icon" data-chat-action="copy" data-id="${esc(turn.id)}" title="Copy response" aria-label="Copy response">${chatIcon("copy")}</button>
            <button class="chat-icon" data-chat-action="download" data-id="${esc(turn.id)}" title="Download response" aria-label="Download response">${chatIcon("download")}</button>
            <span>${esc(r?.model || "-")} · ${r?.cacheHit ? esc(r.cacheType || "Cache hit") : "Generated"} · ${images.length ? `${images.length} image` : `${num(r?.tokens)} tokens`}</span>
          </div>
          <details class="chat-details"><summary>Request details</summary>
            <dl>${Object.entries({
              Provider: r?.provider, Model: r?.model, "Requested model": turn.requestedModel,
              "Input tokens": r?.promptTokens, "Output tokens": r?.completionTokens,
              "Cost (USD)": images.length ? "Image pricing not configured" : money(r?.cost),
              "Latency (ms)": r?.latency, Cache: r?.cacheType || (r?.cacheHit ? "hit" : "miss"),
              Similarity: r?.similarity ?? "-", "Request ID": r?.requestId || "-"
            }).map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>
            <ul>${(r?.routing?.reasons || []).map(reason => `<li>${esc(reason)}</li>`).join("")}</ul>
          </details>`;
    return `<article class="chat-turn">
      <div class="chat-question"><span class="chat-role">You</span><div>${esc(turn.question)}</div>
        <button class="chat-icon" data-chat-action="copy-question" data-id="${esc(turn.id)}" title="Copy question" aria-label="Copy question">${chatIcon("copy")}</button>
      </div>
      <div class="chat-assistant"><span class="chat-role">${esc(r?.provider === "qwen_image" ? "Qwen" : r?.provider || "Gateway")}</span>${result}</div>
    </article>`;
  }).join("") : `<div class="chat-welcome"><span class="chat-welcome-mark">AI</span><h2>What would you like to create?</h2></div>`;
  thread.querySelectorAll("[data-chat-action]").forEach(button => button.onclick = () => chatAction(button));
  thread.querySelectorAll(".chat-prose a").forEach(link => {
    if (!safeImageUrl(link.href)) link.removeAttribute("href");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  });
  thread.querySelectorAll(".chat-image img").forEach(img => img.onerror = () => {
    img.hidden = true;
    img.closest("figure").querySelector("figcaption").prepend("Image unavailable or expired. ");
  });
  const latest = thread.lastElementChild;
  if (latest) thread.scrollTop += latest.getBoundingClientRect().top - thread.getBoundingClientRect().top - 12;
}

async function chatAction(button) {
  const turn = chat.turns.find(item => item.id === button.dataset.id);
  if (!turn) return;
  const action = button.dataset.chatAction;
  if (action === "retry") {
    chat.draft = turn.question;
    chat.model = turn.requestedModel;
    document.getElementById("pg-message").value = chat.draft;
    document.getElementById("pg-model").value = chat.model;
    saveChat();
    document.getElementById("pg-message").focus();
    return;
  }
  const text = action === "copy-question" ? turn.question : turn.result?.answer || "";
  try {
    if (action === "download") {
      const imageUrl = turn.result?.imageAssets?.[0]?.download_url || turn.result?.images?.[0];
      const url = imageUrl || URL.createObjectURL(new Blob([text], {type: "text/plain;charset=utf-8"}));
      const link = document.createElement("a");
      link.href = url;
      link.download = imageUrl ? `generated-${turn.id}` : `response-${turn.id}.txt`;
      link.click();
      if (!imageUrl) setTimeout(() => URL.revokeObjectURL(url), 1000);
    } else {
      await navigator.clipboard.writeText(text);
      toast("Copied", "success");
    }
  } catch { toast("Clipboard is unavailable in this browser.", "error"); }
}

function historyStorageKey() {
  return `ascg_open_history_${String(state.user?.id || "")}_${String(state.user?.workspace?.id || "")}`;
}

async function loadRequestedHistory() {
  const key = historyStorageKey();
  const requestId = sessionStorage.getItem(key);
  if (!requestId) return;
  sessionStorage.removeItem(key);
  try {
    const record = await api(`/api/history/${encodeURIComponent(requestId)}`);
    const images = (record.images || []).map(item => item.url).filter(Boolean);
    chat.turns.push({
      id: `history-${record.request_id}`,
      question: record.question || "",
      requestedModel: record.model || "auto",
      started: Date.now(),
      result: {
        answer: record.answer || "",
        images,
        imageAssets: record.images || [],
        model: record.model,
        provider: record.provider,
        tokens: record.total_tokens || 0,
        promptTokens: record.prompt_tokens || 0,
        completionTokens: record.completion_tokens || 0,
        cost: record.cost || 0,
        latency: record.latency_ms,
        cacheHit: record.cache_hit,
        cacheType: record.cache_type,
        similarity: record.similarity,
        requestId: record.request_id,
      },
    });
    saveChat();
    renderChatTurns();
  } catch (error) {
    toast(`History could not be opened: ${error.message}`, "error");
  }
}

function chatDialog(title, body) {
  document.getElementById("chat-dialog")?.remove();
  const dialog = document.createElement("dialog");
  dialog.id = "chat-dialog";
  dialog.className = "chat-dialog";
  dialog.innerHTML = `<header><h2>${esc(title)}</h2>${chatButton("close-chat-dialog", "x", "Close dialog")}</header>${body}`;
  document.body.appendChild(dialog);
  dialog.querySelector("#close-chat-dialog").onclick = () => dialog.close();
  dialog.addEventListener("close", () => dialog.remove(), {once: true});
  dialog.showModal();
  return dialog;
}

function chatSettings() {
  const dialog = chatDialog("Generation settings", `<form id="chat-settings-form">
    <label>Temperature<input name="temperature" type="number" min="0" max="2" step="0.1" value="${esc(chat.temperature)}" required></label>
    <label>Max output tokens<input name="maxTokens" type="number" min="1" max="8192" step="1" value="${esc(chat.maxTokens)}" required></label>
    <label>System prompt<textarea name="system" rows="6" maxlength="12000">${esc(chat.system)}</textarea></label>
    <button class="btn primary" type="submit">Save settings</button></form>`);
  dialog.querySelector("form").onsubmit = event => {
    event.preventDefault();
    const data = new FormData(event.target);
    chat.temperature = Number(data.get("temperature"));
    chat.maxTokens = Number(data.get("maxTokens"));
    chat.system = String(data.get("system"));
    saveChat();
    dialog.close();
  };
}

async function previewChat() {
  if (!chat.draft.trim()) { document.getElementById("pg-message").focus(); return; }
  if (chat.model !== "auto") {
    chatDialog("Routing preview", `<p>Manual model: <strong>${esc(chat.model)}</strong></p>`);
    return;
  }
  const dialog = chatDialog("Routing preview", `<div id="chat-preview-result" role="status">Analyzing request...</div>`);
  try {
    const result = await api("/api/routing/diagnostics", {method: "POST", timeoutMs: 45000,
      body: JSON.stringify({messages: chatMessages(chat.draft.trim())})});
    const selected = result.selected || {};
    dialog.querySelector("#chat-preview-result").innerHTML = `<h3>${esc(selected.provider)} · ${esc(selected.model)}</h3>
      <p>Confidence: ${esc(selected.confidence ?? "-")}</p><ul>${(selected.reasons || []).map(reason => `<li>${esc(reason)}</li>`).join("")}</ul>`;
  } catch (error) {
    if (dialog.isConnected) dialog.querySelector("#chat-preview-result").textContent = error.message;
  }
}

function expandChat(id, buttonId) {
  const target = document.getElementById(id);
  if (target.classList.contains("chat-fullscreen")) { closeChatFullscreen(); return; }
  closeChatFullscreen();
  target.classList.add("chat-fullscreen");
  const close = document.createElement("button");
  close.className = "chat-icon chat-exit-fullscreen";
  close.title = "Exit full screen";
  close.setAttribute("aria-label", close.title);
  close.innerHTML = chatIcon("minimize-2");
  close.onclick = closeChatFullscreen;
  document.body.appendChild(close);
  document.getElementById(buttonId)?.setAttribute("aria-pressed", "true");
  if (id === "chat-composer") document.getElementById("pg-message").focus();
}

function closeChatFullscreen() {
  document.querySelectorAll(".chat-fullscreen").forEach(element => element.classList.remove("chat-fullscreen"));
  document.querySelector(".chat-exit-fullscreen")?.remove();
  document.querySelectorAll('[aria-pressed="true"]').forEach(button => button.setAttribute("aria-pressed", "false"));
}

document.addEventListener("keydown", event => { if (event.key === "Escape") closeChatFullscreen(); });
window.addEventListener("beforeunload", event => {
  if (chatController) { event.preventDefault(); event.returnValue = ""; }
});
