/* Race Replay — clientside animation loop (see tabs/replay.py).
 *
 * The replay payload (per-driver x/y/didx arrays on a shared time grid) lives
 * in the `replay-data` dcc.Store; a dcc.Interval ticks `tick` below, which
 * advances the playhead and Plotly.restyle's the car-dot traces directly —
 * zero server round-trips during playback. */

(function () {
  const R = { idx: 0, playing: false, dragging: false, wheelUntil: 0, guardsOn: false };
  const nu = () => window.dash_clientside.no_update;

  /* Plotly WebGL limitation: a restyle re-renders the 3D scene and cancels an
   * in-progress camera drag. Workaround: while the pointer is down (or the
   * wheel just fired) on the map, keep the playhead running but skip the dot
   * updates — orbit/zoom stays smooth and the dots catch up on release. */
  function installGuards() {
    const el = document.getElementById("replay-graph");
    if (!el || el._replayGuards) return;   // per-element: tab re-renders recreate the div
    el.addEventListener("pointerdown", () => { R.dragging = true; }, true);
    el.addEventListener("wheel", () => { R.wheelUntil = Date.now() + 400; },
                        { capture: true, passive: true });
    el._replayGuards = true;
    if (!R.guardsOn) {                     // window-level listeners only once
      window.addEventListener("pointerup", () => { R.dragging = false; }, true);
      window.addEventListener("blur", () => { R.dragging = false; });
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

  /* Restyle the map (2D or 3D) and the elevation strip at frame i. */
  function render(data, i) {
    i = clampFrame(data, i);
    const xs = [], ys = [], zs = [], sx = [], sy = [];
    const o = data.outline;
    for (const d of data.drivers) {
      xs.push(d.x[i]);
      ys.push(d.y[i]);
      const di = d.didx ? d.didx[i] : null;
      if (di !== null && di !== undefined && o.z) {
        zs.push(o.z[di]);
        sx.push(o.dist[di]);
        sy.push(o.z[di] === null ? null : o.z[di] / 10.0);
      } else {
        zs.push(null);
        sx.push(null);
        sy.push(null);
      }
    }
    const gd = plotDiv("replay-graph");
    const ci = carsTraceIndex(gd);
    if (gd && ci >= 0 && !interacting()) {
      const upd = gd.data[ci].type === "scatter3d"
        ? { x: [xs], y: [ys], z: [zs] }
        : { x: [xs], y: [ys] };
      Plotly.restyle(gd, upd, [ci]);
    }
    if (data.has_z) {
      const sg = plotDiv("replay-strip");
      const si = carsTraceIndex(sg);
      if (sg && si >= 0) Plotly.restyle(sg, { x: [sx], y: [sy] }, [si]);
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
      /* New payload loaded → rewind, enable Play. */
      onData: function (data) {
        R.idx = 0;
        R.playing = false;
        installGuards();
        if (!data) return [true, 0];
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
        render(data, R.idx);
        setClock(data, R.idx);
        return Math.round(R.idx);
      },

      /* Slider changed (user scrub, or echo of our own tick). */
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
