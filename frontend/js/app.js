"use strict";

const PAGES = {
  dashboard: {title:"Dashboard", subtitle:"Monitor request volume, cache outcomes and provider connections."},
  playground: {title:"Playground", subtitle:"Run requests and inspect how the gateway handles them."},
  cache: {title:"Cache", subtitle:"Inspect stored responses and manage cache entries."},
  requests: {title:"Requests", subtitle:"Find a request and inspect its result, usage and cache outcome."},
  providers: {title:"Providers", subtitle:"Connect model providers and manage which models the gateway can use."},
  metrics: {title:"Analytics", subtitle:"Review recorded usage, cost and latency across your requests."},
  system: {title:"System", subtitle:"Inspect gateway services, Redis and runtime diagnostics."},
  admin: {title:"Admin", subtitle:"Monitor platform users, workspaces and service health."},
  settings: {title:"Settings", subtitle:"Manage your workspace configuration and defaults."}
};
const NAV_GROUPS = [
  {label:"Workspace", items:[["dashboard","/"],["playground","/pages/playground.html"],["requests","/pages/requests.html"]]},
  {label:"Operations", items:[["metrics","/pages/metrics.html"],["cache","/pages/cache.html"],["providers","/pages/providers.html"],["settings","/pages/settings.html"]]},
  {label:"Administration", admin:true, items:[["system","/pages/system.html"],["admin","/pages/admin.html"]]},
];

const state = {user:null};
const page=()=>document.body.dataset.page||"dashboard";
const esc=v=>String(v??"-").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]));
const num=v=>Number(v||0).toLocaleString();
const money=v=>`$${Number(v||0).toFixed(8)}`;
const moneyShort=v=>{const n=Number(v||0);if(!Number.isFinite(n)||n===0)return "$0.00";return `$${n.toFixed(Math.min(8,Math.max(2,Math.ceil(Math.abs(Math.log10(n)))+2)))}`};
const pct=v=>`${Number(v||0).toFixed(2)}%`;
const short=(v,n=90)=>{const s=String(v??"");return s.length>n?s.slice(0,n)+"…":s};
const json=v=>JSON.stringify(v??{},null,2);
const asList=v=>Array.isArray(v)?v:(v==null||v===""?[]:[v]);
const percentile=(values,p)=>{const sorted=values.map(Number).filter(Number.isFinite).sort((a,b)=>a-b);return sorted.length?sorted[Math.min(sorted.length-1,Math.max(0,Math.ceil(sorted.length*p)-1))]:0};

let runtimeToken="";

function tokenStore(){
  return runtimeToken
    || localStorage.getItem("ascg_access_token")
    || sessionStorage.getItem("ascg_access_token")
    || "";
}

function saveToken(token,remember){
  const value=String(token||"").trim();
  if(!value) throw new Error("Login succeeded but the server returned no access token.");
  runtimeToken=value;
  localStorage.removeItem("ascg_access_token");
  sessionStorage.removeItem("ascg_access_token");
  (remember ? localStorage : sessionStorage).setItem("ascg_access_token",value);
}

function clearToken(){
  const token=tokenStore();
  try{
    window.resetPlaygroundSession?.({removeStored:true});
    const payload=token.split(".")[1]?.replace(/-/g,"+").replace(/_/g,"/");
    const sub=payload?JSON.parse(atob(payload)).sub:"";
    if(sub){
      const prefix="ascg_chat_v3_"+sub;
      for(let i=localStorage.length-1;i>=0;i--){
        const key=localStorage.key(i)||"";
        if(key==="ascg_chat_v2_"+sub||key===prefix||key.startsWith(prefix+"_")) localStorage.removeItem(key);
      }
    }
  }catch{}
  for(let i=sessionStorage.length-1;i>=0;i--){
    const key=sessionStorage.key(i)||"";
    if(key.startsWith("ascg_open_history_")) sessionStorage.removeItem(key);
  }
  runtimeToken="";
  localStorage.removeItem("ascg_access_token");
  sessionStorage.removeItem("ascg_access_token");
}

