// Canonical kiosk canvas matches the source videos exactly. The complete
// 688×1032 experience is uniformly scaled to fit the browser when necessary.
const KIOSK_WIDTH = 688;
const KIOSK_HEIGHT = 1032;
const MAX_TRAIL = 280;
const MAX_RIBBON = 36;

const app = {
  p: null,
  w: 0,
  h: 0,
  bgDim: 0,
  clearForVideo: false,
  sparks: [],
  trail: [],
  ribbon: [],
  pointer: { x: 0, y: 0, inside: false },
};

const BIO_STOPS = [
  [35, 110, 255],
  [40, 195, 230],
  [65, 235, 165],
  [110, 175, 255],
  [175, 85, 255],
];

const sketch = (p) => {
  app.p = p;

  p.setup = () => {
    const canvas = p.createCanvas(100, 100);
    canvas.parent("stage");
    canvas.style("background", "transparent");
    p.pixelDensity(Math.min(window.devicePixelRatio || 1, 2));
    p.textFont("Bona Nova");
    layoutKiosk();
    seedSparks();
    bindPointer();
  };

  p.draw = () => {
    if (app.clearForVideo) {
      p.clear();
    } else {
      drawGradientField(p, app.bgDim);
    }
    drawSparks(p);
    updateTrail(p);
    drawTrail(p);
  };

  p.windowResized = () => {
    layoutKiosk();
    seedSparks();
  };

  function layoutKiosk() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const scale = Math.min(vw / KIOSK_WIDTH, vh / KIOSK_HEIGHT);
    const renderedWidth = KIOSK_WIDTH * scale;
    const renderedHeight = KIOSK_HEIGHT * scale;
    const x = Math.round((vw - renderedWidth) / 2);
    const y = Math.round((vh - renderedHeight) / 2);

    const kiosk = document.getElementById("kiosk");
    kiosk.style.width = `${KIOSK_WIDTH}px`;
    kiosk.style.height = `${KIOSK_HEIGHT}px`;
    kiosk.style.left = `${x}px`;
    kiosk.style.top = `${y}px`;
    kiosk.style.transform = `scale(${scale})`;
    kiosk.style.transformOrigin = "top left";
    kiosk.style.setProperty("--kh", `${KIOSK_HEIGHT}px`);

    p.resizeCanvas(KIOSK_WIDTH, KIOSK_HEIGHT);
    app.w = KIOSK_WIDTH;
    app.h = KIOSK_HEIGHT;
  }

  function seedSparks() {
    app.sparks = Array.from({ length: 90 }, () => ({
      x: Math.random(),
      y: Math.random(),
      s: 0.5 + Math.random() * 2.4,
      v: 0.0003 + Math.random() * 0.001,
      a: 60 + Math.random() * 120,
      hue: Math.random(),
    }));
  }

  function bindPointer() {
    if (document.body.dataset.trailBound) return;
    document.body.dataset.trailBound = "1";

    const syncPointer = (clientX, clientY) => {
      const kiosk = document.getElementById("kiosk");
      if (!kiosk) return;

      const rect = kiosk.getBoundingClientRect();
      const inside =
        clientX >= rect.left &&
        clientX <= rect.right &&
        clientY >= rect.top &&
        clientY <= rect.bottom;

      app.pointer = {
        x: (clientX - rect.left) * (app.w / rect.width),
        y: (clientY - rect.top) * (app.h / rect.height),
        inside,
      };
    };

    document.addEventListener(
      "pointermove",
      (event) => syncPointer(event.clientX, event.clientY),
      { passive: true }
    );
    document.addEventListener(
      "pointerdown",
      (event) => syncPointer(event.clientX, event.clientY),
      { passive: true }
    );
    document.addEventListener("pointerup", () => {
      app.pointer.inside = false;
    });
    document.addEventListener("pointercancel", () => {
      app.pointer.inside = false;
    });
  }
};

