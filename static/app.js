"use strict";

const $ = (id) => document.getElementById(id);
const state = { tickets: [], selectedId: null, busy: false, config: null };

function announce(message, isError = false) {
  const notice = $("notice");
  notice.hidden = !message;
  notice.textContent = message;
  notice.classList.toggle("is-error", isError);
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Cannot reach the server. Check that the app is running and try again.");
  }
  let data;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const detail = data && (data.detail || data.message || data.error);
    const error = new Error(typeof detail === "string" ? detail : `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function jsonRequest(method, data) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) };
}

function make(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined && value !== null) element.textContent = String(value);
  return element;
}

function badge(value, kind) {
  const element = make("span", `badge badge-${kind}`, value || "Unknown");
  return element;
}

function historyDescription(event) {
  const details = event.details && typeof event.details === "object" ? event.details : {};
  const labels = {
    submitted: `Submitted in ${details.mode === "live" ? "live AI" : "demo"} mode`,
    triaged: "Suggestion generated",
    triage_failed: "Suggestion failed",
    retry_started: `Retry started in ${details.mode === "live" ? "live AI" : "demo"} mode`,
    interrupted: "Processing was interrupted",
    approved: "Review approved",
    review_saved: "Review saved"
  };
  const changes = details.changes && typeof details.changes === "object" ? details.changes : {};
  const fields = { category: "Category", urgency: "Urgency", summary: "Summary", review_status: "Status" };
  const descriptions = [];
  for (const [field, label] of Object.entries(fields)) {
    const change = changes[field];
    if (!change || typeof change !== "object") continue;
    if (field === "summary") descriptions.push("Summary updated");
    else descriptions.push(`${label}: ${change.from ?? "empty"} → ${change.to ?? "empty"}`);
  }
  return { title: labels[event.action] || "Ticket updated", detail: descriptions.length ? `Changes: ${descriptions.join(", ")}` : "" };
}

function formatDate(value) {
  if (!value) return "Time unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function setBusy(busy) {
  state.busy = busy;
  $("create-button").disabled = busy;
  updateActionAvailability();
  $("seed-button").disabled = busy;
  $("export-button").disabled = busy;
  $("import-button").disabled = busy;
  $("import-file").disabled = busy;
  $("login-button").disabled = busy;
  $("logout-button").disabled = busy;
  $("create-button").firstChild.textContent = busy ? "Working… " : "Create suggestion ";
}

function updateActionAvailability() {
  const ticket = state.tickets.find((item) => String(item.id) === String(state.selectedId));
  $("save-button").disabled = state.busy || !ticket || ticket.triage_status !== "ready";
  $("retry-button").disabled = state.busy || !ticket || ticket.triage_status !== "error";
}

function showLogin() {
  state.tickets = [];
  state.selectedId = null;
  renderStats(null);
  renderTickets();
  renderDetail();
  $("message").value = "";
  $("import-file").value = "";
  $("edit-summary").value = "";
  for (const id of ["detail-id", "detail-message", "detail-meta", "detail-error", "history-list"]) $(id).replaceChildren();
  $("workspace-content").hidden = true;
  $("logout-button").hidden = true;
  $("login-panel").hidden = false;
  $("workspace-token").focus();
}

function showWorkspace() {
  $("login-panel").hidden = true;
  $("workspace-content").hidden = false;
  $("logout-button").hidden = !(state.config && state.config.auth_required);
}

function updateModeHelp() {
  const live = $("mode").value === "live";
  $("mode-help").textContent = live
    ? `Live AI sends the ticket to the configured model${state.config && state.config.model ? ` (${state.config.model})` : ""}. Requests may incur charges.`
    : "Demo uses deterministic rules. It does not call an AI model.";
}

function renderStats(stats) {
  for (const key of ["total", "pending", "approved", "high"]) {
    $(`stat-${key}`).textContent = stats && Number.isFinite(stats[key]) ? stats[key] : "—";
  }
}

function renderTickets() {
  const list = $("ticket-list");
  list.replaceChildren();
  const visible = state.tickets.filter((ticket) =>
    (!$('filter-category').value || ticket.category === $('filter-category').value) &&
    (!$('filter-urgency').value || ticket.urgency === $('filter-urgency').value) &&
    (!$('filter-review').value || ticket.review_status === $('filter-review').value)
  );
  $("filtered-count").textContent = `${visible.length} shown`;
  if (!visible.length) {
    list.append(make("p", "empty", state.tickets.length ? "No tickets match these filters." : "No tickets yet. Create one to get started."));
    return;
  }
  for (const ticket of visible) {
    const button = make("button", "ticket-row");
    button.type = "button";
    const selected = String(ticket.id) === String(state.selectedId);
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
    const rowTop = make("span", "row-top");
    const id = make("span", "ticket-id", `#${String(ticket.id).slice(0, 8)}`);
    id.title = String(ticket.id);
    rowTop.append(id, make("span", "row-date", formatDate(ticket.created_at)));
    const title = make("span", "ticket-title", ticket.message || "Untitled ticket");
    const badges = make("span", "badge-row");
    badges.append(badge(ticket.category, "category"), badge(ticket.urgency, ticket.urgency === "high" ? "high" : "neutral"), badge(ticket.review_status, ticket.review_status === "approved" ? "approved" : "pending"));
    if (ticket.error) badges.append(badge("Error", "high"));
    button.append(rowTop, title, badges);
    button.addEventListener("click", () => { state.selectedId = ticket.id; renderTickets(); renderDetail(); });
    list.append(button);
  }
}

