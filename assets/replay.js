/* Race Replay — clientside animation loop (see tabs/replay.py).
 *
 * The replay payload (per-driver x/y/didx/prog/pos arrays on a shared time
 * grid, plus the leader progress curve L, per-frame flag codes and radio
 * clips) lives in the `replay-data` dcc.Store; a dcc.Interval ticks `tick`
 * below, which advances the playhead and Plotly.restyle's the car-dot traces
 * directly — zero server round-trips during playback. */

(function () {
  const R = { idx: 0, playing: false, dragging: false, wheelUntil: 0, guardsOn: false };
  const nu = () => window.dash_clientside.no_update;

  /* Plotly WebGL limitation: a restyle re-renders the 3D scene and cancels an
   * in-progress camera drag. Workaround: while the pointer is down (or the
   * wheel just fired) on the map, keep the playhead running but skip the dot
   * updates — orbit/zoom stays smooth and the dots catch up on release. */
  function installGuards() {
    const el = document.getElementById("replay-graph");
    if (el && !el._replayGuards) {  // per-element: tab re-renders recreate the div
      el.addEventListener("pointerdown", () => { R.dragging = true; }, true);
      // Wheel = camera zoom only in the 3D view; in 2D a wheel over the map
      // is just the page scrolling past — don't pause the dots for it.
      el.addEventListener("wheel", () => {
        const g = el.querySelector(".js-plotly-plot");
        if (g && g.layout && g.layout.scene) R.wheelUntil = Date.now() + 400;
      }, { capture: true, passive: true });
      el._replayGuards = true;
    }
    const pips = document.getElementById("replay-radio-pips");
    if (pips && !pips._replayGuards) {  // radio pip click → seek there
      pips.addEventListener("click", (e) => {
        const f = e.target && e.target.dataset && e.target.dataset.frame;
        if (f !== undefined && window.dash_clientside.set_props) {
          window.dash_clientside.set_props("replay-slider", { value: parseInt(f, 10) });
        }
      });
      pips._replayGuards = true;
    }
    if (!R.guardsOn) {                 // window-level listeners only once
      const clear = () => { R.dragging = false; };
      window.addEventListener("pointerup", clear, true);
      window.addEventListener("pointercancel", clear, true);  // gesture hijacked
      window.addEventListener("contextmenu", clear, true);    // right-click menu
      window.addEventListener("blur", clear);
      // Self-heal: mouse moving with no button held means any drag is over,
      // whatever event we missed — never leaves the dots frozen for good.
      window.addEventListener("pointermove", (e) => {
        if (R.dragging && e.buttons === 0) R.dragging = false;
      }, true);
      R.guardsOn = true;
    }
  }

  function interacting() {
    return R.dragging || Date.now() < R.wheelUntil;
  }

  function plotDiv(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    return el.querySelector(".js-plotly-plot") || el;
  }

  function carsTraceIndex(gd) {
    if (!gd || !gd.data) return -1;
    return gd.data.findIndex((t) => t.name === "cars");
  }

  function clampFrame(data, i) {
    return Math.max(0, Math.min(data.n - 1, Math.round(i)));
  }

  /* ── gap-to-leader machinery ─────────────────────────────────
   * L[j] = leader progress at frame j (made monotone once per payload).
   * Time behind the leader for progress p at frame i:
   *   gap = (i - lowerBound(L, p)) * dt        (same-point-on-road delta) */
  function leaderCurve(data) {
    if (data._Lmono) return data._Lmono;
    const L = data.L.slice();
    for (let j = 1; j < L.length; j++) if (L[j] < L[j - 1]) L[j] = L[j - 1];
    data._Lmono = L;
    return L;
  }

  function lowerBound(arr, x) {
    let lo = 0, hi = arr.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid] < x) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  function gapSeconds(data, d, i) {
    const p = d.prog ? d.prog[i] : null;
    if (p === null || p === undefined) return null;
    const j = lowerBound(leaderCurve(data), p);
    return Math.max(0, (i - j) * data.dt);
  }

  /* ── per-frame DOM updates: leaderboard, flag banner, radio ── */
  const FLAGS = {
    1: { text: "YELLOW FLAG",         bg: "#FFD700", fg: "#000" },
    2: { text: "SAFETY CAR",          bg: "#FFD700", fg: "#000" },
    3: { text: "VIRTUAL SAFETY CAR",  bg: "#FFD700", fg: "#000" },
    4: { text: "RED FLAG",            bg: "#E10600", fg: "#fff" },
  };

  function updateFlag(data, i) {
    const el = document.getElementById("replay-flag");
    if (!el || !data.flags) return;
    const f = FLAGS[data.flags[i]];
    if (!f) { el.style.display = "none"; return; }
    el.style.display = "block";
    el.style.background = f.bg;
    el.style.color = f.fg;
    el.textContent = f.text;
  }

  function updateBoard(data, i) {
    const el = document.getElementById("replay-board");
    if (!el) return;
    const running = [], out = [];
    for (const d of data.drivers) {
      const pos = d.pos ? d.pos[i] : null;
      if (pos === null || pos === undefined) { out.push(d); continue; }
      running.push([pos, d]);
    }
    running.sort((a, b) => a[0] - b[0]);
    let html = '<div style="color:#8a8a9a;font-size:0.6rem;letter-spacing:1px;' +
               'margin-bottom:6px;font-weight:600">LIVE ORDER · GAP</div>';
    let first = true;
    for (const [pos, d] of running) {
      const g = gapSeconds(data, d, i);
      const gapTxt = first ? "LEADER"
        : (g === null ? "—" : "+" + g.toFixed(1));
      first = false;
      html += rowHtml(pos, d, gapTxt, 1.0);
    }
    for (const d of out) html += rowHtml("–", d, "OUT", 0.38);
    el.innerHTML = html;
  }

  function rowHtml(pos, d, gapTxt, opacity) {
    return (
      '<div style="display:flex;align-items:center;margin-bottom:3px;opacity:' + opacity + '">' +
      '<span style="color:#8a8a9a;font-size:0.62rem;width:18px;text-align:right;' +
      'margin-right:5px;flex-shrink:0">' + pos + "</span>" +
      '<span style="background:' + d.color + ';color:#fff;border-radius:3px;' +
      'padding:0 5px;font-size:0.66rem;font-weight:700;margin-right:6px;' +
      'width:38px;text-align:center;flex-shrink:0">' + d.code + "</span>" +
      '<span style="color:#e8e8f0;font-size:0.64rem;font-variant-numeric:tabular-nums;' +
      'white-space:nowrap">' + gapTxt + "</span></div>"
    );
  }

  function updateRadio(data, i) {
    const el = document.getElementById("replay-radio-live");
    if (!el || !data.radio || !data.radio.length) return;
    // most recent clip passed by the playhead, shown for ~60 s of race time
    let last = null;
    for (const r of data.radio) {
      if (r.f > i) break;
      last = r;
    }
    if (last && (i - last.f) * data.dt <= 60) {
      el.textContent = "📻 " + last.code + " — “" + last.text + "”";
    } else {
      el.textContent = "";
    }
  }

  /* ── main per-frame render: map (2D/3D) or gap view + strip ── */
  function ensureGapLines(gd, data) {
    // lines are empty on a freshly-built gap figure → fill them once
    if (!gd.data.length || (gd.data[0].x && gd.data[0].x.length)) return;
    const L = leaderCurve(data);
    const STEP = 5;                       // 2.5 s resolution is plenty
    const xs = [], ys = [], idxs = [];
    data.drivers.forEach((d, di) => {
      const x = [], y = [];
      for (let i = 0; i < data.n; i += STEP) {
        const p = d.prog[i];
        if (p === null || p === undefined) { x.push(null); y.push(null); continue; }
        x.push((i * data.dt) / 60.0);
        y.push(Math.max(0, (i - lowerBound(L, p)) * data.dt));
      }
      xs.push(x); ys.push(y); idxs.push(di);
    });
    Plotly.restyle(gd, { x: xs, y: ys }, idxs);
  }

  function render(data, i, domToo) {
    i = clampFrame(data, i);
    const gd = plotDiv("replay-graph");
    const ci = carsTraceIndex(gd);
    const isGap = gd && gd.layout && gd.layout.meta && gd.layout.meta.view === "gap";

    if (gd && ci >= 0 && !interacting()) {
      if (isGap) {
        ensureGapLines(gd, data);
        const t = (i * data.dt) / 60.0;
        const xs = [], ys = [];
        for (const d of data.drivers) {
          const g = gapSeconds(data, d, i);
          xs.push(g === null ? null : t);
          ys.push(g);
        }
        Plotly.restyle(gd, { x: [xs], y: [ys] }, [ci]);
      } else {
        const xs = [], ys = [], zs = [];
        const o = data.outline;
        for (const d of data.drivers) {
          xs.push(d.x[i]);
          ys.push(d.y[i]);
          const di = d.didx ? d.didx[i] : null;
          zs.push(di !== null && di !== undefined && o.z ? o.z[di] : null);
        }
        const upd = gd.data[ci].type === "scatter3d"
          ? { x: [xs], y: [ys], z: [zs] }
          : { x: [xs], y: [ys] };
        Plotly.restyle(gd, upd, [ci]);
      }
    }

    if (data.has_z) {
      const sg = plotDiv("replay-strip");
      const si = carsTraceIndex(sg);
      if (sg && si >= 0) {
        const o = data.outline;
        const sx = [], sy = [];
        for (const d of data.drivers) {
          const di = d.didx ? d.didx[i] : null;
          if (di !== null && di !== undefined && o.z && o.z[di] !== null) {
            sx.push(o.dist[di]);
            sy.push(o.z[di] / 10.0);
          } else {
            sx.push(null);
            sy.push(null);
          }
        }
        Plotly.restyle(sg, { x: [sx], y: [sy] }, [si]);
      }
    }

    // Leaderboard / banner / radio are text — 3 Hz is plenty, and skipping
    // the innerHTML rebuild on most ticks keeps the 10 Hz dot loop light.
    if (domToo !== false) {
      updateBoard(data, i);
      updateFlag(data, i);
      updateRadio(data, i);
    }
  }

  function clockText(data, i) {
    i = clampFrame(data, i);
    const s = Math.round(i * data.dt);
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    return "LAP " + data.lap[i] + "/" + data.nLaps + " · " + mm + ":" + ss;
  }

  function setClock(data, i) {
    const el = document.getElementById("replay-clock");
    if (el) el.textContent = clockText(data, i);
  }

  window.dash_clientside = Object.assign({}, window.dash_clientside, {
    replay: {
      /* New payload loaded → rewind, enable Play, draw frame 0. */
      onData: function (data) {
        R.idx = 0;
        R.playing = false;
        installGuards();
        if (!data) return [true, 0];
        setTimeout(() => {               // wait for the figure to mount
          try { render(data, 0); setClock(data, 0); } catch (e) { /* not ready */ }
        }, 400);
        return [false, 0];
      },

      /* Interval tick → advance by speed × real-time. */
      tick: function (_n, speed, data) {
        installGuards();
        if (!data || !R.playing) return nu();
        R.idx += ((speed || 30) * 0.1) / data.dt; // 100 ms per tick
        if (R.idx >= data.n - 1) {
          R.idx = data.n - 1;
          R.playing = false;
        }
        R.ticks = (R.ticks || 0) + 1;
        render(data, R.idx, R.ticks % 3 === 0);
        setClock(data, R.idx);
        return Math.round(R.idx);
      },

      /* Slider changed (user scrub, pip click, or echo of our own tick). */
      seek: function (value, data) {
        if (!data || value === null || value === undefined) return nu();
        if (Math.abs(value - R.idx) >= 1) { // real scrub, not the tick echo
          R.idx = value;
          render(data, R.idx);
        }
        return clockText(data, R.idx);
      },

      /* Play/pause toggle; restart from the top when pressed at the end. */
      playPause: function (_n, data) {
        if (!data) return [true, "▶ Play"];
        R.playing = !R.playing;
        if (R.playing && R.idx >= data.n - 1) R.idx = 0;
        return [!R.playing, R.playing ? "⏸ Pause" : "▶ Play"];
      },

      /* 3D camera presets. */
      camera: function () {
        const trg = window.dash_clientside.callback_context.triggered;
        if (!trg || !trg.length) return nu();
        const which = trg[0].prop_id.split(".")[0];
        const eyes = {
          "replay-cam-top":  { eye: { x: 0, y: 0, z: 2.0 }, up: { x: 0, y: 1, z: 0 } },
          "replay-cam-side": { eye: { x: 0, y: -1.6, z: 0.12 }, up: { x: 0, y: 0, z: 1 } },
          "replay-cam-iso":  { eye: { x: 1.15, y: -1.15, z: 0.7 }, up: { x: 0, y: 0, z: 1 } },
        };
        const cam = eyes[which];
        const gd = plotDiv("replay-graph");
        if (cam && gd && gd.layout && gd.layout.scene) {
          Plotly.relayout(gd, { "scene.camera": cam });
        }
        return "";
      },
    },
  });
})();