async function api(path,options={}){
  const opts={credentials:"same-origin",cache:"no-store",...options};
  const explicitToken=typeof opts.authToken==="string" ? opts.authToken.trim() : "";
  const allowAuthRedirect=opts.allowAuthRedirect!==false;
  const timeoutMs=Number(opts.timeoutMs||20000);
  delete opts.authToken;
  delete opts.allowAuthRedirect;
  delete opts.timeoutMs;

  const headers={
    Accept:"application/json",
    ...(opts.body?{"Content-Type":"application/json"}:{}),
    ...(opts.headers||{})
  };
  const token=explicitToken||tokenStore();
  if(token) headers.Authorization=`Bearer ${token}`;
  // Keep cookie-authenticated writes valid after account switching or session restore.
  if(["POST","PUT","PATCH","DELETE"].includes(String(opts.method||"GET").toUpperCase())){
    const csrf=document.cookie.split(";").map(x=>x.trim()).find(x=>x.startsWith("ascg_csrf_token="));
    if(csrf&&!headers["X-CSRF-Token"]) headers["X-CSRF-Token"]=decodeURIComponent(csrf.slice("ascg_csrf_token=".length));
  }
  opts.headers=headers;

  const controller=new AbortController();
  const callerSignal=opts.signal;
  const abortFromCaller=()=>controller.abort();
  callerSignal?.addEventListener("abort",abortFromCaller,{once:true});
  if(callerSignal?.aborted) controller.abort();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  opts.signal=controller.signal;

  try{
    const r=await fetch(path,opts);
    const text=await r.text();
    let data={};
    if(text){try{data=JSON.parse(text)}catch{data={text}}}

    if(r.status===401){
      if(!explicitToken) clearToken();
      if(
        allowAuthRedirect &&
        page()!=="login"
      ){
        location.href="/pages/login.html";
      }
      throw new Error(
        typeof data.detail==="string"
          ? data.detail
          : "Authentication required"
      );
    }

    if(r.status===403){
      throw new Error(
        typeof data.detail==="string"
          ? data.detail
          : "Access denied"
      );
    }

    if(!r.ok){
      throw new Error(
        typeof data.detail==="string"
          ? data.detail
          : (data.detail ? JSON.stringify(data.detail) : `Request failed (${r.status})`)
      );
    }

    return data;
  }catch(e){
    if(e.name==="AbortError") throw new Error(callerSignal?.aborted ? "Stopped waiting. The provider may still finish; check Requests before retrying." : "Request timed out. Check Requests before retrying to avoid duplicate charges.");
    throw e;
  }finally{
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort",abortFromCaller);
  }
}
function toast(msg,type="info"){const root=document.getElementById("toast-root")||document.body;const x=document.createElement("div");x.className=`toast ${type}`;x.setAttribute("role","status");x.setAttribute("aria-live","polite");x.textContent=msg;root.appendChild(x);setTimeout(()=>x.remove(),3200)}
function button(label,cls="btn",attrs=""){return `<button class="${cls}" ${attrs}>${esc(label)}</button>`}
function card(title,body,extra=""){return `<section class="panel"><div class="panel-head"><h2>${esc(title)}</h2>${extra}</div>${body}</section>`}
function uiIcon(name){return window.gatewayIcon?.(name)||""}
function kpi(label,value,hint="",icon="·",tone="blue"){const symbol=/cost/i.test(label)?"cost":/latency|ttl/i.test(label)?"clock":/cache|hits/i.test(label)?"cache":/provider|model/i.test(label)?"providers":"metrics";return `<div class="kpi-card"><div class="kpi-icon ${tone}">${uiIcon(symbol)}</div><div class="kpi-copy"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(hint)}</small></div></div>`}
function table(headers,rows,empty="No data"){const normalized=Array.isArray(rows)?rows:(rows?[rows]:[]);const labelled=normalized.map(row=>{let column=0;return row.replace(/<td(\s[^>]*)?>/g,(match)=>`${match.slice(0,-1)} data-label="${esc(headers[column++]||"")}">`)});return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${labelled.length?labelled.join(""):`<tr><td colspan="${headers.length}" class="empty">${esc(empty)}</td></tr>`}</tbody></table></div>`}
function statusBadge(v){const s=String(v??"").toLowerCase();const cls=s.includes("error")||s.includes("fail")||s.includes("offline")?"bad":s.includes("hit")||s.includes("healthy")||s.includes("active")||s.includes("connected")||["verified","ready","enabled","ok"].includes(s)?"good":"neutral";return `<span class="badge ${cls}">${esc(v||"-")}</span>`}
function emptyPanel(title,text){return card(title,`<div class="empty-state"><div class="empty-icon">—</div><strong>${esc(text)}</strong><span>Waiting for backend data.</span></div>`)}

function brand() {
  return `<a class="brand" href="/" aria-label="Semantic Gateway dashboard"><span class="brand-icon">${uiIcon("gateway")}</span><span class="brand-name"><strong>Semantic Gateway</strong><span>AI cache &amp; routing</span></span></a>`;
}

function renderNavigation() {
  const current = page();
  document.getElementById("gateway-nav").innerHTML = NAV_GROUPS.filter(group => !group.admin || state.user?.is_admin)
    .map(({label, items}) => `<div class="nav-group"><p>${esc(label)}</p>${items.map(([key, href]) => {
      const active = key === current;
      return `<a class="nav-item${active ? " active" : ""}" ${active ? 'aria-current="page"' : ""} href="${href}"><span class="nav-icon">${uiIcon(key)}</span><span>${esc(PAGES[key].title)}</span></a>`;
    }).join("")}</div>`).join("");
}

function shell() {
  const current = page();
  const meta = PAGES[current] || PAGES.dashboard;
  const sidebar = document.querySelector(".sidebar");
  const main = document.querySelector(".main");
  const root = document.getElementById("page-root");
  const mobile = matchMedia("(max-width:900px)");

  document.body.insertAdjacentHTML("afterbegin", '<a class="skip-link" href="#page-root">Skip to content</a><div class="mobile-nav-backdrop" id="mobile-nav-backdrop"></div>');
  root.tabIndex = -1;
  sidebar.id = "app-sidebar";
  sidebar.innerHTML = `<button class="drawer-close" id="close-mobile-nav" type="button" aria-label="Close navigation">${uiIcon("close")}</button>
    ${brand()}
    <nav id="gateway-nav" aria-label="Gateway navigation"></nav>
    <div class="sidebar-spacer"></div>
    <div class="sidebar-status" id="sidebar-status"></div>
    <div class="sidebar-user" id="sidebar-user"></div>
    <button class="logout-btn" id="logout-btn" type="button">${uiIcon("logout")} Sign out</button>`;
  renderNavigation();

  document.querySelector(".topbar").innerHTML = `<div class="topbar-left">
    <button class="icon-btn mobile-menu-toggle" id="mobile-menu-toggle" type="button" title="Open navigation" aria-label="Open navigation" aria-controls="app-sidebar" aria-expanded="false">${uiIcon("menu")}</button>
    <div class="topbar-context"><span>${uiIcon(current)} ${esc(meta.title)}</span><div id="workspace-label" class="workspace-label"></div></div>
    </div><div class="topbar-actions">
    <button class="icon-btn" id="refresh-page" type="button" title="Refresh page" aria-label="Refresh page">${uiIcon("refresh")}</button>
    <button class="icon-btn" id="theme-toggle" type="button">${uiIcon("theme")}</button>
  </div>`;

  root.insertAdjacentHTML("beforebegin", `<div class="page-heading" id="page-heading"><div><h1>${esc(meta.title)}</h1><p>${esc(meta.subtitle)}</p></div>${current === "dashboard" ? `<a class="btn primary" href="/pages/playground.html">${uiIcon("playground")} Open Playground</a>` : ""}</div>`);

  const toggle = document.getElementById("mobile-menu-toggle");
  const setMobileNav = (open, restoreFocus = true) => {
    sidebar.inert = mobile.matches && !open;
    main.inert = mobile.matches && open;
    document.body.classList.toggle("mobile-nav-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    const label = open ? "Close navigation" : "Open navigation";
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
    if (open) (sidebar.querySelector('[aria-current="page"]') || document.getElementById("close-mobile-nav")).focus();
    else if (restoreFocus && mobile.matches) toggle.focus();
  };
  setMobileNav(false, false);
  toggle.onclick = () => setMobileNav(true);
  document.getElementById("mobile-nav-backdrop").onclick = () => setMobileNav(false);
  document.getElementById("close-mobile-nav").onclick = () => setMobileNav(false);
  mobile.addEventListener("change", () => setMobileNav(false, false));
  document.addEventListener("keydown", event => {
    if (!document.body.classList.contains("mobile-nav-open")) return;
    if (event.key === "Escape") setMobileNav(false);
    if (event.key !== "Tab") return;
    const controls = [...sidebar.querySelectorAll("a[href],button:not([disabled])")].filter(control => control.getClientRects().length);
    if (event.shiftKey && document.activeElement === controls[0]) {
      event.preventDefault();
      controls.at(-1)?.focus();
    } else if (!event.shiftKey && document.activeElement === controls.at(-1)) {
      event.preventDefault();
      controls[0]?.focus();
    }
  });

  document.getElementById("logout-btn").onclick = async () => {
    try { await api("/api/auth/logout", {method:"POST", allowAuthRedirect:false}); } catch {}
    clearToken();
    location.href = "/pages/login.html";
  };
  document.getElementById("refresh-page").onclick = () => location.reload();
  document.getElementById("theme-toggle").onclick = () => applyTheme(nextTheme());
  applyTheme(localStorage.getItem("ascg_theme"));
}

function ensureDesignSystem(){
 if(document.getElementById("design-system-css"))return;
 const link=document.createElement("link");link.id="design-system-css";link.rel="stylesheet";link.href="/css/design-system.css?v=20261119-1";document.head.appendChild(link);
}
function applyTheme(theme) {
  const value = ["light","dark","sakura"].includes(theme) ? theme : "light";
  document.documentElement.classList.toggle("dark", value === "dark");
  document.documentElement.classList.toggle("theme-sakura", value === "sakura");
  localStorage.setItem("ascg_theme", value);
  const button = document.getElementById("theme-toggle");
  if (button) {
    const label = `Switch to ${nextTheme()} theme`;
    button.title = label;
    button.setAttribute("aria-label", label);
  }
}

function nextTheme() {
  const current = localStorage.getItem("ascg_theme") || "light";
  return current === "light" ? "dark" : current === "dark" ? "sakura" : "light";
}

function renderIdentity() {
  const {email, is_admin, workspace} = state.user;
  const initial = (email?.[0] || "U").toUpperCase();
  document.getElementById("sidebar-user").innerHTML = `<div class="avatar">${esc(initial)}</div><div class="user-text"><strong>${esc(email)}</strong><span>${is_admin ? "Administrator" : "Workspace member"}</span></div>`;
  if (workspace?.name) {
    const chip = document.createElement("span");
    chip.className = "workspace-chip";
    chip.textContent = workspace.name;
    chip.title = workspace.name;
    document.getElementById("workspace-label").append(chip);
  }
}

async function loadStatus() {
  if (!state.user?.is_admin) return;
  const status = document.getElementById("sidebar-status");
  try {
    const system = await api("/api/system", {timeoutMs:2500});
    const healthy = ["ok", "healthy"].includes(String(system.gateway?.status).toLowerCase()) && system.redis?.connected === true;
    status.innerHTML = `<a href="/pages/system.html"><span class="service-dot ${healthy ? "healthy" : "degraded"}"></span><span>${healthy ? "Gateway operational" : "Check system status"}</span></a>`;
  } catch {
    status.innerHTML = '<a href="/pages/system.html"><span class="service-dot degraded"></span><span>Status unavailable</span></a>';
  }
}


const CACHE_OUTCOMES = {
  exact: "Exact hit",
  semantic: "Semantic hit",
  miss: "Miss",
  other: "Unspecified hit",
  unavailable: "No outcome",
};

function cacheOutcome(record) {
  const kind = String(record.cache_type || "").toLowerCase();
  if (record.cache_hit) return ["exact", "semantic"].includes(kind) ? kind : "other";
  return kind === "miss" ? "miss" : "unavailable";
}

function cacheBadge(record) {
  const outcome = cacheOutcome(record);
  return `<span class="outcome-badge ${outcome}"><i aria-hidden="true"></i>${CACHE_OUTCOMES[outcome]}</span>`;
}

function parseHistoryTime(value) {
  if (value == null || value === "") return NaN;
  const number = Number(value);
  if (Number.isFinite(number) && number > 0) return number < 100000000000 ? number * 1000 : number;
  const text = String(value);
  return Date.parse(/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(text) ? `${text.replace(" ", "T")}Z` : text);
}

function historyDate(value) {
  const time = parseHistoryTime(value);
  return Number.isFinite(time) ? new Date(time).toISOString().slice(0,10) : "";
}

function requestFailed(record) {
  return ["error", "failed", "failure"].includes(String(record.status || "").toLowerCase()) || Boolean(record.error);
}

function metricsFromHistory(records) {
  const cache = {exact:0, semantic:0, miss:0, other:0, unavailable:0};
  const latencies = [];
  let failed = 0, tokens = 0, cost = 0;
  for (const record of records) {
    cache[cacheOutcome(record)]++;
    failed += Number(requestFailed(record));
    tokens += Number(record.consumed_tokens ?? record.total_tokens) || 0;
    cost += Number(record.cost) || 0;
    const latency = Number(record.latency_ms);
    if (Number.isFinite(latency) && latency > 0) latencies.push(latency);
  }
  cache.hits = cache.exact + cache.semantic + cache.other;
  const lookups = cache.hits + cache.miss;
  cache.hit_rate = lookups ? cache.hits * 100 / lookups : null;
  return {
    total_requests:records.length,
    success_requests:records.length - failed,
    failed_requests:failed,
    total_tokens:tokens,
    total_cost:cost,
    latencies,
    average_latency_ms:latencies.length ? latencies.reduce((sum, value) => sum + value, 0) / latencies.length : null,
    cache,
  };
}

function cacheBreakdown(cache) {
  const keys = Object.keys(CACHE_OUTCOMES).filter(key => key === "exact" || key === "semantic" || key === "miss" || cache[key]);
  const total = keys.reduce((sum, key) => sum + cache[key], 0);
  return `<div class="cache-breakdown">
    <div class="outcome-bars" aria-hidden="true">${total ? keys.filter(key => cache[key]).map(key => `<span class="${key}" style="--outcome-count:${cache[key]}"></span>`).join("") : ""}</div>
    <dl class="outcome-legend">${keys.map(key => `<div><dt><i class="${key}" aria-hidden="true"></i>${CACHE_OUTCOMES[key]}</dt><dd>${num(cache[key])}</dd></div>`).join("")}</dl>
  </div>`;
}

function bucketChart(items, label, valueFor, format = num) {
  const records = items.map(item => ({time:parseHistoryTime(item.created_at), value:valueFor(item)}))
    .filter(point => Number.isFinite(point.time) && Number.isFinite(point.value));
  if (!records.length) return `<div class="chart-empty">No timestamped ${esc(label.toLowerCase())} data.</div>`;
  const start = Math.min(...records.map(point => point.time));
  const end = Math.max(...records.map(point => point.time));
  const hour = 3600000;
  const day = 24 * hour;
  const span = end - start;
  const size = span < day ? hour : span < 24 * day ? day : 7 * day * Math.max(1, Math.ceil(span / (24 * 7 * day)));
  const floor = time => Math.floor(time / size) * size;
  const first = floor(start);
  const last = floor(end);
  const buckets = Array.from({length: (last - first) / size + 1}, () => 0);
  for (const record of records) buckets[(floor(record.time)-first)/size] += record.value;
  const peak = Math.max(...buckets);
  const formatTime = new Intl.DateTimeFormat(undefined, {timeZone:"UTC", month:"short", day:"numeric", ...(size === hour ? {hour:"2-digit", minute:"2-digit", hour12:false} : {})});
  const stamps = buckets.map((_, index) => formatTime.format(first + index * size));
  return `<figure class="histogram" aria-label="${esc(label)} over time, UTC">
    <div class="histogram-key"><span>${esc(format(peak))}</span><span>0</span></div>
    <div class="histogram-body">
      <div class="histogram-plot" aria-hidden="true">${buckets.map((value, index) => `<span title="${esc(stamps[index])}: ${esc(format(value))}" style="--bar-height:${peak ? value / peak * 100 : 0}%"></span>`).join("")}</div>
      <div class="histogram-dates" aria-hidden="true"><span>${esc(stamps[0])}</span>${stamps.length > 1 ? `<span>${esc(stamps.at(-1))}</span>` : ""}</div>
    </div>
    <ul class="sr-only">${buckets.map((value, index) => `<li>${esc(stamps[index])}: ${esc(format(value))}</li>`).join("")}</ul>
  </figure>`;
}

function historyCharts(records) {
  return {
    requests:bucketChart(records, "Requests", () => 1),
    usage:`<div class="trend-columns"><div><span>Tokens</span>${bucketChart(records, "Tokens", item => Number(item.consumed_tokens ?? item.total_tokens) || 0)}</div><div><span>Cost (USD)</span>${bucketChart(records, "Cost", item => Number(item.cost) || 0, moneyShort)}</div></div>`,
  };
}

function latencyLabel(value, decimals = 0) {
  return value == null ? "—" : `${value.toFixed(decimals)} ms`;
}

async function dashboard() {
  const root = document.getElementById("page-root");
  root.innerHTML = '<div class="loading" role="status">Loading dashboard…</div>';
  try {
    const [history, providers, onboarding] = await Promise.all([
      api("/api/history?limit=100"),
      api("/api/providers").catch(() => null),
      api("/api/onboarding").catch(() => null),
    ]);
    const records = history.items || [];
    const metrics = metricsFromHistory(records);
    const {cache, latencies} = metrics;
    const recent = records.slice(0,6).map(record => {
      const id = record.request_id || record.id;
      return `<tr><td><strong>${esc(short(record.question || "-", 70))}</strong><small class="mono">${esc(short(id || "-", 25))}</small></td><td>${cacheBadge(record)}</td><td>${esc(record.model || "—")}</td><td>${esc(latencyLabel(Number(record.latency_ms) > 0 ? Number(record.latency_ms) : null))}</td><td>${id ? `<button type="button" class="btn small" data-request-detail="${esc(id)}">Inspect<span class="sr-only"> ${esc(id)}</span></button>` : "—"}</td></tr>`;
    });
    const connections = (providers?.providers || []).filter(provider => provider.configured);
    const providerRows = connections.slice(0,5).map(provider => `<div class="provider-row"><div class="provider-mark">${uiIcon("providers")}</div><div><strong>${esc(provider.display_name || provider.name)}</strong><span>${esc(provider.model || "No default model")}</span></div>${statusBadge(provider.verified ? "Verified" : "Needs test")}</div>`).join("");
    const traffic = `<section class="panel dashboard-traffic">
      <div class="panel-head"><div><h2>Request volume</h2><p>Recorded traffic by time bucket</p></div><a class="panel-link" href="/pages/metrics.html">Analytics</a></div>
      ${bucketChart(records, "Requests", () => 1)}
    </section>`;
    const outcomes = `<section class="panel dashboard-outcomes">
      <div class="panel-head"><h2>Cache outcomes</h2><a class="panel-link" href="/pages/cache.html">Open cache</a></div>
      <div class="cache-hero-value"><strong>${cache.hit_rate == null ? "—" : pct(cache.hit_rate)}</strong><span>cache hit rate</span></div>
      ${cacheBreakdown(cache)}
    </section>`;
    root.innerHTML = `${onboardingCard(onboarding)}
      <div class="history-scope"><span>${uiIcon("clock")} Recent workspace history</span><span>${num(records.length)} loaded · Up to 100 requests</span></div>
      <div class="kpi-grid dashboard-kpis">
        ${kpi("Recorded requests", num(metrics.total_requests), "In this history view", "", "blue")}
        ${kpi("P95 latency", latencyLabel(latencies.length ? percentile(latencies, .95) : null), "Across measured requests", "", "purple")}
        ${kpi("Used tokens", num(metrics.total_tokens), "Recorded token usage", "", "cyan")}
        ${kpi("Recorded cost", moneyShort(metrics.total_cost), "USD", "", "gold")}
      </div>
      <div class="dashboard-overview">${outcomes}${traffic}</div>
      <div class="dashboard-detail">
        ${card("Recent requests", table(["Request", "Cache", "Model", "Latency", "Action"], recent, "No recorded requests yet."), '<a class="panel-link" href="/pages/requests.html">All requests</a>')}
        ${card("Provider connections", providerRows || `<p class="muted">${providers ? "No providers connected yet." : "Provider status unavailable."}</p>`, '<a class="panel-link" href="/pages/providers.html">Manage</a>')}
      </div>`;
    root.querySelectorAll("[data-request-detail]").forEach(trigger => {
      trigger.onclick = () => showRequest(trigger.dataset.requestDetail);
    });
  } catch (error) {
    root.innerHTML = `<div class="error-panel"><h2>Dashboard unavailable</h2><p>${esc(error.message)}</p>${button("Retry","btn primary",'id="retry-dashboard"')}</div>`;
    document.getElementById("retry-dashboard").onclick = dashboard;
  }
}

async function cachePage(){
 const root=document.getElementById("page-root");root.innerHTML=`<div class="loading">Loading cache…</div>`;
 try{
  const summary=await api("/api/cache");const list=summary.entries||[];
  const renderRows=(filter="")=>list.filter(x=>`${x.key||""} ${x.question||""} ${x.answer||""}`.toLowerCase().includes(filter.toLowerCase())).map(x=>{const fields=Array.isArray(x.fields)?x.fields.join(", "):Object.keys(x.fields&&typeof x.fields==="object"?x.fields:{}).join(", ");return `<tr><td class="mono">${esc(short(x.key||x.redis_key||"-",32))}</td><td>${statusBadge(x.cache_type||"exact")}</td><td>${esc(short(x.question||"-",50))}</td><td>${esc(short(x.answer||"-",70))}</td><td>${x.similarity==null?"—":Number(x.similarity).toFixed(3)}</td><td>${num(x.hit_count||0)}</td><td>${x.ttl_seconds==null?"—":`${Math.max(0,Math.round(Number(x.ttl_seconds)/60))} min`}</td><td><button class="btn small" data-inspect="${esc(x.key||x.redis_key||"")}">Inspect</button> <button class="btn small danger" data-del="${esc(x.key||x.redis_key||"")}">Delete</button><span class="sr-only">${esc(fields)}</span></td></tr>`}).join("");
  const bind=()=>{
   root.querySelectorAll("[data-inspect]").forEach(trigger=>trigger.onclick=()=>{const item=list.find(entry=>(entry.key||entry.redis_key)===trigger.dataset.inspect);if(item)showCacheDetail(item)});
   root.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{try{await api(`/api/cache/entries/${encodeURIComponent(b.dataset.del)}`,{method:"DELETE"});toast("Entry deleted","success");cachePage()}catch(e){toast(e.message,"error")}});
  };
  const headers=["Key","Type","Original Query","Answer","Similarity","Hits","TTL","Actions"];
  root.innerHTML=`<div class="kpi-grid">${kpi("Cache Entries",num(summary.size),"Current Redis entries","C","blue")}${kpi("Threshold",Number(summary.threshold??0).toFixed(2),"Semantic threshold","◎","green")}${kpi("TTL",`${Math.round(Number(summary.ttl_seconds||0)/60)} min`,"Entry expiration","T","purple")}${kpi("Redis",""+(summary.connected?"Connected":"Offline"),"Cache backend","R","slate")}</div>${card("Cache Controls",`<div class="page-toolbar"><span class="muted">Exact: ${summary.exact_enabled===false?"off":"on"} · Semantic: ${summary.semantic_enabled===false?"off":"on"}</span><div class="table-actions"><a class="btn" href="/pages/settings.html?section=Cache+Settings">Open Cache Settings</a><button class="btn" id="refresh-cache">Refresh</button><button class="btn danger" id="clear-cache">Clear All Cache</button></div></div>`)}${card("Cache Entries",`<div class="page-toolbar compact-toolbar"><input id="cache-search" aria-label="Search cache entries" placeholder="Search key, question or answer…"><span class="muted">${num(list.length)} entries loaded</span></div><div id="cache-table">${table(headers,renderRows(),"No cache entries yet.")}</div>`)}`;
  document.getElementById("refresh-cache").onclick=cachePage;document.getElementById("cache-search").oninput=e=>{document.getElementById("cache-table").innerHTML=table(headers,renderRows(e.target.value),"No matching cache entries");bind()};document.getElementById("clear-cache").onclick=async()=>{if(!confirm("Clear all cache entries?"))return;try{await api("/api/cache",{method:"DELETE"});toast("Cache cleared","success");cachePage()}catch(e){toast(e.message,"error")}};bind();
 }catch(e){root.innerHTML=`<div class="error-panel"><h2>Cache unavailable</h2><p>${esc(e.message)}</p>${button("Retry","btn primary",'id="retry-cache"')}</div>`;document.getElementById("retry-cache")?.addEventListener("click",cachePage)}
}

async function requestsPage(){
 const root=document.getElementById("page-root");root.innerHTML=`<div class="loading">Loading requests…</div>`;
 try{
  const d=await api("/api/requests?limit=500");const items=d.items||[];let currentPage=1;const pageSize=20;
  const render=()=>{const q=(document.getElementById("request-search")?.value||"").toLowerCase(),type=document.getElementById("request-cache-filter")?.value||"",status=document.getElementById("request-status-filter")?.value||"";const filtered=items.filter(x=>{const text=`${x.request_id||""} ${x.question||""} ${x.provider||""} ${x.model||""}`.toLowerCase();return(!q||text.includes(q))&&(!type||cacheOutcome(x)===type)&&(!status||String(x.status||"")===status)});const pages=Math.max(1,Math.ceil(filtered.length/pageSize));currentPage=Math.min(currentPage,pages);const shown=filtered.slice((currentPage-1)*pageSize,currentPage*pageSize);const rows=shown.map(x=>`<tr><td class="mono">${esc(short(x.request_id||x.id||"-",22))}</td><td>${esc(short(x.question||"-",70))}</td><td>${esc(x.provider||"-")}</td><td>${esc(x.model||"-")}</td><td>${cacheBadge(x)}</td><td>${num(x.consumed_tokens??x.total_tokens)}</td><td>${num(x.saved_tokens)}</td><td>${money(x.cost)}</td><td><button class="btn small" data-view="${esc(x.request_id||x.id||"")}">View</button></td></tr>`);document.getElementById("request-table").innerHTML=table(["Request","Question","Provider","Model","Cache","Used","Saved","Cost","Action"],rows,"No matching request history");document.getElementById("request-page-label").textContent=`Page ${currentPage} / ${pages} · ${filtered.length} records`;document.getElementById("request-prev").disabled=currentPage<=1;document.getElementById("request-next").disabled=currentPage>=pages;root.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>showRequest(b.dataset.view))};
  root.innerHTML=`<div class="kpi-grid">${kpi("Recorded Requests",num(items.length),"Up to 500 recent requests","R","blue")}${kpi("Used Tokens",num(items.reduce((n,x)=>n+Number(x.consumed_tokens??x.total_tokens??0),0)),"Recorded usage","T","cyan")}${kpi("Saved Tokens",num(items.reduce((n,x)=>n+Number(x.saved_tokens||0),0)),"Estimated cache savings","S","green")}${kpi("Total Cost",moneyShort(items.reduce((n,x)=>n+Number(x.cost||0),0)),"Calculated from provider pricing","$","gold")}</div>${card("Request History",`<div class="page-toolbar compact-toolbar"><input id="request-search" aria-label="Search requests" placeholder="Search request, question, provider…"><select id="request-cache-filter" aria-label="Cache outcome"><option value="">All cache types</option><option value="exact">Exact</option><option value="semantic">Semantic</option><option value="miss">Miss</option><option value="other">Unspecified hit</option><option value="unavailable">No outcome</option></select><select id="request-status-filter" aria-label="Request status"><option value="">All statuses</option><option value="success">Success</option><option value="completed">Completed</option><option value="error">Error</option></select><button class="btn" id="refresh-requests">Refresh</button><button class="btn" id="export-requests">Export CSV</button><button class="btn danger" id="clear-history">Clear History</button></div><div id="request-table"></div><div class="pagination"><button class="btn small" id="request-prev">Previous</button><span id="request-page-label"></span><button class="btn small" id="request-next">Next</button></div>`)}
  `;
  ["request-search","request-cache-filter","request-status-filter"].forEach(id=>document.getElementById(id).oninput=()=>{currentPage=1;render()});document.getElementById("request-prev").onclick=()=>{currentPage--;render()};document.getElementById("request-next").onclick=()=>{currentPage++;render()};document.getElementById("refresh-requests").onclick=requestsPage;document.getElementById("clear-history").onclick=async()=>{if(!confirm("Clear request history?"))return;try{await api("/api/history",{method:"DELETE"});toast("History cleared","success");requestsPage()}catch(e){toast(e.message,"error")}};document.getElementById("export-requests").onclick=()=>{const cols=["request_id","question","provider","model","cache_type","total_tokens","saved_tokens","cost","latency_ms","created_at"];const quote=value=>'"'+String(value??"").replace(/"/g,'""')+'"';const csv=[cols.join(","),...items.map(x=>cols.map(k=>quote(x[k])).join(","))].join("\n");const url=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));const link=document.createElement("a");link.href=url;link.download="gateway-requests.csv";link.click();URL.revokeObjectURL(url)};render();
  const requestedId = new URLSearchParams(location.search).get("id");
  if (requestedId) void showRequest(requestedId);
 }catch(e){root.innerHTML=`<div class="error-panel"><h2>Requests unavailable</h2><p>${esc(e.message)}</p>${button("Retry","btn primary",'id="retry-requests"')}</div>`;document.getElementById("retry-requests")?.addEventListener("click",requestsPage)}
}


async function showRequest(id) {
  if (!id || document.querySelector(".request-dialog")) return;
  const modal = document.createElement("dialog");
  modal.className = "modal request-dialog";
  modal.setAttribute("aria-labelledby", "request-title");
  modal.innerHTML = `<div class="panel-head"><div><h2 id="request-title">Request details</h2><p class="mono">${esc(id)}</p></div><button class="icon-btn" type="button" aria-label="Close request details">${uiIcon("close")}</button></div><div class="request-inspection"><p role="status">Loading request…</p></div>`;
  document.body.append(modal);
  modal.querySelector("button").onclick = () => modal.close();
  modal.addEventListener("close", () => modal.remove(), {once:true});
  modal.showModal();
  const content = modal.querySelector(".request-inspection");
  try {
    const record = await api(`/api/requests/${encodeURIComponent(id)}`);
    const images = (record.images || []).map(image => `<figure class="request-image"><img src="${esc(image.url)}" alt="Generated image"><figcaption><a href="${esc(image.url)}" target="_blank" rel="noopener noreferrer">Preview</a> <a href="${esc(image.download_url || image.url)}" download>Download</a></figcaption></figure>`).join("");
    const summary = {
      Provider:record.provider,
      Model:record.model,
      Similarity:record.similarity,
      Latency:latencyLabel(Number(record.latency_ms) > 0 ? Number(record.latency_ms) : null),
      "Used tokens":num(record.consumed_tokens ?? record.total_tokens),
      "Recorded cost":moneyShort(record.cost),
    };
    const {images: assets, ...metadata} = record;
    content.innerHTML = `<div class="request-inspection-status">${cacheBadge(record)}${record.status ? statusBadge(record.status) : ""}</div>
      <div class="detail-grid compact">${Object.entries(summary).map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value ?? "—")}</strong></div>`).join("")}</div>
      <section class="request-message"><h3>Prompt</h3><p>${esc(record.question || "No prompt recorded.")}</p></section>
      ${images ? `<div class="request-images">${images}</div>` : ""}
      ${record.answer || record.error ? `<section class="request-message"><h3>${record.error ? "Error" : "Response"}</h3><p>${esc(record.error || record.answer)}</p></section>` : ""}
      <details><summary>Raw request record</summary><pre class="code-block">${esc(json(metadata))}</pre></details>
      <div class="form-actions"><button class="btn primary" id="open-history-chat" type="button">Open in Playground</button></div>`;
    modal.querySelector("#open-history-chat").onclick = () => {
      sessionStorage.setItem(`ascg_open_history_${String(state.user?.id || "")}_${String(state.user?.workspace?.id || "")}`, id);
      location.href = "/pages/playground.html";
    };
  } catch (error) {
    content.innerHTML = `<p role="alert">${esc(error.message)}</p>`;
  }
}
function showCacheDetail(item){const modal=document.createElement("div");modal.className="modal-backdrop";modal.innerHTML=`<div class="modal"><button class="modal-close">×</button><div class="modal-head"><div><span class="eyebrow">Cache detail</span><h2>${esc(item.cache_type||"Cache entry")}</h2></div></div><div class="detail-grid"><div><span>Cache key</span><strong class="mono">${esc(item.key||item.redis_key||"-")}</strong></div><div><span>Type</span><strong>${esc(item.cache_type||"-")}</strong></div><div><span>Original query</span><strong>${esc(item.question||"-")}</strong></div><div><span>Answer</span><strong>${esc(item.answer||"-")}</strong></div><div><span>Similarity</span><strong>${item.similarity==null?"—":esc(Number(item.similarity).toFixed(4))}</strong></div><div><span>Embedding</span><strong>${esc(item.embedding_bytes?`${item.embedding_bytes} bytes`:"—")}</strong></div></div><details><summary>Raw cache fields</summary><pre class="code-block">${esc(json(item.fields||{}))}</pre></details></div>`;document.body.appendChild(modal);modal.querySelector(".modal-close").onclick=()=>modal.remove();modal.onclick=e=>{if(e.target===modal)modal.remove()}}

