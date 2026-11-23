/* Heizplaner-Karte \u2013 Wochenplan-Editor f\u00fcr die Heizplaner-Integration */
const HP_VERSION = "0.3.2";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const toMin = (t) => {
  const [h, m] = String(t).split(":").map(Number);
  return h * 60 + m;
};
const fmt = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const WD_SHORT = { mon: "Mo", tue: "Di", wed: "Mi", thu: "Do", fri: "Fr", sat: "Sa", sun: "So" };

function dayRange(days, all) {
  // ["mon","tue","wed"] -> "Mo\u2013Mi", ["mon","wed"] -> "Mo, Mi"
  const idx = days.map((d) => all.indexOf(d)).sort((a, b) => a - b);
  if (!idx.length) return "";
  const groups = [];
  let start = idx[0], prev = idx[0];
  for (const i of idx.slice(1).concat([99])) {
    if (i === prev + 1) { prev = i; continue; }
    groups.push(start === prev ? WD_SHORT[all[start]] : `${WD_SHORT[all[start]]}\u2013${WD_SHORT[all[prev]]}`);
    start = prev = i;
  }
  return groups.join(", ");
}

class HeizplanerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._cfg = null; // Daten der Integration
    this._daytype = null; // gew\u00e4hlter Tagtyp-Tab
    this._edit = null; // { room, daytype, points, copy:Set, error }
    this._sig = "";
    this._loading = false;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("change", (e) => this._onChange(e));
  }

  setConfig(config) {
    this._config = { title: "Heizplaner", ...config };
  }

  static getStubConfig() {
    return { title: "Heizplaner" };
  }

  getCardSize() {
    return 4 + (this._cfg?.rooms.length || 3) * 2;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._cfg && !this._loading) {
      this._load();
      return;
    }
    if (!this._cfg) return;
    const mode = hass.states[this._cfg.mode_entity];
    const pv = mode?.attributes?.plan_version;
    if (pv !== undefined && pv !== this._cfg.plan_version && !this._edit) {
      this._load();
      return;
    }
    const sig = this._signature();
    if (sig !== this._sig && !this._edit) {
      this._sig = sig;
      this._render();
    }
  }

  async _load() {
    this._loading = true;
    try {
      this._cfg = await this._hass.callWS({ type: "heizplaner/config" });
      this._error = null;
      if (!this._daytype) this._daytype = this._cfg.today || this._cfg.daytypes[0].id;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._loading = false;
    this._sig = this._signature();
    this._render();
  }

  _signature() {
    if (!this._cfg || !this._hass) return "";
    const ids = [this._cfg.mode_entity];
    for (const r of this._cfg.rooms) ids.push(r.climate, r.sensor, r.plan_entity);
    for (const s of this._cfg.stufen) ids.push(s.entity);
    for (const s of this._cfg.switches) ids.push(s.entity);
    const minute = Math.floor(Date.now() / 60000);
    return (
      minute +
      ids
        .filter(Boolean)
        .map((id) => {
          const st = this._hass.states[id];
          return st ? st.state + JSON.stringify(st.attributes) : "-";
        })
        .join("|")
    );
  }

  _st(id) {
    return id ? this._hass.states[id] : undefined;
  }

  _stufe(id) {
    return this._cfg.stufen.find((s) => s.id === id) || { id, label: id, color: "#888", icon: "mdi:help" };
  }

  _points(roomId, daytype) {
    if (this._edit && this._edit.room === roomId && this._edit.daytype === daytype) return this._edit.points;
    return this._cfg.schedule?.[roomId]?.[daytype] || [];
  }

  // ------------------------------------------------------------------ Rendern
  _render() {
    const root = this.shadowRoot;
    if (this._error) {
      root.innerHTML = `${STYLE}<ha-card><div class="err">Heizplaner: ${esc(this._error)}</div></ha-card>`;
      return;
    }
    if (!this._cfg) {
      root.innerHTML = `${STYLE}<ha-card><div class="empty">Lade Heizplaner \u2026</div></ha-card>`;
      return;
    }
    const c = this._cfg;
    const mode = this._st(c.mode_entity);
    const rooms = this._config.rooms ? c.rooms.filter((r) => this._config.rooms.includes(r.id)) : c.rooms;
    root.innerHTML = `${STYLE}
      <ha-card>
        <div class="head">
          <div class="title">${esc(this._config.title)}</div>
          <div class="mode" title="Heute">
            <ha-icon icon="${esc(mode?.attributes?.icon || "mdi:calendar")}"></ha-icon>
            <span>${esc(mode?.state || "\u2013")}</span>
          </div>
          <button class="icon-btn" data-action="apply" title="Plan jetzt anwenden (\u00fcberschreibt manuelle \u00c4nderungen)">
            <ha-icon icon="mdi:calendar-sync"></ha-icon>
          </button>
        </div>
        <div class="switches">${c.switches.map((s) => this._switchChip(s)).join("")}</div>
        <div class="tabs">${c.daytypes.map((d) => this._tab(d)).join("")}</div>
        <div class="rooms">
          ${rooms.length ? rooms.map((r) => this._room(r)).join("") : `<div class="empty">Noch keine R\u00e4ume \u2013 unter Einstellungen \u2192 Ger\u00e4te &amp; Dienste \u2192 Heizplaner \u2192 Konfigurieren anlegen.</div>`}
        </div>
        <div class="axis-legend">${c.stufen
          .filter((s) => s.plan)
          .map((s) => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`)
          .join("")}</div>
        <div class="stufen">${c.stufen.map((s) => this._stufeCtl(s)).join("")}</div>
      </ha-card>`;
  }

  _switchChip(s) {
    const st = this._st(s.entity);
    const on = st?.state === "on";
    return `<button class="chip ${on ? "on" : ""}" data-action="toggle" data-entity="${esc(s.entity)}">
      <ha-icon icon="${esc(s.icon)}"></ha-icon><span>${esc(s.label.replace(" heute", ""))}</span></button>`;
  }

  _tab(d) {
    const w = this._cfg.weekdays;
    const days =
      d.id === "buero" ? dayRange(w.buero, w.all) : d.id === "homeoffice" ? dayRange(w.homeoffice, w.all) : "Sa\u2013So \u00b7 Feiertage";
    const sel = d.id === this._daytype;
    const today = d.id === this._cfg.today;
    return `<button class="tab ${sel ? "sel" : ""}" data-action="tab" data-daytype="${d.id}">
      <span class="tab-label">${esc(d.label)}${today ? '<i class="dot" title="gilt heute"></i>' : ""}</span>
      <span class="tab-days">${esc(days)}</span></button>`;
  }

  _room(r) {
    const climate = this._st(r.climate);
    const sensor = this._st(r.sensor);
    const plan = this._st(r.plan_entity)?.attributes || {};
    const ist = sensor && !isNaN(parseFloat(sensor.state)) ? parseFloat(sensor.state) : climate?.attributes?.current_temperature;
    const soll = climate?.attributes?.temperature;
    const heating = climate?.attributes?.hvac_action === "heating";
    const stufe = plan.stufe ? this._stufe(plan.stufe) : null;
    const editing = this._edit?.room === r.id;
    const unavailable = !climate || ["unavailable", "unknown"].includes(climate.state);
    const off = climate?.state === "off";
    const badges = [];
    if (unavailable) badges.push(`<span class="badge warn">nicht erreichbar</span>`);
    else if (off) badges.push(`<span class="badge">aus</span>`);
    if (plan.boost) badges.push(`<span class="badge boost"><ha-icon icon="mdi:rocket-launch"></ha-icon>Boost</span>`);
    if (plan.manuell)
      badges.push(
        `<span class="badge manual" title="Von Hand ge\u00e4ndert \u2013 gilt bis zum n\u00e4chsten Wechsel">Manuell${plan.naechster_wechsel ? " bis " + esc(plan.naechster_wechsel) : ""}</span>`
      );
    return `<div class="room ${editing ? "editing" : ""}">
      <div class="room-row">
        <div class="room-icon ${heating ? "heating" : ""}" data-action="more" data-entity="${esc(r.climate)}">
          <ha-icon icon="${esc(r.icon)}"></ha-icon>
        </div>
        <div class="room-main" data-action="more" data-entity="${esc(r.climate)}">
          <div class="room-name">${esc(r.name)} ${badges.join("")}</div>
          <div class="room-sub">
            ${ist !== undefined && ist !== null ? `<b>${Number(ist).toFixed(1).replace(".", ",")}&nbsp;\u00b0C</b>` : "\u2013"}
            ${soll !== undefined && soll !== null ? `<span class="arrow">\u2192</span><span>${Number(soll).toFixed(1).replace(".", ",")}&nbsp;\u00b0C</span>` : ""}
            ${heating ? `<ha-icon class="flame" icon="mdi:fire"></ha-icon>` : ""}
          </div>
        </div>
        ${
          stufe
            ? `<div class="room-stufe" style="--c:${stufe.color}">
                <span class="pill"><ha-icon icon="${esc(stufe.icon)}"></ha-icon>${esc(stufe.label)}</span>
                ${plan.naechster_wechsel ? `<span class="next">ab ${esc(plan.naechster_wechsel)} ${esc(plan.naechste_stufe_label || "")}</span>` : ""}
              </div>`
            : ""
        }
        <button class="icon-btn" data-action="edit" data-room="${esc(r.id)}" title="Plan bearbeiten">
          <ha-icon icon="${editing ? "mdi:close" : "mdi:pencil"}"></ha-icon>
        </button>
      </div>
      ${this._timeline(r.id, this._daytype, editing)}
      ${editing ? this._editor(r) : ""}
    </div>`;
  }

  _segments(points) {
    const pts = points.map(([t, s]) => [toMin(t), s]).sort((a, b) => a[0] - b[0]);
    if (!pts.length) return [];
    const segs = [];
    // vor dem ersten Wechsel l\u00e4uft die letzte Stufe des Vortags weiter (Anzeige: Ende dieses Plans)
    if (pts[0][0] > 0) segs.push({ from: 0, to: pts[0][0], stufe: pts[pts.length - 1][1], carry: true });
    pts.forEach(([m, s], i) => segs.push({ from: m, to: i + 1 < pts.length ? pts[i + 1][0] : 1440, stufe: s }));
    return segs;
  }

  _timeline(roomId, daytype, editing) {
    const segs = this._segments(this._points(roomId, daytype));
    const now = new Date();
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const showNow = daytype === this._cfg.today;
    return `<div class="timeline ${editing ? "edit" : ""}" data-action="${editing ? "bar-add" : "edit"}" data-room="${esc(roomId)}"
        title="${editing ? "Klicken, um hier einen Wechsel einzuf\u00fcgen" : "Klicken zum Bearbeiten"}">
      <div class="bar">
        ${segs
          .map((sg) => {
            const st = this._stufe(sg.stufe);
            const w = ((sg.to - sg.from) / 1440) * 100;
            const label = !sg.carry && w >= 9 ? `<span>${fmt(sg.from)}</span>` : "";
            return `<div class="seg ${sg.carry ? "carry" : ""}" style="left:${(sg.from / 1440) * 100}%;width:${w}%;background:${st.color}"
                title="${fmt(sg.from)}\u2013${fmt(sg.to)} ${esc(st.label)}">${label}</div>`;
          })
          .join("")}
        ${showNow ? `<div class="now" style="left:${(nowMin / 1440) * 100}%"></div>` : ""}
      </div>
      <div class="ticks">${[0, 6, 12, 18, 24].map((h) => `<span style="left:${(h / 24) * 100}%">${h}</span>`).join("")}</div>
    </div>`;
  }

  _editor(r) {
    const e = this._edit;
    const dtLabel = this._cfg.daytypes.find((d) => d.id === e.daytype)?.label;
    const planStufen = this._cfg.stufen.filter((s) => s.plan);
    const rows = e.points
      .map(
        ([t, s], i) => `<div class="pt">
        <input type="time" step="900" value="${esc(t)}" data-action="pt-time" data-i="${i}">
        <span class="sw" style="background:${this._stufe(s).color}"></span>
        <select data-action="pt-stufe" data-i="${i}">
          ${planStufen.map((ps) => `<option value="${ps.id}" ${ps.id === s ? "selected" : ""}>${esc(ps.label)}</option>`).join("")}
        </select>
        <button class="icon-btn small" data-action="pt-del" data-i="${i}" title="Wechsel l\u00f6schen" ${e.points.length <= 1 ? "disabled" : ""}>
          <ha-icon icon="mdi:delete-outline"></ha-icon></button>
      </div>`
      )
      .join("");
    const otherTypes = this._cfg.daytypes.filter((d) => d.id !== e.daytype);
    const otherRooms = this._cfg.rooms.filter((x) => x.id !== r.id);
    const cb = (key, label) =>
      `<label class="cb"><input type="checkbox" data-action="copy" data-key="${esc(key)}" ${e.copy.has(key) ? "checked" : ""}>${esc(label)}</label>`;
    return `<div class="editor">
      <div class="ed-title">${esc(r.name)} \u00b7 ${esc(dtLabel)}</div>
      <div class="pts">${rows}</div>
      <button class="text-btn" data-action="pt-add"><ha-icon icon="mdi:plus"></ha-icon>Wechsel hinzuf\u00fcgen</button>
      <div class="copy">
        <div class="copy-h">Auch \u00fcbernehmen f\u00fcr</div>
        <div class="copy-list">
          ${otherTypes.map((d) => cb(`tt:${d.id}`, `${r.name} \u00b7 ${d.label}`)).join("")}
          ${otherRooms.map((x) => cb(`room:${x.id}`, `${x.name} \u00b7 ${dtLabel}`)).join("")}
        </div>
      </div>
      ${e.error ? `<div class="err">${esc(e.error)}</div>` : ""}
      <div class="ed-actions">
        <button class="text-btn" data-action="cancel">Abbrechen</button>
        <button class="primary" data-action="save" ${e.saving ? "disabled" : ""}>${e.saving ? "Speichere \u2026" : "Speichern"}</button>
      </div>
    </div>`;
  }

  _stufeCtl(s) {
    const st = this._st(s.entity);
    const v = st ? parseFloat(st.state) : NaN;
    return `<div class="stufe" style="--c:${s.color}">
      <ha-icon icon="${esc(s.icon)}"></ha-icon>
      <span class="stufe-label">${esc(s.label)}</span>
      <button class="icon-btn small" data-action="stufe" data-entity="${esc(s.entity)}" data-delta="-0.5" title="0,5 \u00b0C k\u00e4lter"><ha-icon icon="mdi:minus"></ha-icon></button>
      <span class="stufe-val">${isNaN(v) ? "\u2013" : v.toFixed(1).replace(".", ",")} \u00b0C</span>
      <button class="icon-btn small" data-action="stufe" data-entity="${esc(s.entity)}" data-delta="0.5" title="0,5 \u00b0C w\u00e4rmer"><ha-icon icon="mdi:plus"></ha-icon></button>
    </div>`;
  }

  // ------------------------------------------------------------------ Aktionen
  _onClick(ev) {
    const el = ev.target.closest("[data-action]");
    if (!el) return;
    const a = el.dataset.action;
    if (a === "toggle") this._hass.callService("switch", "toggle", { entity_id: el.dataset.entity });
    else if (a === "apply") this._hass.callService("button", "press", { entity_id: this._applyEntity() });
    else if (a === "tab") {
      if (this._edit) this._edit = null;
      this._daytype = el.dataset.daytype;
      this._render();
    } else if (a === "more") {
      const e = new Event("hass-more-info", { bubbles: true, composed: true });
      e.detail = { entityId: el.dataset.entity };
      this.dispatchEvent(e);
    } else if (a === "edit") {
      const room = el.dataset.room;
      if (this._edit?.room === room) this._edit = null;
      else
        this._edit = {
          room,
          daytype: this._daytype,
          points: JSON.parse(JSON.stringify(this._points(room, this._daytype))),
          copy: new Set(),
        };
      this._render();
    } else if (a === "bar-add") {
      const bar = el.querySelector(".bar").getBoundingClientRect();
      const m = Math.round((((ev.clientX - bar.left) / bar.width) * 1440) / 15) * 15;
      this._addPoint(Math.max(0, Math.min(1425, m)));
    } else if (a === "pt-add") {
      const last = this._edit.points.length ? toMin(this._edit.points[this._edit.points.length - 1][0]) : 360;
      this._addPoint(Math.min(1425, last + 60));
    } else if (a === "pt-del") {
      this._edit.points.splice(Number(el.dataset.i), 1);
      this._render();
    } else if (a === "cancel") {
      this._edit = null;
      this._render();
    } else if (a === "save") this._save();
    else if (a === "stufe") {
      const st = this._st(el.dataset.entity);
      if (!st) return;
      const min = st.attributes.min ?? 5, max = st.attributes.max ?? 30;
      const v = Math.min(max, Math.max(min, parseFloat(st.state) + parseFloat(el.dataset.delta)));
      this._hass.callService("number", "set_value", { entity_id: el.dataset.entity, value: v });
    }
  }

  _onChange(ev) {
    const el = ev.target;
    const a = el.dataset?.action;
    if (!a || !this._edit) return;
    const i = Number(el.dataset.i);
    if (a === "pt-time" && el.value) this._edit.points[i][0] = el.value.slice(0, 5);
    else if (a === "pt-stufe") this._edit.points[i][1] = el.value;
    else if (a === "copy") el.checked ? this._edit.copy.add(el.dataset.key) : this._edit.copy.delete(el.dataset.key);
    if (a !== "copy") {
      this._edit.points.sort((x, y) => toMin(x[0]) - toMin(y[0]));
      this._edit.error = null;
      this._render();
    }
  }

  _addPoint(m) {
    const pts = this._edit.points;
    const t = fmt(m);
    if (pts.some((p) => p[0] === t)) return;
    // Stufe des Abschnitts an dieser Stelle \u2013 neuer Punkt bekommt eine andere
    const seg = this._segments(pts).find((s) => m >= s.from && m < s.to);
    const cur = seg?.stufe;
    const stufe = cur === "komfort" ? "eco" : "komfort";
    pts.push([t, stufe]);
    pts.sort((x, y) => toMin(x[0]) - toMin(y[0]));
    this._edit.error = null;
    this._render();
  }

  _applyEntity() {
    return this._cfg.apply_entity;
  }

  async _save() {
    const e = this._edit;
    const times = e.points.map((p) => p[0]);
    if (new Set(times).size !== times.length) {
      e.error = "Jede Uhrzeit darf nur einmal vorkommen.";
      this._render();
      return;
    }
    const targets = [[e.room, e.daytype]];
    for (const k of e.copy) {
      const [kind, id] = k.split(":");
      targets.push(kind === "tt" ? [e.room, id] : [id, e.daytype]);
    }
    e.saving = true;
    this._render();
    try {
      for (const [room_id, daytype] of targets) {
        await this._hass.callWS({ type: "heizplaner/save_plan", room_id, daytype, points: e.points });
      }
      this._edit = null;
      await this._load();
    } catch (err) {
      e.saving = false;
      e.error = err?.message || String(err);
      this._render();
    }
  }
}

const STYLE = `<style>
  ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
  button { font: inherit; color: inherit; cursor: pointer; }
  .head { display: flex; align-items: center; gap: 10px; }
  .title { font-size: 1.25em; font-weight: 500; flex: 1; }
  .mode { display: flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 16px;
    background: var(--secondary-background-color); font-size: .9em; --mdc-icon-size: 18px; }
  .icon-btn { border: none; background: none; padding: 6px; border-radius: 50%; display: inline-flex;
    color: var(--secondary-text-color); --mdc-icon-size: 22px; }
  .icon-btn:hover { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .icon-btn.small { padding: 3px; --mdc-icon-size: 18px; }
  .icon-btn:disabled { opacity: .3; cursor: default; }
  .switches { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 18px;
    border: 1px solid var(--divider-color); background: none; font-size: .9em; --mdc-icon-size: 18px; }
  .chip.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; padding: 4px; border-radius: 12px;
    background: var(--secondary-background-color); }
  .tab { border: none; background: none; border-radius: 9px; padding: 6px 4px; display: flex; flex-direction: column;
    align-items: center; gap: 1px; }
  .tab.sel { background: var(--card-background-color); box-shadow: 0 1px 3px rgba(0,0,0,.25); }
  .tab-label { font-weight: 500; font-size: .92em; display: flex; align-items: center; gap: 5px; }
  .tab-days { font-size: .75em; color: var(--secondary-text-color); }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--primary-color); display: inline-block; }
  .rooms { display: flex; flex-direction: column; gap: 6px; }
  .room { padding: 10px; border-radius: 12px; border: 1px solid var(--divider-color); }
  .room.editing { border-color: var(--primary-color); }
  .room-row { display: flex; align-items: center; gap: 10px; }
  .room-icon { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    background: var(--secondary-background-color); cursor: pointer; flex-shrink: 0; --mdc-icon-size: 22px; }
  .room-icon.heating { background: rgba(255,111,0,.18); color: #ff6f00; }
  .room-main { flex: 1; min-width: 0; cursor: pointer; }
  .room-name { font-weight: 500; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .room-sub { font-size: .9em; color: var(--secondary-text-color); display: flex; align-items: center; gap: 4px; white-space: nowrap; overflow: hidden; }
  .room-sub b { color: var(--primary-text-color); font-weight: 500; }
  .flame { --mdc-icon-size: 16px; color: #ff6f00; }
  .room-stufe { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex-shrink: 0; }
  @media (max-width: 420px) { .next { display: none; } }
  .pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px 2px 7px; border-radius: 12px;
    background: color-mix(in srgb, var(--c) 22%, transparent); color: var(--c); font-size: .85em; font-weight: 500;
    --mdc-icon-size: 15px; }
  .next { font-size: .75em; color: var(--secondary-text-color); white-space: nowrap; }
  .badge { font-size: .72em; padding: 1px 7px; border-radius: 8px; background: var(--secondary-background-color);
    color: var(--secondary-text-color); font-weight: 400; display: inline-flex; align-items: center; gap: 3px; --mdc-icon-size: 12px; }
  .badge.manual { background: rgba(33,150,243,.18); color: #2196f3; }
  .badge.boost { background: rgba(244,67,54,.18); color: #f44336; }
  .badge.warn { background: rgba(255,152,0,.2); color: #ff9800; }
  .timeline { margin-top: 8px; cursor: pointer; }
  .timeline.edit { cursor: copy; }
  .bar { position: relative; height: 22px; border-radius: 6px; overflow: hidden; background: var(--secondary-background-color); }
  .seg { position: absolute; top: 0; bottom: 0; display: flex; align-items: center; padding-left: 4px; box-sizing: border-box;
    border-right: 1px solid var(--card-background-color); }
  .seg.carry { opacity: .55; }
  .seg { overflow: hidden; }
  .seg span { font-size: .68em; color: #fff; text-shadow: 0 0 2px rgba(0,0,0,.6); white-space: nowrap; pointer-events: none; }
  .now { position: absolute; top: -2px; bottom: -2px; width: 2px; margin-left: -1px; background: var(--primary-text-color);
    box-shadow: 0 0 0 1px var(--card-background-color); }
  .ticks { position: relative; height: 14px; font-size: .65em; color: var(--secondary-text-color); }
  .ticks span { position: absolute; transform: translateX(-50%); top: 2px; }
  .ticks span:first-child { transform: none; }
  .ticks span:last-child { transform: translateX(-100%); }
  .editor { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--divider-color); display: flex;
    flex-direction: column; gap: 8px; }
  .ed-title { font-weight: 500; font-size: .9em; color: var(--secondary-text-color); }
  .pts { display: flex; flex-direction: column; gap: 6px; }
  .pt { display: flex; align-items: center; gap: 8px; }
  .pt input[type=time], .pt select { font: inherit; padding: 5px 8px; border-radius: 8px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); }
  .pt select { flex: 1; min-width: 0; }
  .sw { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
  .text-btn { border: none; background: none; color: var(--primary-color); display: inline-flex; align-items: center;
    gap: 4px; padding: 6px 4px; align-self: flex-start; --mdc-icon-size: 18px; font-weight: 500; }
  .copy-h { font-size: .8em; color: var(--secondary-text-color); margin-bottom: 4px; }
  .copy-list { display: flex; flex-wrap: wrap; gap: 4px 14px; }
  .cb { display: flex; align-items: center; gap: 4px; font-size: .85em; cursor: pointer; }
  .ed-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .primary { border: none; border-radius: 18px; padding: 7px 18px; background: var(--primary-color);
    color: var(--text-primary-color, #fff); font-weight: 500; }
  .primary:disabled { opacity: .6; }
  .err { color: var(--error-color, #db4437); font-size: .9em; }
  .empty { color: var(--secondary-text-color); padding: 8px 0; }
  .axis-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: .78em; color: var(--secondary-text-color); }
  .axis-legend span { display: flex; align-items: center; gap: 5px; }
  .axis-legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .stufen { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 6px;
    border-top: 1px solid var(--divider-color); padding-top: 12px; }
  .stufe { display: flex; align-items: center; gap: 6px; --mdc-icon-size: 18px; }
  .stufe > ha-icon { color: var(--c); }
  .stufe-label { flex: 1; font-size: .9em; }
  .stufe-val { min-width: 54px; text-align: center; font-variant-numeric: tabular-nums; font-weight: 500; }
</style>`;

if (!customElements.get("heizplaner-card")) {
  customElements.define("heizplaner-card", HeizplanerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "heizplaner-card",
    name: "Heizplaner",
    description: "Wochenplan f\u00fcr die Heizung \u2013 R\u00e4ume, Stufen und Zeiten bearbeiten",
    preview: false,
  });
  console.info(`%c HEIZPLANER-CARD %c ${HP_VERSION} `, "background:#ff9800;color:#000;font-weight:700", "");
}
