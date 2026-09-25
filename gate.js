/* Candado de acceso del sitio (client-side, disuasivo).
 * Muestra una pantalla de desbloqueo antes de revelar cualquier página.
 * Guarda SÓLO el hash SHA-256 del código, nunca el código en texto.
 * OJO: GitHub Pages es estático/público -> esto tapa la interfaz, no es
 * seguridad real (los datos .json siguen accesibles por URL directa).
 */
(function () {
  var HASH = "f8c506fd6f84c434a9d7bf04f5583d765b7b63b99dd4cbff6ad5bf22f16adce4";
  var KEY = "bsj_gate_ok";           // marca de desbloqueo
  var STORE = window.sessionStorage; // por sesión: se re-pide al cerrar el navegador

  try { if (STORE.getItem(KEY) === HASH) return; } catch (e) {}

  // ocultar el contenido lo antes posible (esto corre en <head>)
  var st = document.createElement("style");
  st.textContent =
    "html.gate-locked body{visibility:hidden!important}" +
    "#gate-ov{visibility:visible!important;position:fixed;inset:0;z-index:2147483647;" +
    "display:flex;align-items:center;justify-content:center;background:#0f1115;" +
    "font-family:system-ui,Segoe UI,Roboto,sans-serif}" +
    "#gate-ov .box{width:min(92vw,360px);background:#171a21;border:1px solid #2a2f3a;" +
    "border-radius:14px;padding:26px 24px;text-align:center;box-shadow:0 12px 40px rgba(0,0,0,.5)}" +
    "#gate-ov .lock{font-size:34px}" +
    "#gate-ov h1{font-size:16px;color:#e6e8ec;margin:10px 0 4px}" +
    "#gate-ov h1 b{color:#F3C323}" +
    "#gate-ov p{font-size:12px;color:#9aa3b2;margin:0 0 16px}" +
    "#gate-ov input{width:100%;background:#1e222b;border:1px solid #2a2f3a;color:#e6e8ec;" +
    "border-radius:9px;padding:11px 12px;font-size:16px;text-align:center;letter-spacing:.15em}" +
    "#gate-ov input:focus{outline:none;border-color:#F3C323}" +
    "#gate-ov button{width:100%;margin-top:10px;background:#F3C323;border:0;color:#111;" +
    "font-weight:700;font-size:14px;border-radius:9px;padding:11px;cursor:pointer}" +
    "#gate-ov button:hover{filter:brightness(1.05)}" +
    "#gate-ov .err{color:#e0533b;font-size:12px;min-height:16px;margin-top:9px}";
  (document.head || document.documentElement).appendChild(st);
  document.documentElement.classList.add("gate-locked");

  async function sha256(txt) {
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(txt));
    return Array.prototype.map.call(new Uint8Array(buf), function (b) {
      return b.toString(16).padStart(2, "0");
    }).join("");
  }

  function build() {
    if (document.getElementById("gate-ov")) return;
    var ov = document.createElement("div");
    ov.id = "gate-ov";
    ov.innerHTML =
      '<div class="box">' +
      '<div class="lock">🔒</div>' +
      '<h1><b>Boletín Minero</b> San Juan</h1>' +
      '<p>Ingresá el código de acceso para continuar.</p>' +
      '<input id="gate-in" type="password" inputmode="numeric" autocomplete="off" ' +
      'placeholder="código" autofocus />' +
      '<button id="gate-btn">Desbloquear</button>' +
      '<div class="err" id="gate-err"></div>' +
      '</div>';
    (document.body || document.documentElement).appendChild(ov);

    var inp = document.getElementById("gate-in");
    var btn = document.getElementById("gate-btn");
    var err = document.getElementById("gate-err");

    async function tryUnlock() {
      var h = await sha256(inp.value.trim());
      if (h === HASH) {
        try { STORE.setItem(KEY, HASH); } catch (e) {}
        document.documentElement.classList.remove("gate-locked");
        ov.remove();
      } else {
        err.textContent = "Código incorrecto.";
        inp.value = "";
        inp.focus();
      }
    }
    btn.addEventListener("click", tryUnlock);
    inp.addEventListener("keydown", function (e) { if (e.key === "Enter") tryUnlock(); });
    setTimeout(function () { inp.focus(); }, 50);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