function sampleGradientRGB(t) {
  const wrapped = ((t % 1) + 1) % 1;
  const span = BIO_STOPS.length - 1;
  const pos = wrapped * span;
  const i = Math.min(Math.floor(pos), span - 1);
  const u = pos - i;
  const a = BIO_STOPS[i];
  const b = BIO_STOPS[i + 1];
  return [
    a[0] + (b[0] - a[0]) * u,
    a[1] + (b[1] - a[1]) * u,
    a[2] + (b[2] - a[2]) * u,
  ];
}

function drawGradientField(p, dim) {
  p.noStroke();
  const bands = 56;
  const bandH = Math.ceil(app.h / bands);
  const shade = 1 - dim * 0.6;

  for (let i = 0; i < bands; i += 1) {
    const t = i / (bands - 1);
    const [r, g, b] = sampleGradientRGB(t);
    const depth = p.lerp(0.08, 0.22, t);
    p.fill(r * depth * shade, g * depth * shade, b * depth * shade + 4);
    p.rect(0, i * bandH, app.w, bandH + 1);
  }

  p.fill(2, 4, 12, 40 + dim * 120);
  p.rect(0, 0, app.w, app.h);
}

function spawnMote(p, x, y, dx, dy, speed) {
  const energy = Math.min(1, speed / 24);
  app.trail.push({
    x: x + p.random(-2, 2),
    y: y + p.random(-2, 2),
    vx: dx * 0.04 + p.random(-0.55, 0.55),
    vy: dy * 0.04 + p.random(-0.7, 0.25),
    size: p.random(2, 7 + energy * 6),
    life: 1,
    decay: p.random(0.006, 0.018),
    hue: p.random(),
  });
}

function updateTrail(p) {
  const prev =
    app.ribbon.length > 0 ? app.ribbon[app.ribbon.length - 1] : null;
  const pointer = app.pointer;

  if (pointer.inside) {
    const dx = prev ? pointer.x - prev.x : 0;
    const dy = prev ? pointer.y - prev.y : 0;
    const speed = Math.hypot(dx, dy);
    const minStep = 3;

    if (!prev || speed >= minStep) {
      app.ribbon.push({ x: pointer.x, y: pointer.y, life: 1 });
      if (app.ribbon.length > MAX_RIBBON) app.ribbon.shift();
    }

    if (speed > 0.4) {
      const count = Math.min(8, 1 + Math.floor(speed / 5));
      for (let i = 0; i < count; i += 1) {
        const t = i / count;
        spawnMote(
          p,
          prev ? prev.x + dx * t : pointer.x,
          prev ? prev.y + dy * t : pointer.y,
          dx,
          dy,
          speed
        );
      }
    } else if (p.frameCount % 2 === 0) {
      spawnMote(p, pointer.x, pointer.y, 0, 0, 0);
    }
  }

  if (app.trail.length > MAX_TRAIL) {
    app.trail.splice(0, app.trail.length - MAX_TRAIL);
  }

  app.trail = app.trail.filter((mote) => {
    mote.x += mote.vx;
    mote.y += mote.vy;
    mote.vx *= 0.93;
    mote.vy = mote.vy * 0.93 - 0.018;
    mote.life -= mote.decay;
    return mote.life > 0;
  });

  app.ribbon = app.ribbon
    .map((node) => ({ ...node, life: node.life * 0.94 }))
    .filter((node) => node.life > 0.04);
}

function bioGradient(t, alpha, layer) {
  const [r, g, b] = sampleGradientRGB(t);
  // Soften outer layers with alpha only — keep hue bright (no near-black RGB).
  const alphaScale = layer === "halo" ? 0.45 : layer === "mid" ? 0.75 : 1;
  return [r, g, b, alpha * alphaScale];
}