async function providersPage(){
 const root=document.getElementById("page-root");root.innerHTML=`<div class="loading">Loading providers…</div>`;
 try{
  const shouldOpenAdd=new URLSearchParams(location.search).get("add")==="1";
  const [p,r]=await Promise.all([api("/api/providers"),api("/api/routing/models")]);
  const providers=p.providers||[];
  const roleLabel=x=>x.role==="router"?"Routing model":x.role==="image"?"Image model":x.custom?"Custom answer provider":"Answer model";
  const displayName=x=>x.display_name||(x.name==="qwen_image"||x.name==="qwen_classifier"?"Qwen":x.name);
  const renderRows=(filter="")=>providers.filter(x=>`${displayName(x)} ${x.name} ${x.model} ${asList(x.models).join(" ")} ${x.base_url}`.toLowerCase().includes(filter.toLowerCase())).map(x=>{const models=asList(x.models).filter(Boolean);return `<section class="provider-connection"><div class="connection-head"><div class="provider-identity"><span class="provider-mark">${uiIcon("providers")}</span><div><h3>${esc(displayName(x))}</h3><span class="muted">${esc(roleLabel(x))}</span></div></div>${x.configured?(x.verified?statusBadge("Verified"):statusBadge("Needs test")):statusBadge("Not configured")}</div><div class="tag-list">${(models.length?models:[x.model]).filter(Boolean).map(m=>`<span class="model-chip">${esc(m)}${m===x.model&&x.active?' <span class="badge good">Default</span>':""}</span>`).join("")||'<span class="muted">No models configured</span>'}</div><div class="provider-endpoint">${esc(x.base_url||"Endpoint not configured")}</div><div class="connection-footer"><span class="muted">${x.configured?"Credentials saved securely":"Add your own API key"}</span><div class="table-actions">${x.selectable!==false&&x.configured?`<button class="btn small" data-use-provider="${esc(x.name)}" data-use-model="${esc(x.model||"")}">Use</button>`:""}${x.configured&&x.role!=="image"?`<button class="btn small" data-test-provider="${esc(x.name)}" data-test-model="${esc(x.model||"")}">Test</button>`:""}${x.role!=="router"?`<button class="btn small" data-manage-models="${esc(x.name)}">Models</button>`:""}${x.custom?`<button class="btn small danger" data-delete-provider="${esc(x.name)}">Delete</button>`:""}</div></div></section>`}).join("")||'<div class="empty-state"><strong>No matching providers</strong><span>Add a provider or adjust your search.</span></div>';

  const configured = providers.filter(provider => provider.configured);
  const active = p.active?.provider && p.active?.model ? p.active : null;
  if (!document.getElementById("add-provider")) document.getElementById("page-heading").insertAdjacentHTML("beforeend", '<button class="btn primary" type="button" id="add-provider">Add provider</button>');
  root.innerHTML = `<div class="provider-summary">
    <section class="panel provider-default">
      <h2>Default route</h2>
      ${active ? `<strong>${esc(active.provider)}</strong><code>${esc(active.model)}</code>` : '<p class="muted">Select a provider and model to set a default.</p>'}
    </section>
    <div class="kpi-grid">
      ${kpi("Connections",num(configured.length),"Providers with saved credentials")}
      ${kpi("Verified",num(configured.filter(provider => provider.verified).length),"Tested connections","","green")}
      ${kpi("Routing models",num((r.models || []).filter(model => model.enabled).length),"Enabled for model selection","","purple")}
    </div>
  </div>
  ${card("Provider connections", `<div class="page-toolbar compact-toolbar"><input id="provider-search" aria-label="Search providers or models" placeholder="Search providers or models…"><button class="btn" id="refresh-providers">Refresh</button></div><div id="provider-table"><div class="provider-connections">${renderRows()}</div></div>`)}
  ${card("Routing models", table(["Provider","Model","Enabled","Description"], (r.models || []).map(model => `<tr><td>${esc(model.provider === "qwen_image" ? "Qwen" : model.provider)}</td><td>${esc(model.model)}</td><td>${statusBadge(model.enabled ? "Enabled" : "Disabled")}</td><td>${esc(model.description || "—")}</td></tr>`), "No routing models configured"))}
  <div id="provider-modal-root"></div>`;
  const closeModal=()=>document.getElementById("provider-modal-root")?.replaceChildren();
  const runTest=async btn=>{const name=btn.dataset.testProvider,model=btn.dataset.testModel;btn.disabled=true;btn.textContent="Testing…";try{const d=await api("/api/providers/test",{method:"POST",body:JSON.stringify({name,model}),timeoutMs:30000});toast(`${name} connection succeeded · ${Number(d.latency_ms||0).toFixed(0)} ms`,"success")}catch(e){toast(`${name} test failed: ${e.message}`,"error")}finally{btn.disabled=false;btn.textContent="Test"}};
  const bindRows=()=>{root.querySelectorAll("[data-test-provider]").forEach(x=>x.onclick=()=>runTest(x));root.querySelectorAll("[data-use-provider]").forEach(x=>x.onclick=async()=>{try{await api("/api/settings",{method:"PATCH",body:JSON.stringify({default_provider:x.dataset.useProvider,default_model:x.dataset.useModel})});toast("Default provider updated","success");providersPage()}catch(e){toast(e.message,"error")}});root.querySelectorAll("[data-manage-models]").forEach(x=>x.onclick=()=>{const p=providers.find(v=>v.name===x.dataset.manageModels);if(!p)return;document.getElementById("provider-modal-root").innerHTML=`<div class="modal-backdrop"><div class="modal provider-modal"><button class="modal-close" id="close-models">×</button><div class="modal-head"><span class="eyebrow">Model management</span><h2>${esc(p.name)}</h2></div><p class="muted">Add models that use this provider's existing endpoint and credentials. Separate names with commas.</p><form id="models-form" class="settings-form"><label>Models<input id="managed-models" value="${esc((p.models||[]).join(", "))}" required></label><div id="models-status" class="muted"></div><div class="form-actions"><button type="button" class="btn" id="close-models-2">Cancel</button><button class="btn primary">Save models</button></div></form></div></div>`;const close=()=>document.getElementById("provider-modal-root")?.replaceChildren();document.getElementById("close-models").onclick=close;document.getElementById("close-models-2").onclick=close;document.getElementById("models-form").onsubmit=async e=>{e.preventDefault();const models=document.getElementById("managed-models").value.split(",").map(v=>v.trim()).filter(Boolean);try{await api(`/api/providers/${encodeURIComponent(p.name)}/models`,{method:"PATCH",body:JSON.stringify({models})});toast("Models updated","success");close();providersPage()}catch(err){document.getElementById("models-status").textContent=err.message}}});root.querySelectorAll("[data-delete-provider]").forEach(x=>x.onclick=async()=>{if(!confirm(`Delete ${x.dataset.deleteProvider}?`))return;try{await api(`/api/providers/${encodeURIComponent(x.dataset.deleteProvider)}`,{method:"DELETE"});toast("Provider deleted","success");providersPage()}catch(e){toast(e.message,"error")}})};
  bindRows();document.getElementById("provider-search").oninput=e=>{document.getElementById("provider-table").innerHTML=`<div class="provider-connections">${renderRows(e.target.value)}</div>`;bindRows()};document.getElementById("refresh-providers").onclick=providersPage;
  document.getElementById("add-provider").onclick=()=>{document.getElementById("provider-modal-root").innerHTML=`<div class="modal-backdrop"><div class="modal provider-modal"><button class="modal-close" id="close-provider">×</button><div class="modal-head"><span class="eyebrow">Provider setup</span><h2>Add and test a provider</h2></div><p class="muted">Use an API key from your provider. It is encrypted on the server and never returned to the browser.</p><form id="provider-form" class="settings-form"><div class="field-grid"><label>Provider name<input id="new-provider-name" required placeholder="deepseek, openai or qwen"></label><label>API key<div class="secret-field"><input id="new-provider-key" type="password" autocomplete="new-password" required><button type="button" class="btn small" id="toggle-provider-key" aria-pressed="false">Show</button></div></label><label>API key environment variable<input id="new-provider-key-env" value="PROVIDER_API_KEY"></label><label>Base URL<input id="new-provider-url" required placeholder="https://api.example.com/v1"></label><label>Models<input id="new-provider-models" required placeholder="model-a, model-b"></label><label>Capabilities<input id="new-provider-capabilities" value="general, reasoning, coding"></label></div><p class="muted provider-key-help">You can create an API key in your provider account dashboard. Do not paste it into chat, logs or shared documents.</p><label class="check"><input id="new-provider-enabled" type="checkbox" checked> Enable this provider for routing</label><div id="provider-form-status" class="muted" aria-live="polite"></div><div class="form-actions"><button type="button" class="btn" id="close-provider-2">Cancel</button><button type="button" class="btn" id="test-new-provider">Test Connection</button><button class="btn primary" type="submit">Add Provider</button></div></form></div></div>`;document.getElementById("close-provider").onclick=closeModal;document.getElementById("close-provider-2").onclick=closeModal;document.getElementById("toggle-provider-key").onclick=()=>{const input=document.getElementById("new-provider-key"),button=document.getElementById("toggle-provider-key"),visible=input.type==="text";input.type=visible?"password":"text";button.textContent=visible?"Show":"Hide";button.setAttribute("aria-pressed",String(!visible))};const payload=()=>({name:document.getElementById("new-provider-name").value.trim(),base_url:document.getElementById("new-provider-url").value.trim(),api_key_env:document.getElementById("new-provider-key-env").value.trim(),api_key:document.getElementById("new-provider-key").value,models:document.getElementById("new-provider-models").value.split(",").map(x=>x.trim()).filter(Boolean),capabilities:document.getElementById("new-provider-capabilities").value.split(",").map(x=>x.trim()).filter(Boolean),enabled:document.getElementById("new-provider-enabled").checked});document.getElementById("test-new-provider").onclick=async()=>{const x=payload(),model=x.models[0],status=document.getElementById("provider-form-status");if(!x.name||!x.base_url||!model||!x.api_key){status.textContent="Provider name, API key, base URL and one model are required.";return}try{const d=await api("/api/providers/test",{method:"POST",body:JSON.stringify({name:x.name,model,base_url:x.base_url,api_key:x.api_key}),timeoutMs:30000});status.textContent=`Connection succeeded in ${Number(d.latency_ms||0).toFixed(0)} ms.`}catch(e){status.textContent=e.message}};document.getElementById("provider-form").onsubmit=async e=>{e.preventDefault();try{await api("/api/providers",{method:"POST",body:JSON.stringify(payload())});toast("Provider added","success");closeModal();providersPage()}catch(e){document.getElementById("provider-form-status").textContent=e.message}}};
  if(shouldOpenAdd){history.replaceState(null,"",location.pathname);document.getElementById("add-provider").click()}
 }catch(e){root.innerHTML=`<div class="error-panel"><h2>Providers unavailable</h2><p>${esc(e.message)}</p>${button("Retry","btn primary",'id="retry-providers"')}</div>`;document.getElementById("retry-providers")?.addEventListener("click",providersPage)}}


