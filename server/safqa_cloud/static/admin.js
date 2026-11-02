"use strict";
// Safqa back-office. Every value coming from users is inserted with
// textContent (never innerHTML) so names or e-mails cannot inject code.

const $ = (s) => document.querySelector(s);
let TOKEN = sessionStorage.getItem("safqa_admin") || "";

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "content-type": "application/json", ...(TOKEN ? { authorization: "Bearer " + TOKEN } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty */ }
  if (res.status === 401 && path !== "/api/auth/login") { logout(); }
  if (!res.ok) { const err = new Error(data.detail || ("Erreur " + res.status)); err.status = res.status; throw err; }
  return data;
}

const fmtDate = (ts) => ts ? new Date(ts * 1000).toLocaleString("fr-MA") : "—";
const money = (v) => (v || 0).toLocaleString("fr-MA") + " DH";

function show(id) {
  for (const s of document.querySelectorAll("main > section")) s.hidden = s.id !== id;
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.tab === id);
}

function logout() {
  if (TOKEN) fetch("/api/auth/logout", { method: "POST", headers: { authorization: "Bearer " + TOKEN } });
  TOKEN = ""; sessionStorage.removeItem("safqa_admin");
  $("#tabs").hidden = true; $("#logout").hidden = true; show("login");
}

// ------------------------------------------------------------ login
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target; $("#loginError").textContent = "";
  try {
    const r = await api("/api/auth/login", { method: "POST", body: {
      email: f.email.value, password: f.password.value, code: f.code.value, device: "Back-office web" } });
    TOKEN = r.token; sessionStorage.setItem("safqa_admin", TOKEN);
    f.password.value = ""; f.code.value = "";
    if (!r.user.is_admin) { $("#loginError").textContent = "Ce compte n'est pas administrateur."; logout(); return; }
    if (!r.user.totp_enabled) return startMfa();
    enter();
  } catch (err) {
    if (err.message === "mfa_required") { $("#codeRow").hidden = false; f.code.focus(); $("#loginError").textContent = "Saisissez le code à 6 chiffres."; }
    else $("#loginError").textContent = err.message;
  }
});

async function startMfa() {
  show("mfa");
  try { const r = await api("/api/auth/2fa/setup", { method: "POST" }); $("#mfaSecret").textContent = r.secret.replace(/(.{4})/g, "$1 ").trim(); }
  catch (err) { $("#mfaError").textContent = err.message; }
}

$("#mfaForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("/api/auth/2fa/enable", { method: "POST", body: { code: e.target.code.value } }); toast("Double authentification activée"); enter(); }
  catch (err) { $("#mfaError").textContent = err.message; }
});

function enter() { $("#tabs").hidden = false; $("#logout").hidden = false; loadDash(); }
$("#logout").addEventListener("click", logout);
for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => {
  const t = b.dataset.tab; show(t);
  ({ dash: loadDash, orgs: loadOrgs, users: loadUsers, audit: loadAudit, licence: () => {} })[t]();
});

// ------------------------------------------------------------ dashboard
async function loadDash() {
  show("dash");
  try {
    const s = await api("/api/admin/stats");
    const k = [["Utilisateurs", s.users], ["Actifs (7 j)", s.active_7d], ["Inscriptions (30 j)", s.signups_30d],
      ["Entreprises", s.orgs], ["Revenu mensuel estimé", money(s.mrr_dh)], ["Enregistrements", s.rows],
      ["Fichiers stockés", s.storage_mb + " Mo"], ["Requêtes IA (mois)", s.ai_month],
      ["Échecs de connexion (24 h)", s.failed_logins_24h], ["Comptes verrouillés", s.locked]];
    $("#kpis").replaceChildren(...k.map(([l, v]) => h("div", { class: "kpi" }, h("span", { class: "muted" }, l), h("b", {}, v))));
    $("#plans").replaceChildren(...Object.entries(s.plans).map(([p, n]) => h("span", { class: "pill" }, p + " : " + n)));
    const flag = (ok, yes, no) => h("span", { class: "pill " + (ok ? "ok" : "warn") }, ok ? yes : no);
    $("#config").replaceChildren(
      flag(s.db === "postgres", "Base PostgreSQL", "Base SQLite (test)"), flag(s.ai, "IA Claude activée", "IA non configurée (ANTHROPIC_API_KEY)"),
      flag(s.smtp, "E-mails activés", "E-mails non configurés (SMTP)"), flag(s.license, "Clés de licence activées", "SAFQA_LICENSE_SECRET absent"));
  } catch (err) {
    if (err.status === 403) { show("login"); $("#loginError").textContent = err.message; }
    else toast(err.message);
  }
}

