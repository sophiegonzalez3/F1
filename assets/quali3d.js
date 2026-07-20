/* 3D Replay viewer — Three.js clientside implementation.
 *
 * One factory (makeReplay3D) drives two cards from the same code:
 *   • quali3d — each driver's best qualifying lap, ghost-synced at t=0
 *     (see tabs/quali_replay.py, ids q3d-*)
 *   • race3d  — the whole field on a shared race clock through lap 1
 *     (see tabs/race3d.py, ids r3d-*)
 *
 * The payload (georeferenced track scene + per-driver arrays at 10 Hz) lives
 * in the `<ID>-data` dcc.Store. onData builds the WebGL scene in #<ID>-mount;
 * a requestAnimationFrame loop renders at display rate and interpolates
 * between telemetry frames. The dcc.Interval only echoes the playhead back to
 * the slider. THREE is only referenced inside callbacks, so asset load order
 * doesn't matter.
 */

(function () {
  function makeReplay3D(ID, NS) {
  const Q = {
    data: null, t: 0, playing: false, speed: 1,
    camMode: "chase", focus: null, shown: [],
    three: null,             // {renderer, scene, camera, cars, ...}
    lastTs: null,
    orbit: { yaw: -0.7, pitch: 0.9, radius: 600 },
  };
  const nu = () => window.dash_clientside.no_update;
  window["__" + ID] = Q;                  // debug handle (read-only use)

  /* ---------- helpers ---------- */

  function lerp(a, b, f) { return a + (b - a) * f; }
  function lerpAngle(a, b, f) {
    let d = b - a;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    return a + d * f;
  }

  /* Elevation of a car at (x, y) near scene section di: lateral offset along
   * the section normal, interpolated across the stored cross-section. */
  function surfaceZ(sc, di, x, y) {
    const dx = x - sc.cx[di], dy = y - sc.cy[di];
    const lat = dx * sc.nx[di] + dy * sc.ny[di];
    let f = Math.max(-1, Math.min(1, lat / sc.hw[di]));
    const xs = sc.xsec;                       // [-1,-.5,0,.5,1]
    for (let k = 0; k < xs.length - 1; k++) {
      if (f <= xs[k + 1] || k === xs.length - 2) {
        const u = (f - xs[k]) / (xs[k + 1] - xs[k]);
        return lerp(sc.z[k][di], sc.z[k + 1][di], Math.max(0, Math.min(1, u)));
      }
    }
    return sc.z[2][di];
  }

  /* Precompute Float32 x/y/z/heading per frame for one driver. */
  function bakeDriver(sc, d) {
    const n = d.x.length;
    const x = new Float32Array(n), y = new Float32Array(n),
          z = new Float32Array(n), h = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      x[i] = d.x[i] / 100;
      y[i] = d.y[i] / 100;
      z[i] = surfaceZ(sc, d.didx[i], x[i], y[i]);
    }
    for (let i = 0; i < n; i++) {
      const a = Math.max(0, i - 1), b = Math.min(n - 1, i + 1);
      h[i] = Math.atan2(y[b] - y[a], x[b] - x[a]);
    }
    // light smoothing of heading (telemetry jitter)
    for (let i = 1; i < n; i++) h[i] = lerpAngle(h[i - 1], h[i], 0.6);
    return { x, y, z, h };
  }

  /* ---------- scene construction ---------- */

  function trackMesh(sc) {
    const THREE = window.THREE;
    const n = sc.n;
    // lateral vertex layout: fractions of half-width + which xsec column to
    // interpolate z from; outer 7% band is painted as the white edge line.
    const F = [-1, -0.93, -0.5, 0, 0.5, 0.93, 1];
    const asphalt = new THREE.Color(0x3a3a46);
    const asphaltHi = new THREE.Color(0x55555f);
    const edge = new THREE.Color(0xd8d8d8);
    const kerbRed = new THREE.Color(0xb23230);
    const kerbWhite = new THREE.Color(0xe8e8e8);
    const zmax = Math.max(sc.elev_range[1], 1);

    function zAtFrac(i, f) {
      const xs = sc.xsec;
      const ff = Math.max(xs[0], Math.min(xs[xs.length - 1], f));
      for (let k = 0; k < xs.length - 1; k++) {
        if (ff <= xs[k + 1] || k === xs.length - 2) {
          const u = (ff - xs[k]) / (xs[k + 1] - xs[k]);
          return lerp(sc.z[k][i], sc.z[k + 1][i], Math.max(0, Math.min(1, u)));
        }
      }
      return sc.z[2][i];
    }

    const nv = F.length;
    const pos = new Float32Array(n * nv * 3);
    const col = new Float32Array(n * nv * 3);
    for (let i = 0; i < n; i++) {
      for (let k = 0; k < nv; k++) {
        const off = F[k] * sc.hw[i];
        const j = (i * nv + k) * 3;
        pos[j] = sc.cx[i] + sc.nx[i] * off;
        pos[j + 1] = sc.cy[i] + sc.ny[i] * off;
        pos[j + 2] = zAtFrac(i, F[k]);
        let c;
        if (Math.abs(F[k]) > 0.94) {
          // edge band: white line, or red/white kerb on the apex side
          const kb = sc.kerb ? sc.kerb[i] : 0;
          const onKerb = (kb === 1 && F[k] > 0) || (kb === 2 && F[k] < 0);
          c = onKerb
            ? (Math.floor(sc.dist[i] / 4) % 2 ? kerbRed : kerbWhite)
            : edge;
        } else {
          c = asphalt.clone().lerp(asphaltHi, sc.z[2][i] / zmax);
        }
        col[j] = c.r; col[j + 1] = c.g; col[j + 2] = c.b;
      }
    }
    const idx = [];
    for (let i = 0; i < n - 1; i++) {
      for (let k = 0; k < nv - 1; k++) {
        const a = i * nv + k, b = a + nv;
        idx.push(a, b, a + 1, a + 1, b, b + 1);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    const mat = new THREE.MeshLambertMaterial({
      vertexColors: true, side: THREE.DoubleSide,
    });
    return new THREE.Mesh(geo, mat);
  }

  function shoulderMesh(sc) {
    /* grass/gravel shoulders: 8 m flat extensions beyond each edge */
    const THREE = window.THREE;
    const n = sc.n, W = 8.0;
    const pos = new Float32Array(n * 4 * 3);
    for (let i = 0; i < n; i++) {
      const hw = sc.hw[i];
      const zi = sc.z[0][i], zo = sc.z[sc.z.length - 1][i];
      const p = [
        [-(hw + W), zi], [-hw, zi], [hw, zo], [hw + W, zo],
      ];
      for (let k = 0; k < 4; k++) {
        const j = (i * 4 + k) * 3;
        pos[j] = sc.cx[i] + sc.nx[i] * p[k][0];
        pos[j + 1] = sc.cy[i] + sc.ny[i] * p[k][0];
        pos[j + 2] = p[k][1] - 0.06;
      }
    }
    const idx = [];
    for (let i = 0; i < n - 1; i++) {
      for (const k of [0, 2]) {              // two strips: left, right
        const a = i * 4 + k, b = a + 4;
        idx.push(a, b, a + 1, a + 1, b, b + 1);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    return new THREE.Mesh(geo, new THREE.MeshLambertMaterial({
      color: 0x232b22, side: THREE.DoubleSide,
    }));
  }

  function startLine(sc) {
    const THREE = window.THREE;
    const i = 0, hw = sc.hw[i];
    const geo = new THREE.BufferGeometry();
    const L = 2.0;   // stripe length along track
    const tx = -sc.ny[i], ty = sc.nx[i];     // tangent
    const pos = new Float32Array(4 * 3);
    const corners = [[-hw, 0], [hw, 0], [-hw, L], [hw, L]];
    corners.forEach((c, k) => {
      pos[k * 3] = sc.cx[i] + sc.nx[i] * c[0] + tx * c[1];
      pos[k * 3 + 1] = sc.cy[i] + sc.ny[i] * c[0] + ty * c[1];
      pos[k * 3 + 2] = surfaceHere(sc, i, c[0]) + 0.05;
    });
    function surfaceHere(sc, i, off) {
      return surfaceZ(sc, i, sc.cx[i] + sc.nx[i] * off, sc.cy[i] + sc.ny[i] * off);
    }
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setIndex([0, 1, 2, 2, 1, 3]);
    geo.computeVertexNormals();
    return new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: 0xffffff }));
  }

  /* ---------- surroundings (phase 2) ----------
   * Everything here is deliberately MONOCHROME — near-greyscale materials so
   * the coloured track ribbon, edge lines and cars stay the visual focus.
   * The geometry exists to convey wall proximity, speed and elevation. */

  function terrainMesh(t) {
    const THREE = window.THREE;
    const nx = t.nx, ny = t.ny;
    const pos = new Float32Array(nx * ny * 3);
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const k = (j * nx + i) * 3;
        pos[k] = t.x0 + i * t.step;
        pos[k + 1] = t.y0 + j * t.step;
        pos[k + 2] = t.z[j * nx + i] / 10 - 0.45;   // sit under the shoulders
      }
    }
    const idx = [];
    for (let j = 0; j < ny - 1; j++) {
      for (let i = 0; i < nx - 1; i++) {
        const a = j * nx + i, b = a + nx;
        idx.push(a, a + 1, b, b, a + 1, b + 1);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    return new THREE.Mesh(geo, new THREE.MeshLambertMaterial({
      color: 0x17171d,
    }));
  }

  function buildingsMesh(list) {
    const THREE = window.THREE;
    const pos = [];
    function quad(ax, ay, az, bx, by, bz, cx2, cy2, cz, dx2, dy2, dz) {
      pos.push(ax, ay, az, bx, by, bz, cx2, cy2, cz,
               ax, ay, az, cx2, cy2, cz, dx2, dy2, dz);
    }
    for (const b of list) {
      const p = b.p, n = p.length, z0 = b.z, z1 = b.z + b.h;
      for (let i = 0; i < n; i++) {
        const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % n];
        quad(x1, y1, z0, x2, y2, z0, x2, y2, z1, x1, y1, z1);
      }
      try {                                    // flat roof
        const v2 = p.map(([x, y]) => new THREE.Vector2(x, y));
        const tris = THREE.ShapeUtils.triangulateShape(v2, []);
        for (const [a, bb, c] of tris) {
          pos.push(p[a][0], p[a][1], z1, p[bb][0], p[bb][1], z1,
                   p[c][0], p[c][1], z1);
        }
      } catch (e) { /* degenerate footprint — walls alone still read fine */ }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(pos), 3));
    geo.computeVertexNormals();
    const mat = new THREE.MeshLambertMaterial({
      color: 0x26262d, side: THREE.DoubleSide, flatShading: true,
    });
    return new THREE.Mesh(geo, mat);
  }

  function wallsMesh(list) {
    const THREE = window.THREE;
    const pos = [];
    for (const w of list) {
      const p = w.p, z = w.z, h = w.h;
      for (let i = 0; i < p.length - 1; i++) {
        const [x1, y1] = p[i], [x2, y2] = p[i + 1];
        const za = z[i], zb = z[i + 1];
        pos.push(x1, y1, za, x2, y2, zb, x2, y2, zb + h,
                 x1, y1, za, x2, y2, zb + h, x1, y1, za + h);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(pos), 3));
    geo.computeVertexNormals();
    return new THREE.Mesh(geo, new THREE.MeshLambertMaterial({
      color: 0x3e3e46, side: THREE.DoubleSide, flatShading: true,
    }));
  }

  function treesMesh(list) {
    const THREE = window.THREE;
    const geo = new THREE.ConeGeometry(2.0, 6.5, 6);
    geo.rotateX(Math.PI / 2);                  // cone axis → +Z
    const mat = new THREE.MeshLambertMaterial({ color: 0x1e2226 });
    const inst = new THREE.InstancedMesh(geo, mat, list.length);
    const m4 = new THREE.Matrix4();
    list.forEach((t, i) => {
      const s = 0.7 + ((i * 2654435761) % 100) / 160;   // hash-ish variety
      m4.makeScale(s, s, s);
      m4.setPosition(t[0], t[1], t[2] + 3.25 * s);
      inst.setMatrixAt(i, m4);
    });
    return inst;
  }

  function addSurround(scene, sur) {
    /* Returns the buildings/walls/trees materials so the TV camera can fade
     * them (they sit between fixed TV pylons and the cars on street
     * circuits). Terrain stays opaque — it is clamped below the track. */
    const out = { mats: [], bldg: null };
    if (!sur) return out;
    if (sur.terrain) scene.add(terrainMesh(sur.terrain));
    if (sur.buildings && sur.buildings.length) {
      const m = buildingsMesh(sur.buildings);
      scene.add(m); out.mats.push(m.material); out.bldg = m;
    }
    if (sur.walls && sur.walls.length) {
      const m = wallsMesh(sur.walls);
      scene.add(m); out.mats.push(m.material);
    }
    if (sur.trees && sur.trees.length) {
      const m = treesMesh(sur.trees);
      scene.add(m); out.mats.push(m.material);
    }
    return out;
  }

  function textSprite(text, color, scale) {
    const THREE = window.THREE;
    const cv = document.createElement("canvas");
    const font = "bold 64px Inter, sans-serif";
    let ctx = cv.getContext("2d");
    ctx.font = font;
    // width follows the text so long corner names don't clip
    cv.width = Math.max(128, Math.ceil(ctx.measureText(text).width) + 48);
    cv.height = 96;
    ctx = cv.getContext("2d");
    ctx.font = font;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.lineWidth = 8; ctx.strokeStyle = "rgba(0,0,0,0.85)";
    ctx.strokeText(text, cv.width / 2, 48);
    ctx.fillStyle = color;
    ctx.fillText(text, cv.width / 2, 48);
    const tex = new THREE.CanvasTexture(cv);
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, depthTest: false, transparent: true,
    }));
    spr.scale.set(scale * cv.width / cv.height, scale, 1);
    return spr;
  }

  function carModel(color) {
    const THREE = window.THREE;
    const g = new THREE.Group();
    // slight self-illumination: cars stay readable in tunnels and shadow —
    // they are the only strongly coloured objects in the scene
    const body = new THREE.MeshLambertMaterial({
      color: new THREE.Color(color),
      emissive: new THREE.Color(color), emissiveIntensity: 0.35,
    });
    const dark = new THREE.MeshLambertMaterial({ color: 0x111114 });

    const chassis = new THREE.Mesh(new THREE.BoxGeometry(4.6, 1.5, 0.6), body);
    chassis.position.set(0, 0, 0.55);
    const nose = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.7, 0.35), body);
    nose.position.set(2.9, 0, 0.45);
    const cockpit = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.8, 0.5), dark);
    cockpit.position.set(0.2, 0, 1.0);
    const fwing = new THREE.Mesh(new THREE.BoxGeometry(0.7, 2.0, 0.12), body);
    fwing.position.set(3.4, 0, 0.28);
    const rwing = new THREE.Mesh(new THREE.BoxGeometry(0.5, 1.9, 0.14), body);
    rwing.position.set(-2.5, 0, 1.15);
    g.add(chassis, nose, cockpit, fwing, rwing);

    const wg = new THREE.CylinderGeometry(0.36, 0.36, 0.4, 10);
    [[1.6, 1.0], [1.6, -1.0], [-1.7, 1.0], [-1.7, -1.0]].forEach(([wx, wy]) => {
      const w = new THREE.Mesh(wg, dark);
      w.position.set(wx, wy, 0.36);
      // cylinder axis is Y by default — already the wheel axle direction
      g.add(w);
    });
    return g;
  }

  function disposeScene() {
    const T = Q.three;
    if (!T) return;
    cancelAnimationFrame(T.raf);
    if (T.ro) T.ro.disconnect();
    T.scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
          if (m.map) m.map.dispose();
          m.dispose();
        });
      }
    });
    T.renderer.dispose();
    if (T.renderer.domElement.parentNode)
      T.renderer.domElement.parentNode.removeChild(T.renderer.domElement);
    Q.three = null;
  }

  function buildScene() {
    const THREE = window.THREE;
    const mount = document.getElementById(ID + "-mount");
    if (!mount || !Q.data) return false;
    disposeScene();
    mount.innerHTML = "";

    const sc = Q.data.scene;
    const W = mount.clientWidth || 900, H = mount.clientHeight || 560;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(W, H);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x14141f);
    scene.fog = new THREE.Fog(0x14141f, 900, 2600);

    scene.add(new THREE.HemisphereLight(0x8899bb, 0x223311, 1.0));
    const sun = new THREE.DirectionalLight(0xfff2dd, 1.05);
    sun.position.set(300, -500, 600);
    scene.add(sun);

    // extents / center
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9, zTop = 0;
    for (let i = 0; i < sc.n; i++) {
      x0 = Math.min(x0, sc.cx[i]); x1 = Math.max(x1, sc.cx[i]);
      y0 = Math.min(y0, sc.cy[i]); y1 = Math.max(y1, sc.cy[i]);
      zTop = Math.max(zTop, sc.z[2][i]);
    }
    const ctr = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, zTop / 2);
    const span = Math.max(x1 - x0, y1 - y0);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(span * 6, span * 6),
      new THREE.MeshLambertMaterial({ color: 0x15181a }));
    ground.position.set(ctr.x, ctr.y, -1.5);
    scene.add(ground);

    scene.add(shoulderMesh(sc));
    scene.add(trackMesh(sc));
    scene.add(startLine(sc));
    const sur = addSurround(scene, sc.surround);

    (sc.corners || []).forEach((c) => {
      const label = "T" + c.n + (c.letter || "") + (c.name ? "  " + c.name : "");
      const spr = textSprite(label, "#9aa2ff", 4.0);
      spr.material.opacity = 0.8;
      spr.position.set(sc.cx[c.i], sc.cy[c.i], sc.z[2][c.i] + 7);
      scene.add(spr);
    });
    (sc.straights || []).forEach((s) => {
      const spr = textSprite(s.name, "#8fa3ad", 3.6);
      spr.material.opacity = 0.7;
      spr.position.set(sc.cx[s.i], sc.cy[s.i], sc.z[2][s.i] + 9);
      scene.add(spr);
    });

    // cars
    const cars = {};
    Q.data.drivers.forEach((d) => {
      const grp = carModel(d.color);
      const label = textSprite(d.code, d.color, 2.4);
      label.position.set(0, 0, 3.0);
      grp.add(label);
      grp.visible = false;
      scene.add(grp);
      cars[d.code] = { grp: grp, d: d, baked: bakeDriver(sc, d), label: label };
    });

    const camera = new THREE.PerspectiveCamera(55, W / H, 0.5, 6000);
    camera.up.set(0, 0, 1);
    camera.position.set(ctr.x, ctr.y - span * 0.7, span * 0.55);
    camera.lookAt(ctr);

    // TV camera pylons every ~500 m, offset from the track edge
    const tvCams = [];
    const stride = Math.max(1, Math.round(500 / sc.step));
    for (let i = 0; i < sc.n; i += stride) {
      tvCams.push(new THREE.Vector3(
        sc.cx[i] + sc.nx[i] * 35,
        sc.cy[i] + sc.ny[i] * 35,
        sc.z[2][i] + 14));
    }

    // HUD overlay
    const hud = document.createElement("div");
    hud.style.cssText =
      "position:absolute;left:14px;bottom:12px;pointer-events:none;" +
      "font-family:Inter,sans-serif;color:#fff;text-shadow:0 1px 3px #000;";
    hud.innerHTML =
      '<div style="display:flex;align-items:baseline;gap:10px">' +
      '<span id="' + ID + '-hud-code" style="font-weight:800;font-size:1.05rem"></span>' +
      '<span id="' + ID + '-hud-spd" style="font-weight:800;font-size:1.9rem;' +
      'font-variant-numeric:tabular-nums"></span>' +
      '<span style="font-size:0.75rem;color:#aaa">km/h</span>' +
      '<span id="' + ID + '-hud-gear" style="font-weight:800;font-size:1.3rem;color:#9aa2ff"></span></div>' +
      '<div style="width:170px;height:5px;background:#333;border-radius:3px;margin-top:5px">' +
      '<div id="' + ID + '-hud-thr" style="height:5px;background:#2ECC71;border-radius:3px;width:0%"></div></div>' +
      '<div style="width:170px;height:5px;background:#333;border-radius:3px;margin-top:3px">' +
      '<div id="' + ID + '-hud-brk" style="height:5px;background:#E10600;border-radius:3px;width:0%"></div></div>' +
      '<div id="' + ID + '-hud-elev" style="font-size:0.7rem;color:#aaa;margin-top:4px"></div>';
    mount.appendChild(hud);

    // orbit interaction: left-drag rotates, right- or shift-drag PANS the
    // pivot point, wheel zooms (only applied while in orbit mode)
    let dragging = false, panning = false, px = 0, py = 0;
    renderer.domElement.addEventListener("pointerdown", (e) => {
      dragging = true;
      panning = (e.button === 2 || e.shiftKey);
      px = e.clientX; py = e.clientY;
    });
    renderer.domElement.addEventListener("contextmenu", (e) => {
      if (Q.camMode === "orbit") e.preventDefault();
    });
    window.addEventListener("pointerup", () => { dragging = false; });
    window.addEventListener("pointermove", (e) => {
      if (!dragging || Q.camMode !== "orbit") return;
      const dx = e.clientX - px, dy = e.clientY - py;
      px = e.clientX; py = e.clientY;
      if (panning) {
        // move the pivot in the camera's screen plane
        const k = Q.orbit.radius * 0.0014;
        const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
        const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
        Q.orbit.center.addScaledVector(right, -dx * k);
        Q.orbit.center.addScaledVector(up, dy * k);
      } else {
        Q.orbit.yaw -= dx * 0.005;
        Q.orbit.pitch = Math.max(0.08, Math.min(1.45,
          Q.orbit.pitch + dy * 0.004));
      }
    });
    renderer.domElement.addEventListener("wheel", (e) => {
      if (Q.camMode !== "orbit") return;
      e.preventDefault();
      Q.orbit.radius = Math.max(60, Math.min(span * 3,
        Q.orbit.radius * (e.deltaY > 0 ? 1.1 : 0.9)));
    }, { passive: false });
    Q.orbit.radius = span * 0.9;
    Q.orbit.center = ctr.clone();

    const T = {
      renderer, scene, camera, cars, ctr, span, tvCams, sc,
      camPos: camera.position.clone(), camTgt: ctr.clone(),
      camUp: new THREE.Vector3(0, 0, 1),
      surMats: sur.mats, bldg: sur.bldg, surFaded: false,
      occluded: false, occN: 0, ray: null,
      raf: 0, ro: null,
    };
    T.ro = new ResizeObserver(() => {
      const w = mount.clientWidth, h = mount.clientHeight;
      if (w && h) {
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      }
    });
    T.ro.observe(mount);
    Q.three = T;
    applyVisibility();
    animate();
    return true;
  }

  /* ---------- animation ---------- */

  function carState(code, t) {
    const T = Q.three;
    const car = T.cars[code];
    if (!car) return null;
    const d = car.d, b = car.baked;
    const dt = Q.data.dt, n = b.x.length;
    let f = t / dt;
    if (f > n - 1) f = n - 1;
    const i0 = Math.floor(f), i1 = Math.min(n - 1, i0 + 1), u = f - i0;
    return {
      x: lerp(b.x[i0], b.x[i1], u),
      y: lerp(b.y[i0], b.y[i1], u),
      z: lerp(b.z[i0], b.z[i1], u),
      h: lerpAngle(b.h[i0], b.h[i1], u),
      i: i0, finished: t >= d.dur,
    };
  }

  function updateHud(t) {
    const focus = Q.focus;
    const car = Q.three && Q.three.cars[focus];
    const el = (suffix) => document.getElementById(ID + suffix);
    if (!car || !el("-hud-spd")) return;
    const d = car.d;
    const i = Math.min(d.spd.length - 1, Math.floor(t / Q.data.dt));
    el("-hud-code").textContent = d.code + " · " + d.lt;
    el("-hud-code").style.color = d.color;
    el("-hud-spd").textContent = d.spd[i];
    el("-hud-gear").textContent = "G" + d.gear[i];
    el("-hud-thr").style.width = d.thr[i] + "%";
    el("-hud-brk").style.width = (d.brk[i] ? 100 : 0) + "%";
    const sc = Q.data.scene;
    const di = d.didx[i];
    el("-hud-elev").textContent =
      "elev +" + sc.z[2][di].toFixed(1) + " m · bank " +
      Math.abs(sc.bank[di]).toFixed(1) + "° · " +
      (sc.dist[di] / 1000).toFixed(2) + " km";
  }

  function updateCamera(st) {
    const THREE = window.THREE;
    const T = Q.three;
    const cam = T.camera;
    let eye, tgt, lerpF = 0.12;
    let upWant = null;                        // default: world z-up
    // Fade the surroundings when they stand between camera and car: always
    // in TV mode (fixed pylons), and on occlusion in chase/onboard (street
    // circuits — the raycast runs throttled in animate())
    const fade = (Q.camMode === "tv") || T.occluded;
    if (T.surMats && T.surFaded !== fade) {
      T.surFaded = fade;
      for (const m of T.surMats) {
        m.transparent = fade;
        m.opacity = fade ? 0.3 : 1.0;
        m.depthWrite = !fade;
        m.needsUpdate = true;
      }
    }
    if (Q.camMode === "orbit" || !st) {
      const o = Q.orbit;
      const c = o.center || T.ctr;
      const r = o.radius, cp = Math.cos(o.pitch), sp = Math.sin(o.pitch);
      eye = new THREE.Vector3(
        c.x + r * cp * Math.cos(o.yaw),
        c.y + r * cp * Math.sin(o.yaw),
        c.z + r * sp);
      tgt = c.clone();
      lerpF = 0.25;
      cam.fov = 55;
    } else if (Q.camMode === "chase") {
      const dx = Math.cos(st.h), dy = Math.sin(st.h);
      eye = new THREE.Vector3(st.x - dx * 13, st.y - dy * 13, st.z + 5);
      tgt = new THREE.Vector3(st.x + dx * 10, st.y + dy * 10, st.z + 1);
      cam.fov = 55;
    } else if (Q.camMode === "onboard") {
      const dx = Math.cos(st.h), dy = Math.sin(st.h);
      eye = new THREE.Vector3(st.x - dx * 1.2, st.y - dy * 1.2, st.z + 1.5);
      tgt = new THREE.Vector3(st.x + dx * 45, st.y + dy * 45, st.z + 1.0);
      lerpF = 0.55;
      cam.fov = 62;
      // roll with the banking: camera up = track surface normal
      // (bank > 0 = left side higher → the normal leans right, i.e. −n̂)
      const fd = T.cars[Q.focus] && T.cars[Q.focus].d;
      if (fd) {
        const di = fd.didx[Math.min(st.i, fd.didx.length - 1)];
        const th = (T.sc.bank[di] || 0) * Math.PI / 180;
        upWant = new THREE.Vector3(
          -Math.sin(th) * T.sc.nx[di],
          -Math.sin(th) * T.sc.ny[di],
          Math.cos(th));
      }
    } else {                                   // tv
      let bi = 0, bd = 1e18;
      T.tvCams.forEach((c, i) => {
        const dd = (c.x - st.x) ** 2 + (c.y - st.y) ** 2;
        if (dd < bd) { bd = dd; bi = i; }
      });
      eye = T.tvCams[bi];
      tgt = new THREE.Vector3(st.x, st.y, st.z + 1);
      lerpF = 1.0;                             // hard cuts, like real TV
      cam.fov = 28;
    }
    T.camPos.lerp(eye, lerpF);
    T.camTgt.lerp(tgt, Q.camMode === "tv" ? 0.35 : lerpF);
    T.camUp.lerp(upWant || new window.THREE.Vector3(0, 0, 1), 0.12).normalize();
    cam.up.copy(T.camUp);
    cam.position.copy(T.camPos);
    cam.lookAt(T.camTgt);
    cam.updateProjectionMatrix();
  }

  function animate() {
    const T = Q.three;
    if (!T) return;
    T.raf = requestAnimationFrame(animate);
    const now = performance.now();
    const dtReal = Q.lastTs ? Math.min(0.1, (now - Q.lastTs) / 1000) : 0;
    Q.lastTs = now;
    if (Q.playing) {
      Q.t += dtReal * Q.speed;
      if (Q.t >= Q.data.tMax) { Q.t = Q.data.tMax; Q.playing = false; }
    }
    let focusState = null;
    const hideFocusLabel = (Q.camMode === "chase" || Q.camMode === "onboard");
    for (const code of Object.keys(T.cars)) {
      const car = T.cars[code];
      if (!car.grp.visible) continue;
      const st = carState(code, Q.t);
      car.grp.position.set(st.x, st.y, st.z);
      car.grp.rotation.z = st.h;
      // hide labels near the camera: world-sized sprites with depthTest off
      // fill the screen when their car is just behind the focus car
      const camDist = car.grp.position.distanceTo(T.camera.position);
      car.label.visible = !(hideFocusLabel && code === Q.focus) && camDist > 14;
      if (code === Q.focus) focusState = st;
    }
    // throttled occlusion test: is a building between the camera and the
    // focus car? (chase/onboard on street circuits)
    if (T.bldg && focusState
        && (Q.camMode === "chase" || Q.camMode === "onboard")) {
      if (++T.occN % 6 === 0) {
        const THREE = window.THREE;
        const org = T.camera.position;
        const tgt = new THREE.Vector3(focusState.x, focusState.y,
                                      focusState.z + 1.0);
        const dir = tgt.clone().sub(org);
        const L = dir.length();
        T.ray = T.ray || new THREE.Raycaster();
        T.ray.set(org, dir.normalize());
        T.ray.far = L;
        T.occluded = T.ray.intersectObject(T.bldg, false).length > 0;
      }
    } else {
      T.occluded = false;
    }
    updateCamera(focusState);
    updateHud(Q.t);
    T.renderer.render(T.scene, T.camera);
  }

  function applyVisibility() {
    const T = Q.three;
    if (!T) return;
    const shown = new Set(Q.shown || []);
    for (const code of Object.keys(T.cars))
      T.cars[code].grp.visible = shown.has(code);
    if (Q.focus && !shown.has(Q.focus)) {
      const first = (Q.shown || [])[0];
      if (first) Q.focus = first;
    }
  }

  function clockText() {
    if (!Q.data) return "";
    const t = Q.t;
    const m = Math.floor(t / 60);
    const s = (t - m * 60).toFixed(1).padStart(4, "0");
    return m + ":" + s + " / " + Q.data.tMax.toFixed(1) + "s";
  }

  /* ---------- dash clientside namespace ---------- */

  window.dash_clientside = Object.assign({}, window.dash_clientside, {
    [NS]: {
      onData: function (data, shown, focus, camMode) {
        Q.data = data || null;
        Q.t = 0; Q.playing = false; Q.lastTs = null;
        Q.shown = shown || [];
        Q.focus = focus || (data && data.drivers[0] && data.drivers[0].code);
        Q.camMode = camMode || "chase";
        if (!data) { disposeScene(); return 0; }
        // the mount div may not be laid out yet on a tab re-render
        let tries = 0;
        (function attempt() {
          if (buildScene() || ++tries > 20) return;
          setTimeout(attempt, 100);
        })();
        return 0;
      },

      tick: function (_n) {
        if (!Q.data) return nu();
        return Math.round(Q.t / Q.data.dt);
      },

      seek: function (value) {
        if (!Q.data || value === null || value === undefined) return nu();
        const t = value * Q.data.dt;
        if (Math.abs(t - Q.t) > Q.data.dt * 0.51) Q.t = t;  // real scrub
        return clockText();
      },

      playPause: function (_n) {
        if (!Q.data) return [true, "▶ Play"];
        Q.playing = !Q.playing;
        if (Q.playing && Q.t >= Q.data.tMax) Q.t = 0;
        return [!Q.playing, Q.playing ? "⏸ Pause" : "▶ Play"];
      },

      setSpeed: function (v) { Q.speed = v || 1; return ""; },

      setCamera: function (v) {
        Q.camMode = v || "chase";
        return "";
      },

      setShown: function (v) {
        Q.shown = v || [];
        applyVisibility();
        return "";
      },

      setFocus: function (v) {
        if (v) Q.focus = v;
        return "";
      },
    },
  });
  }

  makeReplay3D("q3d", "quali3d");   // QUALI tab — best-lap ghosts
  makeReplay3D("r3d", "race3d");    // RACE tab — lap 1, whole field
})();