function renderDetail() {
  const ticket = state.tickets.find((item) => String(item.id) === String(state.selectedId));
  updateActionAvailability();
  $("detail-empty").hidden = Boolean(ticket);
  $("detail").hidden = !ticket;
  if (!ticket) return;
  $("detail-id").textContent = `TICKET #${String(ticket.id).slice(0, 8)}`;
  $("detail-id").title = String(ticket.id);
  $("detail-message").textContent = ticket.message || "Untitled ticket";
  const badges = $("detail-badges");
  badges.replaceChildren(badge(ticket.review_status, ticket.review_status === "approved" ? "approved" : "pending"), badge(ticket.mode === "live" ? "Live AI" : "Demo · simulated", "mode"));
  const parts = [`Created ${formatDate(ticket.created_at)}`];
  if (ticket.updated_at) parts.push(`Updated ${formatDate(ticket.updated_at)}`);
  if (ticket.latency_ms != null && Number.isFinite(Number(ticket.latency_ms))) parts.push(`${Number(ticket.latency_ms).toFixed(2)} ms`);
  if (ticket.input_tokens != null) parts.push(`${ticket.input_tokens} input tokens`);
  if (ticket.output_tokens != null) parts.push(`${ticket.output_tokens} output tokens`);
  $("detail-meta").textContent = parts.join("  ·  ");
  $("detail-error").hidden = !ticket.error;
  $("detail-error").textContent = ticket.error ? `Suggestion error: ${ticket.error}` : "";
  $("review-help").hidden = ticket.triage_status === "ready";
  $("review-help").textContent = ticket.triage_status === "error" ? "Retry the suggestion before saving a review." : "A suggestion must be ready before you can save a review.";
  $("edit-category").value = ticket.category || "other";
  $("edit-urgency").value = ticket.urgency || "normal";
  $("edit-status").value = ticket.review_status || "pending";
  $("edit-summary").value = ticket.summary || "";
  const history = $("history-list");
  history.replaceChildren();
  if (!Array.isArray(ticket.history) || !ticket.history.length) {
    history.append(make("p", "muted", "No activity recorded yet."));
  } else {
    for (const event of ticket.history) {
      const entry = make("div", "history-entry");
      const description = historyDescription(event);
      entry.append(make("span", "history-dot"), make("div", "history-copy"));
      entry.lastChild.append(make("strong", "", description.title), make("p", "", description.detail), make("small", "", formatDate(event.created_at)));
      history.append(entry);
    }
  }
}

async function refresh() {
  const [tickets, stats] = await Promise.all([request("/api/tickets"), request("/api/stats")]);
  if (!Array.isArray(tickets)) throw new Error("The server returned an unexpected ticket list.");
  state.tickets = tickets;
  renderStats(stats);
  renderTickets();
  renderDetail();
}

async function runAction(action) {
  if (state.busy) return;
  setBusy(true);
  announce("");
  try { await action(); } catch (error) {
    if (error.status === 401 && state.config && state.config.auth_required) showLogin();
    announce(error.message || "Something went wrong. Please try again.", true);
  }
  finally { setBusy(false); }
}