// ------------------------------------------------------------ companies
async function loadOrgs() {
  const r = await api("/api/admin/orgs?q=" + encodeURIComponent($("#orgQ").value));
  $("#orgRows").replaceChildren(...r.orgs.map((o) => h("tr", {},
    h("td", {}, h("b", {}, o.name), h("div", { class: "muted" }, o.ice ? "ICE " + o.ice : ""), o.disabled ? h("span", { class: "pill err" }, "Suspendue") : null),
    h("td", {}, o.owner || "—"),
    h("td", {}, h("span", { class: "pill " + (o.active ? "ok" : "warn") }, o.label)),
    h("td", {}, o.plan_until || "—"),
    h("td", {}, o.members), h("td", {}, o.records), h("td", {}, o.ai_month),
    h("td", {}, h("div", { class: "actions" },
      h("button", { class: "small", onclick: () => planDialog(o, r.plans) }, "Formule"),
      h("button", { class: "small ghost", onclick: () => act("/api/admin/orgs/" + o.id + "/" + (o.disabled ? "enable" : "disable"),
        o.disabled ? "Réactiver cette entreprise ?" : "Suspendre l'accès de toute l'entreprise ?", loadOrgs) }, o.disabled ? "Réactiver" : "Suspendre"))))));
}
$("#orgGo").addEventListener("click", loadOrgs);
$("#orgQ").addEventListener("keydown", (e) => { if (e.key === "Enter") loadOrgs(); });

function planDialog(o, plans) {
  const sel = h("select", {}, plans.map((p) => h("option", { value: p, selected: p === (o.plan || "FREE") }, p)));
  const until = h("input", { type: "date", value: o.plan_until || "" });
  modal("Formule de " + o.name, [h("label", {}, "Formule", sel), h("label", {}, "Valable jusqu'au", until)], async () => {
    await api("/api/admin/orgs/" + o.id + "/plan", { method: "POST", body: { plan: sel.value, until: until.value || null } });
    toast("Formule mise à jour"); loadOrgs();
  });
}

// ------------------------------------------------------------ users
async function loadUsers() {
  const r = await api("/api/admin/users?q=" + encodeURIComponent($("#userQ").value));
  const now = Date.now() / 1000;
  $("#userRows").replaceChildren(...r.users.map((u) => h("tr", {},
    h("td", {}, h("b", {}, u.email), h("div", { class: "muted" }, u.name || ""), u.is_admin ? h("span", { class: "pill" }, "Admin") : null),
    h("td", {}, u.orgs.map((o) => h("span", { class: "pill" }, o.name + " · " + o.role))),
    h("td", {}, fmtDate(u.created_at)), h("td", {}, fmtDate(u.last_login)),
    h("td", {}, u.disabled ? h("span", { class: "pill err" }, "Désactivé") : null,
      u.locked_until > now ? h("span", { class: "pill warn" }, "Verrouillé") : null,
      h("span", { class: "pill " + (u.totp_enabled ? "ok" : "") }, u.totp_enabled ? "2FA" : "Sans 2FA")),
    h("td", {}, h("div", { class: "actions" },
      h("button", { class: "small ghost", onclick: () => resetPw(u) }, "Mot de passe"),
      u.locked_until > now ? h("button", { class: "small ghost", onclick: () => act("/api/admin/users/" + u.id + "/unlock", null, loadUsers) }, "Déverrouiller") : null,
      h("button", { class: "small ghost", onclick: () => act("/api/admin/users/" + u.id + "/revoke", "Déconnecter cet utilisateur de tous ses appareils ?", loadUsers) }, "Déconnecter"),
      u.totp_enabled && !u.is_admin ? h("button", { class: "small ghost", onclick: () => act("/api/admin/users/" + u.id + "/reset-2fa", "Retirer la double authentification (téléphone perdu) ?", loadUsers) }, "Retirer 2FA") : null,
      h("button", { class: "small " + (u.disabled ? "" : "danger"), onclick: () => act("/api/admin/users/" + u.id + "/" + (u.disabled ? "enable" : "disable"),
        u.disabled ? "Réactiver ce compte ?" : "Désactiver ce compte ? Il sera déconnecté immédiatement.", loadUsers) }, u.disabled ? "Réactiver" : "Désactiver"))))));
}
$("#userGo").addEventListener("click", loadUsers);
$("#userQ").addEventListener("keydown", (e) => { if (e.key === "Enter") loadUsers(); });

