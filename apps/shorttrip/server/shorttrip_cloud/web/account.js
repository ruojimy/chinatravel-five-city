// Account menu added to the Workbench top bar by the ShortTrip cloud gateway.
(() => {
  if (window.__shortTripAccount) return;
  window.__shortTripAccount = true;
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = "/account.css";
  document.head.appendChild(css);

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const STATES = {complete: "已完成", planning: "规划中", starting: "排队中", failed: "失败", worker_failed: "失败",
                  needs_confirmation: "待确认", infeasible: "无可行方案"};
  let me = null;

  async function call(path, options = {}) {
    const response = await fetch(path, {credentials: "same-origin", headers: {"Content-Type": "application/json"}, ...options});
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
      location.replace("/login?next=" + encodeURIComponent(location.pathname + location.search));
      throw new Error(data.message || "请先登录。");
    }
    if (!response.ok) throw new Error(data.message || "请求失败");
    return data;
  }

  function when(iso) {
    const d = new Date(iso);
    return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function mount() {
    const bar = document.querySelector(".topbar");
    if (!bar || document.getElementById("stAccountBtn")) return;
    const button = document.createElement("button");
    button.className = "ib st-account-btn";
    button.id = "stAccountBtn";
    button.type = "button";
    button.title = "账号与云端行程";
    button.textContent = (me.display_name || me.username).slice(0, 1).toUpperCase();
    const more = document.getElementById("moreBtn");
    bar.insertBefore(button, more ? more.previousElementSibling || more : null);
    button.addEventListener("click", event => { event.stopPropagation(); toggle(); });
  }

  function panel() {
    let el = document.getElementById("stAccountPanel");
    if (el) return el;
    el = document.createElement("section");
    el.id = "stAccountPanel";
    el.className = "st-account-panel";
    el.hidden = true;
    el.addEventListener("click", event => event.stopPropagation());
    document.body.appendChild(el);
    document.addEventListener("click", () => { el.hidden = true; });
    return el;
  }

  async function toggle() {
    const el = panel();
    if (!el.hidden) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `<header><div><b>${esc(me.display_name)}</b><span>@${esc(me.username)}${me.role === "admin" ? " · 管理员" : ""}</span></div>
      <button type="button" class="st-link" data-act="logout">退出登录</button></header>
      <h3>云端行程 <small>电脑和手机同步</small></h3><div class="st-trips">正在读取…</div>
      <footer><a href="/?new=1">＋ 新建规划</a><button type="button" class="st-link" data-act="password">修改密码</button></footer>`;
    el.querySelector('[data-act="logout"]').onclick = async () => {
      await call("/api/auth/logout", {method: "POST", body: "{}"}).catch(() => {});
      location.replace("/login");
    };
    el.querySelector('[data-act="password"]').onclick = () => passwordForm(el);
    try {
      const {trips} = await call("/api/account/trips");
      const list = el.querySelector(".st-trips");
      if (!trips.length) { list.innerHTML = `<p class="st-empty">还没有规划过行程。</p>`; return; }
      list.innerHTML = trips.map(t => `<a class="st-trip" href="/?job=${esc(t.job)}${t.request ? "&request=" + esc(t.request) : ""}">
          <span class="st-title">${esc(t.title || "行程规划")}${t.example ? ' <em>示例</em>' : ""}</span>
          <span class="st-meta">${esc(STATES[t.state] || t.state || "")} · ${when(t.created)}${t.client === "android" ? " · 手机" : t.client === "pc" ? " · 电脑" : ""}${t.adopted_edits ? ` · 已改 ${t.adopted_edits} 次` : ""}</span></a>`).join("");
    } catch (error) {
      el.querySelector(".st-trips").innerHTML = `<p class="st-empty">${esc(error.message)}</p>`;
    }
  }

  function passwordForm(el) {
    el.querySelector(".st-trips").innerHTML = `<form class="st-password">
      <input type="password" name="old" placeholder="原密码" autocomplete="current-password" required>
      <input type="password" name="new" placeholder="新密码（≥8 位，含字母和数字）" autocomplete="new-password" required>
      <button type="submit">保存新密码</button><p class="st-empty" role="alert"></p></form>`;
    const form = el.querySelector(".st-password");
    form.onsubmit = async event => {
      event.preventDefault();
      const note = form.querySelector("p");
      try {
        await call("/api/auth/password", {method: "POST", body: JSON.stringify({old: form.old.value, new: form.new.value})});
        note.textContent = "已修改。其他设备需要重新登录。";
        form.reset();
      } catch (error) { note.textContent = error.message; }
    };
  }

  function start() {
    call("/api/auth/me").then(data => {
      me = data.user;
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
      else mount();
    }).catch(() => {});
  }
  start();
})();