$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const token = $("workspace-token").value.trim();
  if (!token) { announce("Enter your workspace access token.", true); return; }
  runAction(async () => {
    try {
      await request("/api/session", jsonRequest("POST", { token }));
      await refresh();
      showWorkspace();
      announce("Signed in to the workspace.");
    } finally {
      $("workspace-token").value = "";
    }
  });
});

$("logout-button").addEventListener("click", () => runAction(async () => {
  await request("/api/session/logout", { method: "POST" });
  showLogin();
  announce("Signed out of the workspace.");
}));

$("seed-button").addEventListener("click", () => runAction(async () => {
  const hadTickets = state.tickets.length > 0;
  await request("/api/demo/seed", { method: "POST" });
  await refresh();
  announce(hadTickets ? "No sample tickets were added. The inbox already has tickets." : "Sample tickets are ready in the inbox.");
}));

$("import-button").addEventListener("click", () => {
  const file = $("import-file").files[0];
  if (!file) { announce("Choose a CSV file to import.", true); $("import-file").focus(); return; }
  if (file.size > 50000) { announce("The CSV file must be 50 KB or smaller.", true); return; }
  runAction(async () => {
    const csv = await file.text();
    const payload = { csv, mode: $("mode").value };
    if (new TextEncoder().encode(JSON.stringify(payload)).length > 64000) {
      throw new Error("This CSV is too large after encoding. Use a smaller file and try again.");
    }
    const result = await request("/api/tickets/import", jsonRequest("POST", payload));
    $("import-file").value = "";
    await refresh();
    const summary = `Imported ${result.imported} ticket${result.imported === 1 ? "" : "s"}; ${result.remaining} remaining.`;
    announce(result.stopped_on_error ? `${summary} Import stopped after a provider error; check the inbox.` : summary, Boolean(result.stopped_on_error));
  });
});

$("export-button").addEventListener("click", () => runAction(async () => {
  let response;
  try { response = await fetch("/api/export.csv"); }
  catch { throw new Error("Cannot reach the server. Check that the app is running and try again."); }
  if (!response.ok) {
    const error = new Error(`Export failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "tickets.csv";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  announce("Ticket export downloaded.");
}));

$("create-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const message = $("message").value.trim();
  if (!message) { announce("Enter a ticket message first.", true); $("message").focus(); return; }
  runAction(async () => {
    const ticket = await request("/api/tickets", jsonRequest("POST", { message, mode: $("mode").value }));
    state.selectedId = ticket.id;
    $("message").value = "";
    await refresh();
    announce(ticket.error ? "Ticket created, but the suggestion failed. See details below." : "Ticket created. Review the suggestion below.", Boolean(ticket.error));
  });
});

$("review-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const summary = $("edit-summary").value.trim();
  if (!summary) { announce("Enter a summary before saving.", true); $("edit-summary").focus(); return; }
  runAction(async () => {
    const ticket = await request(`/api/tickets/${encodeURIComponent(state.selectedId)}`, jsonRequest("PATCH", {
      category: $("edit-category").value, urgency: $("edit-urgency").value,
      summary, review_status: $("edit-status").value
    }));
    await refresh();
    announce(ticket.review_status === "approved" ? "Review saved and approved." : "Review saved as pending.");
  });
});

$("retry-button").addEventListener("click", () => runAction(async () => {
  const ticket = await request(`/api/tickets/${encodeURIComponent(state.selectedId)}/retry`, jsonRequest("POST", { mode: $("mode").value }));
  await refresh();
  announce(ticket.error ? "Retry failed. See the ticket details." : "A new suggestion is ready for review.", Boolean(ticket.error));
}));

for (const id of ["filter-category", "filter-urgency", "filter-review"]) $(id).addEventListener("change", renderTickets);
$("mode").addEventListener("change", updateModeHelp);

async function initialize() {
  try {
    state.config = await request("/api/config");
    const option = $("mode").querySelector('option[value="live"]');
    option.disabled = !state.config.live_available;
    option.textContent = state.config.live_available ? "Live AI — configured server key" : "Live AI — unavailable";
    updateModeHelp();
    if (state.config.auth_required && !state.config.authenticated) {
      showLogin();
      return;
    }
    await refresh();
    showWorkspace();
  } catch (error) {
    if (error.status === 401 && state.config && state.config.auth_required) {
      showLogin();
    } else {
      announce(error.message || "Could not load the workspace. Refresh the page to try again.", true);
    }
  }
}

initialize();