function resetPw(u) {
  modal("Réinitialiser le mot de passe", [h("p", {}, "Un mot de passe temporaire sera créé pour " + u.email +
    ". Communiquez-le par un canal sûr (appel, WhatsApp) : l'utilisateur devra le changer.")], async () => {
    const r = await api("/api/admin/users/" + u.id + "/reset-password", { method: "POST" });
    modal("Mot de passe temporaire", [h("p", { class: "secret" }, r.temporary_password)], null);
  });
}

// ------------------------------------------------------------ licence keys
$("#licForm").addEventListener("submit", async (e) => {
  e.preventDefault(); const f = e.target;
  try { const r = await api("/api/admin/license", { method: "POST", body: { plan: f.plan.value, until: f.until.value, customer: f.customer.value } });
    $("#licKey").textContent = r.key; }
  catch (err) { toast(err.message); }
});

// ------------------------------------------------------------ audit
const ACTIONS = { login: "Connexion", login_failed: "Échec de connexion", signup: "Inscription", mfa_failed: "Code 2FA erroné",
  password_changed: "Mot de passe changé", password_reset: "Mot de passe réinitialisé", invite_created: "Invitation créée",
  invite_accepted: "Invitation acceptée", member_removed: "Membre retiré", role_changed: "Rôle modifié", org_created: "Entreprise créée",
  org_deleted: "Entreprise supprimée", org_exported: "Export des données", license_activated: "Licence activée", mfa_enabled: "2FA activée" };
async function loadAudit() {
  const r = await api("/api/admin/audit?q=" + encodeURIComponent($("#auditQ").value));
  $("#auditRows").replaceChildren(...r.events.map((a) => h("tr", {},
    h("td", {}, fmtDate(a.ts)), h("td", {}, h("span", { class: "pill " + (/failed|deleted|disable/.test(a.action) ? "warn" : "") }, ACTIONS[a.action] || a.action)),
    h("td", {}, a.email || "—"), h("td", {}, a.org_id || "—"), h("td", {}, a.ip || "—"), h("td", { class: "muted" }, a.detail || ""))));
}
$("#auditGo").addEventListener("click", loadAudit);
$("#auditQ").addEventListener("keydown", (e) => { if (e.key === "Enter") loadAudit(); });

// ------------------------------------------------------------ helpers
async function act(path, question, then) {
  const go = async () => { try { await api(path, { method: "POST" }); toast("Fait"); then && then(); } catch (err) { toast(err.message); } };
  if (!question) return go();
  modal("Confirmer", [h("p", {}, question)], go);
}

function modal(title, body, onOk) {
  const d = $("#modal"); $("#modalTitle").textContent = title; $("#modalBody").replaceChildren(...body);
  $("#modalOk").hidden = !onOk;
  d.onclose = async () => { if (d.returnValue === "ok" && onOk) { try { await onOk(); } catch (err) { toast(err.message); } } };
  d.returnValue = ""; d.showModal();
}

if (TOKEN) enter(); else show("login");