async function metricsPage() {
  const root = document.getElementById("page-root");
  root.innerHTML = '<div class="loading" role="status">Loading analytics…</div>';
  try {
    const history = await api("/api/history?limit=500");
    const all = history.items || [];
    const tabs = ["Overview","Requests","Cache Performance","Token Usage","Cost Analysis","Provider Performance","Latency"];
    const savedTab = localStorage.getItem("ascg_analytics_tab");
    let active = tabs.includes(savedTab) ? savedTab : tabs[0];
    root.innerHTML = `<div class="analytics-toolbar history-filter">
      <div><strong>Workspace history</strong><p class="muted">Up to 500 recent requests. Dates use UTC.</p><p class="muted" id="analytics-count" role="status"></p></div>
      <div class="toolbar-actions analytics-actions">
        <label>From <input id="analytics-from" type="date"></label>
        <label>Through <input id="analytics-to" type="date"></label>
        <button class="btn" id="analytics-export">Export CSV</button>
        <button class="btn" id="analytics-refresh">Refresh</button>
      </div>
    </div>
    <div class="analytics-tabs" aria-label="Analytics views">${tabs.map(tab => `<button type="button" class="settings-tab" data-analytics-tab="${esc(tab)}">${esc(tab)}</button>`).join("")}</div>
    <div id="analytics-content"></div>`;
    const from = document.getElementById("analytics-from");
    const through = document.getElementById("analytics-to");
    const exportButton = document.getElementById("analytics-export");
    const filtered = () => all.filter(record => {
      if (!from.value && !through.value) return true;
      const day = historyDate(record.created_at);
      return day && (!from.value || day >= from.value) && (!through.value || day <= through.value);
    });
    const render = () => {
      const records = filtered();
      const metrics = metricsFromHistory(records);
      const {latencies, cache} = metrics;
      const content = document.getElementById("analytics-content");
      document.getElementById("analytics-count").textContent = `${num(records.length)} of ${num(all.length)} loaded requests`;
      exportButton.disabled = !records.length;
      root.querySelectorAll("[data-analytics-tab]").forEach(tab => {
        const current = tab.dataset.analyticsTab === active;
        tab.classList.toggle("active", current);
        tab.setAttribute("aria-pressed", String(current));
      });
      if (!records.length) {
        const empty = all.length ? "No requests match the selected dates." : "Usage appears here after your first recorded request.";
        content.innerHTML = card("No request data", `<div class="empty-state"><strong>${esc(empty)}</strong>${all.length ? "" : '<a class="btn" href="/pages/playground.html">Open Playground</a>'}</div>`);
        return;
      }
      const trend = historyCharts(records);
      const providers = new Map();
      for (const record of records) {
        if (record.cache_hit || !record.provider) continue;
        if (!providers.has(record.provider)) providers.set(record.provider, []);
        providers.get(record.provider).push(record);
      }
      const providerMetrics = [...providers].map(([provider, entries]) => [provider, metricsFromHistory(entries)]);

      const cacheCard = () => card("Cache outcomes", `<div class="cache-hero-value"><strong>${cache.hit_rate == null ? "—" : pct(cache.hit_rate)}</strong><span>cache hit rate</span></div>${cacheBreakdown(cache)}`);
      const overview = () => `<div class="analytics-overview">
        ${card("Request volume", trend.requests)}
        ${cacheCard()}
      </div>
      ${card("Token usage and cost", trend.usage)}`;
      const reports = {
        "Overview": overview,
        "Requests": () => card("Recorded requests", table(["Request","Provider","Model","Cache","Tokens","Cost"], records.map(record => `<tr><td><button class="btn small" type="button" data-request-detail="${esc(record.request_id)}">${esc(short(record.request_id, 25))}</button></td><td>${esc(record.provider || "—")}</td><td>${esc(record.model || "—")}</td><td>${cacheBadge(record)}</td><td>${num(record.consumed_tokens ?? record.total_tokens)}</td><td>${moneyShort(record.cost)}</td></tr>`))),
        "Cache Performance": () => `<div class="two-col">${cacheCard()}${card("Estimated savings", `<div class="metric-list"><div><span>Saved tokens</span><strong>${num(records.reduce((sum, item) => sum + (Number(item.saved_tokens) || 0), 0))}</strong></div><div><span>Saved cost when recorded</span><strong>${records.some(item => item.saved_cost != null) ? moneyShort(records.reduce((sum, item) => sum + (Number(item.saved_cost) || 0), 0)) : "—"}</strong></div></div>`)}</div>`,
        "Token Usage": () => card("Tokens over time", bucketChart(records, "Tokens", record => Number(record.consumed_tokens ?? record.total_tokens) || 0)),
        "Cost Analysis": () => `<div class="two-col">
          ${card("Cost over time", bucketChart(records, "Cost", record => Number(record.cost) || 0, moneyShort))}
          ${card("Cost by provider", table(["Provider","Recorded cost"], providerMetrics.sort((a,b) => b[1].total_cost - a[1].total_cost).map(([provider, value]) => `<tr><td>${esc(provider)}</td><td>${moneyShort(value.total_cost)}</td></tr>`), "No provider cost in this range."))}
        </div>${state.user?.is_admin ? '<a class="btn" href="/metrics" target="_blank" rel="noopener noreferrer">Open Prometheus metrics</a>' : ""}`,
        "Provider Performance": () => card("Requests attributed to providers", table(["Provider","Requests","Errors","Tokens","Cost","Mean latency"], providerMetrics.map(([provider, value]) => `<tr><td>${esc(provider)}</td><td>${num(value.total_requests)}</td><td>${num(value.failed_requests)}</td><td>${num(value.total_tokens)}</td><td>${moneyShort(value.total_cost)}</td><td>${latencyLabel(value.average_latency_ms)}</td></tr>`), "No provider requests in this range.")),
        "Latency": () => card("Latency percentiles", `<div class="kpi-grid latency-kpis">${[[.5,"P50","Median"],[.95,"P95","95th percentile"],[.99,"P99","99th percentile"]].map(([p, label, hint]) => kpi(label, latencyLabel(latencies.length ? percentile(latencies, p) : null), hint)).join("")}</div>`),
      };
      content.innerHTML = `<div class="kpi-grid analytics-kpis">
        ${kpi("Requests",num(metrics.total_requests),`${num(metrics.failed_requests)} failed`)}
        ${kpi("Used tokens",num(metrics.total_tokens),"Recorded usage","","cyan")}
        ${kpi("Recorded cost",moneyShort(metrics.total_cost),"USD","","gold")}
        ${kpi("Mean latency",latencyLabel(metrics.average_latency_ms),`${num(latencies.length)} measured requests`,"","purple")}
      </div>${reports[active]()}`;
      content.querySelectorAll("[data-request-detail]").forEach(trigger => {
        trigger.onclick = () => showRequest(trigger.dataset.requestDetail);
      });
    };
    from.onchange = through.onchange = render;
    root.querySelectorAll("[data-analytics-tab]").forEach(tab => {
      tab.onclick = () => {
        active = tab.dataset.analyticsTab;
        localStorage.setItem("ascg_analytics_tab", active);
        render();
      };
    });
    document.getElementById("analytics-refresh").onclick = metricsPage;
    exportButton.onclick = () => {
      const columns = ["request_id","provider","model","cache_type","total_tokens","cost","latency_ms","created_at"];
      const quote = value => '"' + String(value ?? "").replace(/"/g, '""') + '"';
      const csv = [columns.join(","), ...filtered().map(record => columns.map(key => quote(record[key])).join(","))].join("\n");
      const url = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
      const link = document.createElement("a");
      link.href = url;
      link.download = "gateway-analytics.csv";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    render();
  } catch (error) {
    root.innerHTML = `<div class="error-panel"><h2>Analytics unavailable</h2><p>${esc(error.message)}</p>${button("Retry","btn primary",'id="retry-analytics"')}</div>`;
    document.getElementById("retry-analytics").onclick = metricsPage;
  }
}

async function systemPage(){
 const root=document.getElementById("page-root");
 root.innerHTML=`<div class="loading">Loading system…</div>`;
 try{
  const [s,l,h,c]=await Promise.all([
   api("/api/system"),
   api("/api/lifecycle"),
   api("/health").catch(e=>({error:e.message})),
   api("/cache/stats").catch(e=>({error:e.message}))
  ]);
  const app=s.application||{}, r=s.redis||{};
  root.innerHTML=`<div class="system-banner ${h?.status==="ok"||h?.status==="healthy"?"good":"warn"}"><div><span class="eyebrow">Runtime diagnostics</span><h2>${esc(app.name||s.gateway?.name||"AI Semantic Cache Gateway")}</h2></div><span>${r.connected?"Redis connected":"Redis unavailable"}</span></div><div class="two-col">${card("Application & Gateway",`<div class="detail-grid compact"><div><span>Name</span><strong>${esc(app.name||s.gateway?.name||"—")}</strong></div><div><span>Version</span><strong>${esc(app.version||s.gateway?.version||"—")}</strong></div><div><span>Provider</span><strong>${esc(s.gateway?.provider||"—")}</strong></div><div><span>Model</span><strong>${esc(s.gateway?.model||"—")}</strong></div><div><span>Python</span><strong>${esc(s.runtime?.python||"-")}</strong></div><div><span>Platform</span><strong>${esc(s.runtime?.platform||"-")}</strong></div></div>`)}${card("Redis / Cache",`<div class="detail-grid compact"><div><span>Connected</span><strong>${r.connected?"Yes":"No"}</strong></div><div><span>Host</span><strong>${esc(r.host||"-")}</strong></div><div><span>Port</span><strong>${esc(r.port??"-")}</strong></div><div><span>Index</span><strong>${esc(r.index_name||r.index||"—")}</strong></div><div><span>Algorithm</span><strong>${esc(r.algorithm||"-")}</strong></div><div><span>Distance</span><strong>${esc(r.distance_metric||"-")}</strong></div><div><span>Vector Dimension</span><strong>${esc(r.vector_dim??r.vector_dimension??"—")}</strong></div><div><span>Threshold</span><strong>${esc(s.cache?.threshold??c.threshold??"—")}</strong></div></div>`)}</div>${card("Embedding & Runtime",`<div class="detail-grid compact"><div><span>Embedding model</span><strong>${esc(s.embedding?.model||"-")}</strong></div><div><span>Python</span><strong>${esc(s.runtime?.python||"-")}</strong></div><div><span>Platform</span><strong>${esc(s.runtime?.platform||"-")}</strong></div></div>`)}${card("Lifecycle",`<pre class="code-block">${esc(json(l))}</pre>`)}${card("Health",`<pre class="code-block">${esc(json(h))}</pre>`)}${card("Cache Stats",`<pre class="code-block">${esc(json(c))}</pre>`)}`;
 }catch(e){root.innerHTML=`<div class="error-panel"><h2>System unavailable</h2><p>${esc(e.message)}</p></div>`}
}

async function adminPage(){
 const root=document.getElementById("page-root");root.innerHTML=`<div class="loading">Loading admin console…</div>`;
 try{
  const [overview,health,analytics]=await Promise.all([api("/api/admin/overview"),api("/api/admin/health"),api("/api/admin/analytics?period=7d")]);
  const u=overview.users||{},r=overview.requests||{},usage=overview.usage||{},db=health.database||{},redis=health.redis||{},embedding=health.embedding||{};
  const chart=(items,key,label)=>{const values=(items||[]).map(x=>Number(x[key]||0)),max=Math.max(...values,1);return values.length?`<div class="admin-bars" aria-label="${esc(label)}">${values.map((value,i)=>`<div class="admin-bar-wrap"><div class="admin-bar" style="height:${Math.max(4,value/max*100)}%" title="${esc(items[i].bucket||"")}: ${esc(value)}"></div><span>${esc(String(items[i].bucket||"").slice(5,10))}</span></div>`).join("")}</div>`:`<div class="chart-empty">No data available.</div>`};
  const summary=`<div class="kpi-grid">${kpi("Users",num(u.total),`${num(u.active)} active` ,"U","blue")}${kpi("Online estimate",num(u.online_estimate),`Last ${u.online_window_minutes||15} minutes`,"◉","green")}${kpi("Workspaces",num(overview.workspaces?.total),"Personal and managed","W","purple")}${kpi("Requests",num(r.total),`${pct(r.cache_hit_rate||0)} cache hit rate`,"R","gold")}${kpi("Tokens",num(usage.total_tokens),"Persisted usage","T","cyan")}${kpi("Estimated cost",money(usage.estimated_cost),"USD, persisted history","$","slate")}</div>`;
  root.innerHTML=`<div class="admin-heading"><div><span class="eyebrow">Restricted platform view</span><h2>Administrator console</h2><p class="muted">Read-only operational data. Provider credentials and private payloads are never shown here.</p></div><button class="btn" id="admin-refresh">Refresh</button></div>${summary}<div class="two-col">${card("Service health",`<div class="admin-health-grid"><div><span>Gateway</span>${statusBadge(health.gateway?.status||"unknown")}</div><div><span>Database</span>${statusBadge(db.ready?"Connected":"Unavailable")}</div><div><span>Redis / HNSW</span>${statusBadge(redis.ready?"Connected":"Unavailable")}</div><div><span>Embedding</span>${statusBadge(embedding.ready?"Ready":"Loading")}</div><div><span>Image storage</span>${statusBadge(health.storage?.configured?health.storage.backend||"Configured":"Not configured")}</div></div>`)}${card("Request volume · 7 days",chart(analytics.request_volume,"requests","Request volume"))}</div><div class="two-col">${card("Token consumption",chart(analytics.token_consumption,"tokens","Token consumption"))}${card("Cache performance",chart(analytics.cache_performance,"hits","Cache hits"))}</div>${card("Users",`<div class="page-toolbar compact-toolbar"><input id="admin-user-search" placeholder="Search by email or user ID" maxlength="120"><select id="admin-user-status"><option value="all">All statuses</option><option value="active">Active</option><option value="pending">Pending</option><option value="disabled">Disabled</option></select><select id="admin-user-sort"><option value="created_at">Newest</option><option value="email">Email</option><option value="requests">Requests</option><option value="tokens">Tokens</option><option value="last_active">Last active</option></select><span id="admin-user-count" class="muted"></span></div><div id="admin-user-table"><div class="loading">Loading users…</div></div>`)}<div id="admin-detail-root"></div>`;
  const renderTable=(data)=>{const items=data.items||[];document.getElementById("admin-user-count").textContent=`${num(data.pagination?.total||0)} users`;document.getElementById("admin-user-table").innerHTML=table(["User","Status","Workspaces","Requests","Tokens","Last active","Action"],items.map(item=>`<tr><td><strong>${esc(item.email)}</strong><small>ID ${esc(item.id)}</small></td><td>${statusBadge(item.status)}</td><td>${num(item.workspace_count)}</td><td>${num(item.request_count)}</td><td>${num(item.total_tokens)}</td><td>${esc(item.last_active_at||"Never")}</td><td><button class="btn small" data-admin-user="${esc(item.id)}">View</button></td></tr>`),"No matching users");document.querySelectorAll("[data-admin-user]").forEach(button=>button.onclick=()=>showDetail(button.dataset.adminUser))};
  const loadUsers=async()=>{const params=new URLSearchParams({page:"1",page_size:"50",q:document.getElementById("admin-user-search").value,status:document.getElementById("admin-user-status").value,sort:document.getElementById("admin-user-sort").value,order:"desc"});try{renderTable(await api(`/api/admin/users?${params}`))}catch(e){document.getElementById("admin-user-table").innerHTML=`<div class="error-panel"><p>${esc(e.message)}</p></div>`}};
  const showDetail=async id=>{const mount=document.getElementById("admin-detail-root");mount.innerHTML=`<div class="modal-backdrop"><div class="modal"><div class="loading">Loading user details…</div></div></div>`;try{const d=await api(`/api/admin/users/${encodeURIComponent(id)}`),user=d.user||{},summary=d.request_summary||{};mount.innerHTML=`<div class="modal-backdrop"><div class="modal admin-detail"><button class="modal-close" id="close-admin-detail">×</button><div class="modal-head"><span class="eyebrow">User ${esc(user.id)}</span><h2>${esc(user.email)}</h2></div><div class="detail-grid compact"><div><span>Status</span><strong>${esc(user.status)}</strong></div><div><span>Created</span><strong>${esc(user.created_at||"-")}</strong></div><div><span>Workspaces</span><strong>${num(user.workspace_count)}</strong></div><div><span>Providers</span><strong>${num(d.provider_count)}</strong></div><div><span>Requests</span><strong>${num(summary.total)}</strong></div><div><span>Tokens</span><strong>${num(summary.tokens)}</strong></div><div><span>Estimated cost</span><strong>${money(summary.estimated_cost)}</strong></div><div><span>Last active</span><strong>${esc(user.last_active_at||"Never")}</strong></div></div>${card("Workspace ownership",table(["ID","Name"],(d.workspaces||[]).map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.name)}</td></tr>`),"No workspaces"))}${card("Provider metadata",table(["Provider","Role","Default model","Models","Status"],(d.providers||[]).map(x=>`<tr><td>${esc(x.display_name||x.name)}</td><td>${esc(x.role)}</td><td>${esc(x.default_model||"-")}</td><td>${num(x.model_count)}</td><td>${statusBadge(x.enabled?x.status||"enabled":"disabled")}</td></tr>`),"No provider metadata"))}${card("Recent requests",table(["Request","Provider","Model","Cache","Tokens","Status","Created"],(summary.recent||[]).map(x=>`<tr><td class="mono">${esc(short(x.request_id,18))}</td><td>${esc(x.provider||"-")}</td><td>${esc(x.model||"-")}</td><td>${statusBadge(x.cache_hit?"Hit":"Miss")}</td><td>${num(x.total_tokens)}</td><td>${statusBadge(x.status||"-")}</td><td>${esc(x.created_at||"-")}</td></tr>`),"No requests"))}</div></div>`;document.getElementById("close-admin-detail").onclick=()=>mount.replaceChildren()}catch(e){mount.innerHTML=`<div class="error-panel"><p>${esc(e.message)}</p></div>`}};
  ["admin-user-search","admin-user-status","admin-user-sort"].forEach(id=>document.getElementById(id).oninput=loadUsers);document.getElementById("admin-refresh").onclick=adminPage;await loadUsers();
 }catch(e){root.innerHTML=`<div class="error-panel"><h2>Admin console unavailable</h2><p>${esc(e.message)}</p>${button("Retry","btn primary",'id="retry-admin"')}</div>`;document.getElementById("retry-admin")?.addEventListener("click",adminPage)}
}

async function settingsPage(){
 const root=document.getElementById("page-root");root.innerHTML=`<div class="loading">Loading settings…</div>`;
 try{
  const [d,p,r]=await Promise.all([api("/api/settings"),api("/api/providers"),api("/api/routing/models")]);

  const c=d.cache||{},a=d.ai_configuration||{},g=d.general||{},l=d.logging||{},sec=d.security||{},n=d.notifications||{};
  const sections=["General","AI Configuration","Cache Settings","Database","Logging","Security","Notification","About"];
  const preferred = new URLSearchParams(location.search).get("section") || localStorage.getItem("ascg_settings_section");
  const active = sections.includes(preferred) ? preferred : sections[0];
  const providerOptions=(p.providers||[]).filter(x=>(x.configured||x.active)&&x.selectable!==false).map(x=>`<option value="${esc(x.name)}" ${x.name===a.default_provider?"selected":""}>${esc(x.display_name||x.name)}</option>`).join("");
  const modelOptions=(r.models||[]).filter(x=>x.provider===a.default_provider).map(x=>`<option value="${esc(x.model)}" ${x.model===a.default_model?"selected":""}>${esc(x.model)}</option>`).join("");
  const info=(title,value)=>`<div class="setting-info"><span>${esc(title)}</span><strong>${esc(value??"-")}</strong></div>`;
  const form=(body,button="Save Settings")=>`<form id="settings-form" class="settings-form">${body}<div class="form-actions"><span id="settings-dirty" class="muted" aria-live="polite"></span><button class="btn" id="settings-discard" type="button" disabled>Discard</button><button class="btn primary" type="submit">${button}</button></div></form>`;
  const body=()=>{
   if(active==="General")return form(`<div class="field-grid"><label>Application name<input id="set-app-name" value="${esc(g.app_name||d.application?.name||"")}" required></label><label>Environment<input value="${esc(g.environment||"development")}" disabled></label><label>Version<input value="${esc(g.version||d.application?.version||"")}" disabled></label><label>API port<input value="${esc(d.application?.port||8000)}" disabled></label></div><p class="muted">Application name is stored in the gateway runtime configuration. Environment and port are read-only process settings.</p>`);
   if(active==="AI Configuration")return form(`<div class="field-grid"><label>Default provider<select id="set-provider">${providerOptions||`<option value="">No configured provider</option>`}</select></label><label>Default model<select id="set-model">${modelOptions||`<option value="${esc(a.default_model||"")}">${esc(a.default_model||"No configured model")}</option>`}</select></label><label>Request timeout (seconds)<input id="set-timeout" type="number" min="1" max="600" value="${esc(a.timeout??d.llm?.timeout??30)}"></label><label>Max retries<input id="set-retries" type="number" min="0" max="5" value="${esc(a.max_retries??d.llm?.max_retries??0)}"></label></div><div class="setting-list">${info("Cost tracking",a.cost_tracking?"Enabled":"Disabled")}${info("Configured providers",(p.providers||[]).filter(x=>x.configured).length)}</div>`);
   if(active==="Cache Settings")return form(`<div class="toggle-list"><label class="check"><input id="set-exact" type="checkbox" ${c.exact_enabled!==false?"checked":""}> Enable Exact Cache</label><label class="check"><input id="set-semantic" type="checkbox" ${c.semantic_enabled!==false?"checked":""}> Enable Semantic Cache</label></div><div class="field-grid"><label>Similarity threshold<input id="set-threshold" type="number" min="0" max="1" step="0.01" value="${esc(Number(c.threshold??0.75).toFixed(2))}"></label><label>Cache TTL (seconds)<input id="set-ttl" type="number" min="60" max="604800" value="${esc(c.ttl??86400)}"></label><label>Max cached answer length<input id="set-max-answer" type="number" min="256" max="200000" value="${esc(c.max_answer_length??20000)}"></label><label>Embedding model<input value="${esc(d.embedding?.model||"")}" disabled></label></div><div class="setting-list">${info("Redis",d.redis?.connected?"Connected":"Unavailable")}${info("Vector index",c.index_name)}${info("Distance metric",c.distance_metric)}${info("Vector dimension",c.vector_dimension)}</div>`);
   if(active==="Database")return `${card("Database",`<div class="setting-list">${info("Engine",d.database?.type)}${info("Path",d.database?.path)}${info("Status",d.database?.status)}${info("Recorded requests","Available through Requests")}</div><p class="muted">This project uses SQLite for request history. Redis remains the cache and vector-search backend.</p><div class="form-actions"><a class="btn" href="/pages/requests.html">Open Request History</a><button class="btn danger" id="settings-clear-history" type="button">Clear History</button></div>`)}${card("Redis Connection",`<div class="setting-list">${info("Host",d.redis?.host)}${info("Port",d.redis?.port)}${info("Status",d.redis?.connected?"Connected":"Unavailable")}</div>`)}`;
   if(active==="Logging")return form(`<div class="field-grid"><label>Log level<select id="set-log-level">${["DEBUG","INFO","WARNING","ERROR","CRITICAL"].map(x=>`<option ${String(l.level||"INFO").toUpperCase()===x?"selected":""}>${x}</option>`).join("")}</select></label><label>Log file<input id="set-log-file" value="${esc(l.file||"logs/gateway.log")}"></label></div><label class="check"><input id="set-log-file-enabled" type="checkbox" ${l.to_file?"checked":""}> Write application logs to file</label><p class="muted">Changes apply to the running process and are retained in the runtime settings file.</p>`);
   if(active==="Security")return form(`<div class="setting-list">${info("Authentication",sec.auth_enabled?"Enabled":"Not configured")}${info("Secret key",sec.secret_configured?"Configured":"Missing")}</div><div class="field-grid"><label>Access token expiration (hours)<input id="set-token-hours" type="number" min="1" max="720" value="${esc(sec.token_expiration_hours||24)}"></label></div><p class="muted">API secret keys remain in environment variables and are never shown or saved by this page.</p>`);
   if(active==="Notification")return form(`<div class="setting-list">${info("SMTP",n.smtp_configured?"Configured":"Not configured")}${info("From email",n.from_email||"-")}</div><label class="check"><input id="set-notifications" type="checkbox" ${n.enabled?"checked":""}> Enable notification hooks</label><p class="muted">Email delivery still requires SMTP credentials in the backend environment.</p>`);
   return card("About",`<div class="setting-list">${info("Application",d.about?.name||d.application?.name)}${info("Version",d.about?.version||d.application?.version)}${info("Embedding model",d.embedding?.model)}${info("Runtime",g.environment||"development")}</div><h3>Enabled capabilities</h3><div class="tag-list">${(d.about?.features||[]).map(x=>`<span class="badge good">${esc(x)}</span>`).join("")}</div><p class="muted">The Settings page now reflects the live gateway configuration. Provider secrets and process-only values remain protected.</p>`);
  };
  root.innerHTML=`<div class="settings-layout"><aside class="settings-nav"><div class="eyebrow">Gateway settings</div>${sections.map(x=>`<button class="settings-tab ${x===active?"active":""}" data-settings-section="${esc(x)}">${esc(x)}</button>`).join("")}</aside><div class="settings-content"><div class="settings-heading"><div><span class="eyebrow">Configuration</span><h2>${esc(active)}</h2><p>Manage the live gateway behavior and inspect connected services.</p></div><button class="btn" id="settings-refresh">Refresh</button></div>${body()}</div></div>`;
  root.querySelectorAll("[data-settings-section]").forEach(button=>button.onclick=()=>{localStorage.setItem("ascg_settings_section",button.dataset.settingsSection);const url=new URL(location.href);url.searchParams.set("section",button.dataset.settingsSection);history.replaceState(null,"",url);settingsPage()});
  document.getElementById("settings-refresh").onclick=settingsPage;
  const provider=document.getElementById("set-provider"),model=document.getElementById("set-model");
  provider?.addEventListener("change",()=>{const options=(r.models||[]).filter(x=>x.provider===provider.value);model.innerHTML=options.map(x=>`<option value="${esc(x.model)}">${esc(x.model)}</option>`).join("")});
  document.getElementById("settings-clear-history")?.addEventListener("click",async()=>{if(!confirm("Clear all request history?"))return;try{await api("/api/history",{method:"DELETE"});toast("History cleared","success");settingsPage()}catch(e){toast(e.message,"error")}});
  const settingsForm=document.getElementById("settings-form");
  if(settingsForm){const discard=document.getElementById("settings-discard"),dirty=document.getElementById("settings-dirty");const markDirty=()=>{discard.disabled=false;dirty.textContent="Unsaved changes"};settingsForm.querySelectorAll("input,select").forEach(field=>field.addEventListener("input",markDirty));discard?.addEventListener("click",settingsPage);settingsForm.addEventListener("submit",async event=>{event.preventDefault();const payload={};if(active==="General")payload.app_name=document.getElementById("set-app-name").value.trim();if(active==="AI Configuration"){payload.default_provider=provider.value;payload.default_model=model.value;payload.llm_timeout=Number(document.getElementById("set-timeout").value);payload.llm_max_retries=Number(document.getElementById("set-retries").value)}if(active==="Cache Settings"){payload.exact_cache_enabled=document.getElementById("set-exact").checked;payload.semantic_cache_enabled=document.getElementById("set-semantic").checked;payload.cache_threshold=Number(document.getElementById("set-threshold").value);payload.cache_ttl=Number(document.getElementById("set-ttl").value);payload.cache_max_answer_length=Number(document.getElementById("set-max-answer").value)}if(active==="Logging"){payload.log_level=document.getElementById("set-log-level").value;payload.log_file=document.getElementById("set-log-file").value.trim();payload.log_to_file=document.getElementById("set-log-file-enabled").checked}if(active==="Security")payload.auth_token_expiration_hours=Number(document.getElementById("set-token-hours").value);if(active==="Notification")payload.notifications_enabled=document.getElementById("set-notifications").checked;try{await api("/api/settings",{method:"PATCH",body:JSON.stringify(payload)});toast("Settings saved","success");settingsPage()}catch(e){toast(e.message,"error")}})}
 }catch(e){root.innerHTML=`<div class="error-panel"><h2>Settings unavailable</h2><p>${esc(e.message)}</p>${button("Retry","btn primary",'id="retry-settings"')}</div>`;document.getElementById("retry-settings")?.addEventListener("click",settingsPage)}}


const PLAYGROUND_TABS = [
  ["chat","Chat","playground"],
  ["raw","Raw Request","code"],
  ["routing","Routing Preview","route"],
  ["batch","Batch Test","layers"],
];

async function playgroundPage() {
  const root = document.getElementById("page-root");
  root.innerHTML = '<div class="loading" role="status">Loading Playground…</div>';
  try {
    const [models, onboarding] = await Promise.all([api("/api/routing/models"), api("/api/onboarding")]);
    if (!onboarding.configured_provider_count || !onboarding.verified_provider_count || !(models.models || []).length) {
      const needsVerification = Boolean(onboarding.configured_provider_count);
      root.innerHTML = `<div class="empty-state playground-onboarding"><span class="workbench-mark">${uiIcon("providers")}</span><strong>${needsVerification ? "Verify a provider to start" : "Connect a provider to start"}</strong><p>${needsVerification ? "Test a saved provider connection before sending requests." : "Add your provider’s API key to run text or image requests."}</p><a class="btn primary" href="${needsVerification ? "/pages/providers.html" : "/pages/providers.html?add=1"}">${needsVerification ? "Open Providers" : "Add a provider"}</a></div>`;
      return;
    }
    const options = models.models.map(model => `<option value="${esc(model.model)}">${esc(model.provider === "qwen_image" ? "Qwen" : model.provider)} · ${esc(model.model)}</option>`).join("");
    root.innerHTML = `<div class="pg-tabs" aria-label="Playground modes">${PLAYGROUND_TABS.map(([key, name, icon]) => `<button type="button" class="pg-tab" data-tab="${key}" aria-controls="pg-mode-${key}">${uiIcon(icon)} ${name}</button>`).join("")}</div>
      <div id="pg-tab-content">${PLAYGROUND_TABS.map(([key]) => `<section class="pg-mode" id="pg-mode-${key}" hidden></section>`).join("")}</div>`;
    const renderers = {chat: node => renderChat(node, options), raw:renderRaw, routing:renderRouting, batch:renderBatch};
    const tabs = [...root.querySelectorAll(".pg-tab")];
    const select = key => {
      const selected = Object.hasOwn(renderers, key) ? key : "chat";
      closeChatFullscreen();
      tabs.forEach(tab => {
        const active = tab.dataset.tab === selected;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-pressed", String(active));
        document.getElementById(`pg-mode-${tab.dataset.tab}`).hidden = !active;
      });
      const node = document.getElementById(`pg-mode-${selected}`);
      if (!node.hasChildNodes()) renderers[selected](node);
      if (selected === "chat") scrollChatToLatest();
    };
    const selectFromUrl = () => select(new URLSearchParams(location.search).get("tab"));
    selectFromUrl();
    tabs.forEach(tab => {
      tab.onclick = () => {
        if (tab.classList.contains("active")) return;
        const url = new URL(location.href);
        if (tab.dataset.tab === "chat") url.searchParams.delete("tab");
        else url.searchParams.set("tab", tab.dataset.tab);
        history.pushState(null, "", url);
        selectFromUrl();
      };
    });
    window.addEventListener("popstate", selectFromUrl);
  } catch (error) {
    root.innerHTML = `<div class="error-panel"><h2>Playground unavailable</h2><p>${esc(error.message)}</p></div>`;
  }
}

function workbench(intro, editor, output) {
  return `<div class="playground-workbench"><p class="workbench-intro">${esc(intro)}</p><div class="workbench-grid">${editor}${output}</div></div>`;
}

function requestHistoryLink(id) {
  return id ? `<a class="btn small" href="/pages/requests.html?id=${esc(encodeURIComponent(id))}">Open in Requests</a>` : "";
}

function renderRaw(root) {
  const template = json({model:"auto", messages:[{role:"user", content:""}]});
  root.innerHTML = workbench("Send a JSON payload to the Playground endpoint and inspect the full response.",
    card("Request body", `<div class="endpoint-card"><span>POST</span><code>/api/playground</code></div>
      <label class="sr-only" for="raw-json">JSON request body</label>
      <textarea class="workbench-editor code-editor" id="raw-json" rows="12" spellcheck="false">${esc(template)}</textarea>
      <div class="form-actions"><button class="btn primary" id="raw-send" type="button">Send raw request</button></div>`),
    card("Response", `<div id="raw-output"><p class="workbench-empty">Send a request to view its JSON response here.</p></div>`));
  const trigger = document.getElementById("raw-send");
  const output = document.getElementById("raw-output");
  trigger.onclick = async () => {
    try {
      const body = JSON.parse(document.getElementById("raw-json").value);
      trigger.disabled = true;
      output.innerHTML = '<p class="workbench-empty" role="status">Waiting for the gateway…</p>';
      const data = await api("/api/playground", {method:"POST", body:JSON.stringify(body), timeoutMs:120000});
      const response = data.response || data;
      output.innerHTML = `<div class="workbench-result-meta">${statusBadge("Completed")}${requestHistoryLink(response.request_id || response.context?.request_id)}</div><pre class="code-block" id="raw-response">${esc(json(data))}</pre>`;
    } catch (error) {
      output.innerHTML = `<p class="workbench-empty" role="alert">${esc(error.message)}</p>`;
    } finally {
      trigger.disabled = false;
    }
  };
}

function renderRouting(root) {
  root.innerHTML = workbench("Check which model the gateway would choose for a prompt before running it.",
    card("Prompt", `<label class="sr-only" for="route-message">Prompt to route</label><textarea id="route-message" class="workbench-editor" rows="9" placeholder="Enter a prompt to preview its route…"></textarea><div class="form-actions"><button class="btn primary" id="route-run" type="button">Preview routing</button></div>`),
    card("Routing decision", '<div id="route-result"><p class="workbench-empty">Model selection and reasons will appear here.</p></div>'));
  const trigger = document.getElementById("route-run");
  trigger.onclick = async () => {
    const text = document.getElementById("route-message").value.trim();
    if (!text) return toast("Enter a prompt first", "error");
    const output = document.getElementById("route-result");
    trigger.disabled = true;
    output.innerHTML = '<p class="workbench-empty" role="status">Checking available models…</p>';
    try {
      const data = await api("/api/routing/diagnostics", {method:"POST", body:JSON.stringify({messages:[{role:"user", content:text}]})});
      const selected = data.selected;
      output.innerHTML = selected ? `<div class="route-result">
        <div class="route-selected"><span class="workbench-mark">${uiIcon("route")}</span><div><span>${esc(selected.provider)}</span><strong>${esc(selected.model)}</strong></div></div>
        <dl class="workbench-measurements"><div><dt>Score</dt><dd>${esc(selected.score ?? "—")}</dd></div><div><dt>Confidence</dt><dd>${esc(selected.confidence ?? "—")}</dd></div></dl>
        ${selected.reasons?.length ? `<h3>Why it was selected</h3><ul>${selected.reasons.map(reason => `<li>${esc(reason)}</li>`).join("")}</ul>` : ""}
      </div>` : '<p class="workbench-empty">No model was selected for this prompt.</p>';
    } catch (error) {
      output.innerHTML = `<p class="workbench-empty" role="alert">${esc(error.message)}</p>`;
    } finally {
      trigger.disabled = false;
    }
  };
}

function renderBatch(root) {
  root.innerHTML = workbench("Enter one prompt per line. The gateway runs them in order with automatic model selection.",
    card("Prompts", `<label class="sr-only" for="batch-input">Batch prompts</label><textarea id="batch-input" class="workbench-editor" rows="11" placeholder="Enter one prompt per line…"></textarea><div class="form-actions"><button class="btn primary" id="batch-run" type="button">Run batch</button></div>`),
    card("Batch results", '<div id="batch-results"><p class="workbench-empty">Run a batch to see the outcome for each prompt.</p></div>'));
  document.getElementById("batch-run").onclick = runBatch;
}

async function runBatch() {
  const lines = document.getElementById("batch-input").value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!lines.length) return toast("Enter at least one prompt", "error");
  const trigger = document.getElementById("batch-run");
  const output = document.getElementById("batch-results");
  trigger.disabled = true;
  output.innerHTML = `<p class="batch-progress" role="status">Running 0 of ${lines.length} requests</p><ol class="batch-results-list"></ol>`;
  const progress = output.querySelector(".batch-progress");
  const results = output.querySelector("ol");
  let errors = 0;
  try {
    for (const text of lines) {
      const row = document.createElement("li");
      row.className = "batch-row";
      try {
        const data = await api("/api/playground", {method:"POST", body:JSON.stringify({model:"auto", messages:[{role:"user",content:text}], user:state.user?.email || null}), timeoutMs:120000});
        const response = data.response || data;
        row.innerHTML = `<div><strong>${esc(short(text,100))}</strong><span>${esc(response.llm?.model || response.model || "Completed")}</span></div><div>${cacheBadge(response)}${requestHistoryLink(response.request_id || response.context?.request_id)}</div>`;
      } catch (error) {
        errors++;
        row.innerHTML = `<div><strong>${esc(short(text,100))}</strong><span>${esc(error.message)}</span></div>${statusBadge("Error")}`;
      }
      results.append(row);
      progress.textContent = `Completed ${results.children.length} of ${lines.length} requests · ${errors} failed`;
    }
  } finally {
    trigger.disabled = false;
  }
}

function onboardingCard(data){
 if(!data?.show_getting_started)return "";
 const state=data.state||"no_provider";
 const copy={
  no_provider:{title:"Welcome to AI Semantic Cache Gateway",subtitle:"Connect your first AI provider and start using your gateway in minutes."},
  needs_verification:{title:"Finish connecting your provider",subtitle:"Your provider is saved securely. Test the connection to unlock the Playground."},
  ready_for_playground:{title:"Your gateway is ready",subtitle:"Send your first request in Playground, then explore your usage and analytics."}
 }[state]||{title:"Welcome to AI Semantic Cache Gateway",subtitle:"Connect your first AI provider and start using your gateway in minutes."};
 const primary=data.primary_action||{label:"Add Your First Provider",href:"/pages/providers.html?add=1"};
 const statusLabel=value=>value==="completed"?"Completed":value==="current"?"Current":"Locked";
 const steps=(data.steps||[]).map((step,index)=>{const locked=step.status==="locked";return `<article class="onboarding-step ${esc(step.status||"locked")}"><div class="onboarding-step-top"><span class="onboarding-step-icon">${index+1}</span><span class="onboarding-status ${esc(step.status||"locked")}">${statusLabel(step.status)}</span></div><h3>${esc(step.title)}</h3><p>${esc(step.description)}</p>${locked?"":`<a class="btn small" href="${esc(step.href||"#")}">${esc(step.action||"Open")}</a>`}</article>`}).join("");
 return `<section class="getting-started" aria-labelledby="getting-started-title"><div class="getting-started-copy"><span class="eyebrow">Getting started</span><h2 id="getting-started-title">${esc(copy.title)}</h2><p>${esc(copy.subtitle)}</p></div><div class="onboarding-actions"><a class="btn primary onboarding-primary" href="${esc(primary.href)}">${esc(primary.label)}</a><a class="btn onboarding-secondary" href="${esc(data.learn_href||"/pages/playground.html?tab=routing")}">Learn How It Works</a></div><div class="onboarding-steps" aria-label="Getting started steps">${steps}</div></section>`;
}

function authPage(kind){
 if(kind!=="login")return;
 const root=document.getElementById("auth-root");
 const query=new URLSearchParams(location.search);
 const oauthError=query.get("oauth_error");
 const message=oauthError==="oauth_cancelled"?"Sign-in was cancelled.":oauthError?"Sign-in could not be completed. Please try again.":"";

 root.innerHTML = `<div class="auth-shell">
  <section class="auth-story">
    ${brand()}
    <div class="auth-story-copy"><h2>One gateway for your model requests.</h2><p>Connect a provider, test routing, and see when the cache answers a request.</p></div>
    <div class="auth-flow" aria-label="Prompt, gateway, then cache or model provider">
      <div><span class="workbench-mark">${uiIcon("playground")}</span><strong>Prompt</strong></div>
      <span class="auth-flow-line" aria-hidden="true"></span>
      <div><span class="workbench-mark">${uiIcon("gateway")}</span><strong>Gateway</strong></div>
      <span class="auth-flow-line" aria-hidden="true"></span>
      <div><span class="workbench-mark">${uiIcon("cache")}</span><strong>Cache or provider</strong></div>
    </div>
  </section>
  <div class="auth-card">
    <div class="auth-mobile-brand">${brand()}</div>
    <h1>Sign in</h1><p>Open your Semantic Gateway workspace.</p>
    <div class="oauth-actions">
      <a class="btn primary full oauth-btn github" href="/api/auth/oauth/github/start">${uiIcon("github")}Continue with GitHub</a>
      <a class="btn full oauth-btn google" href="/api/auth/oauth/google/start"><span class="google-mark" aria-hidden="true">G</span>Continue with Google</a>
    </div>
    <div id="auth-error" role="alert" class="auth-error" ${message ? "" : "hidden"}>${esc(message)}</div>
  </div>
 </div>`;
}

async function init() {
  const current = page();
  ensureDesignSystem();
  try {
    state.user = await api("/api/auth/me", {allowAuthRedirect:false});
  } catch {
    if (current === "login") authPage("login");
    else location.replace("/pages/login.html");
    return;
  }
  if (current === "login" || (["admin", "system"].includes(current) && !state.user.is_admin)) {
    location.replace("/");
    return;
  }
  shell();
  renderIdentity();
  void loadStatus();
  const render = {
    dashboard, playground:playgroundPage, cache:cachePage, requests:requestsPage,
    providers:providersPage, metrics:metricsPage, system:systemPage, admin:adminPage, settings:settingsPage,
  }[current] || dashboard;
  await render();
}

window.addEventListener("DOMContentLoaded",init);