function drawTrail(p) {
  const pointer = app.pointer;
  if (!app.trail.length && !app.ribbon.length && !pointer.inside) return;

  p.push();
  p.noStroke();
  p.blendMode(p.ADD);

  if (app.ribbon.length > 1) {
    const drift = (p.frameCount * 0.003) % 1;
    for (let i = 1; i < app.ribbon.length; i += 1) {
      const a = app.ribbon[i - 1];
      const b = app.ribbon[i];
      const t = i / app.ribbon.length;
      const glow = t * b.life;
      const mx = (a.x + b.x) * 0.5;
      const my = (a.y + b.y) * 0.5;
      const spread = p.lerp(8, 28, glow);
      const hue = (t * 0.75 + drift) % 1;

      let [r, g, bl, al] = bioGradient(hue, 28 * glow, "halo");
      p.fill(r, g, bl, al);
      p.circle(mx, my, spread * 2.6);

      [r, g, bl, al] = bioGradient(hue + 0.08, 52 * glow, "mid");
      p.fill(r, g, bl, al);
      p.circle(mx, my, spread);
    }
  }

  app.trail.forEach((mote) => {
    const glow = mote.life * mote.life;
    let [r, g, b, a] = bioGradient(mote.hue, 30 * glow, "halo");
    p.fill(r, g, b, a);
    p.circle(mote.x, mote.y, mote.size * 9);
    [r, g, b, a] = bioGradient(mote.hue + 0.12, 62 * glow, "mid");
    p.fill(r, g, b, a);
    p.circle(mote.x, mote.y, mote.size * 3.8);
    [r, g, b, a] = bioGradient(mote.hue + 0.2, 240 * glow, "core");
    p.fill(r, g, b, a);
    p.circle(mote.x, mote.y, mote.size * 0.75);
  });

  if (pointer.inside) {
    const breathe = 0.82 + 0.18 * Math.sin(p.frameCount * 0.07);
    const cursorHue =
      (p.frameCount * 0.004 + (pointer.x / Math.max(app.w, 1)) * 0.35) % 1;
    let [r, g, b, a] = bioGradient(cursorHue, 24, "halo");
    p.fill(r, g, b, a * breathe);
    p.circle(pointer.x, pointer.y, 160 * breathe);
    [r, g, b, a] = bioGradient(cursorHue + 0.15, 58, "mid");
    p.fill(r, g, b, a * breathe);
    p.circle(pointer.x, pointer.y, 56 * breathe);
    [r, g, b, a] = bioGradient(cursorHue + 0.28, 210, "core");
    p.fill(r, g, b, a);
    p.circle(pointer.x, pointer.y, 9);
  }

  p.blendMode(p.BLEND);
  p.pop();
}

function drawSparks(p) {
  p.noStroke();
  const pointer = app.pointer;

  app.sparks.forEach((spark) => {
    spark.y -= spark.v;
    if (spark.y < 0) spark.y = 1;

    const x = spark.x * app.w;
    const y = spark.y * app.h;
    const pulse = 0.55 + 0.45 * Math.sin(p.frameCount * 0.05 + spark.x * 12);
    const [r, g, b] = sampleGradientRGB(spark.hue);

    let wake = 0;
    if (pointer.inside) {
      const reach = Math.min(app.w, app.h) * 0.18;
      const d = Math.hypot(x - pointer.x, y - pointer.y);
      if (d < reach) wake = 1 - d / reach;
    }

    if (wake > 0) {
      const wakeHue = (spark.hue + p.frameCount * 0.002) % 1;
      const [wr, wg, wb] = bioGradient(wakeHue, 1, "core");
      p.fill(
        p.lerp(r, wr, wake * 0.65),
        p.lerp(g, wg, wake * 0.65),
        p.lerp(b, wb, wake * 0.65),
        spark.a * pulse * (1 + wake * 2)
      );
    } else {
      p.fill(r, g, b, spark.a * pulse);
    }
    p.circle(x, y, spark.s * (1 + wake * 1.8));
  });
}

new p5(sketch);
