"use strict";

/*
 * Illustrated product packaging, drawn as inline SVG.
 *
 * Every catalogue item gets a package in its real-world shape (masala box,
 * ghee tin, oil pouch, tea pack, milk carton, rice bag, sugar sack, soda
 * bottle...) in its brand colours, with the name printed on the label.
 * Drawn rather than photographed: product photos and logos are copyrighted,
 * and these load instantly and stay consistent with the app's style.
 */
const ProductArt = (() => {
  // sku: [shape, main colour, accent colour, label line 1, label line 2, category]
  const ART = {
    "SHAN-BIRYANI": ["box", "#c8102e", "#ffd34d", "SHAN", "Biryani", "Masala"],
    "SHAN-PULAO": ["box", "#b5121b", "#f6e7c1", "SHAN", "Pulao", "Masala"],
    "SHAN-KARAHI": ["box", "#d1201f", "#ffb627", "SHAN", "Karahi", "Masala"],
    "SHAN-NIHARI": ["box", "#9e1b32", "#ffd34d", "SHAN", "Nihari", "Masala"],
    "NATIONAL-BIRYANI": ["box", "#0f7a3d", "#e63946", "NATIONAL", "Biryani", "Masala"],
    "RED-CHILLI": ["jar", "#c1121f", "#fefae0", "NATIONAL", "Lal Mirch", "Masala"],
    "HALDI": ["jar", "#e9a800", "#0f7a3d", "NATIONAL", "Haldi", "Masala"],
    "SALT-800G": ["pack", "#1d6fd1", "#ffffff", "NATIONAL", "Salt", "Masala"],
    "DALDA-TIN": ["tin", "#f4c430", "#127c3a", "DALDA", "Ghee 5kg", "Ghee & oil"],
    "DALDA-OIL": ["pouch", "#f4c430", "#127c3a", "DALDA", "Oil 1L", "Ghee & oil"],
    "SUFI-OIL": ["pouch", "#f28c28", "#1b4332", "SUFI", "Oil 1L", "Ghee & oil"],
    "MEZAN-GHEE": ["pouch", "#2d9a47", "#ffd166", "MEZAN", "Ghee 1kg", "Ghee & oil"],
    "TAPAL-DANEDAR": ["pack", "#b3001b", "#f2c14e", "TAPAL", "Danedar", "Tea & milk"],
    "LIPTON-YL": ["pack", "#f9c80e", "#d62828", "LIPTON", "Yellow Label", "Tea & milk"],
    "VITAL-TEA": ["pack", "#2b9348", "#f6aa1c", "VITAL", "Tea", "Tea & milk"],
    "MILKPAK-1L": ["carton", "#1f5fbf", "#ffffff", "MILKPAK", "1 Litre", "Tea & milk"],
    "OLPERS-1L": ["carton", "#16325c", "#7cc35f", "OLPER'S", "Milk 1L", "Tea & milk"],
    "TARANG-1L": ["carton", "#e85d04", "#6a3e1f", "TARANG", "Whitener", "Tea & milk"],
    "BASMATI-5KG": ["bag", "#7a1f2b", "#e8b84a", "SUPER", "Basmati 5kg", "Rice & flour"],
    "SELLA-25KG": ["sack", "#e9dcc0", "#8b5e34", "SELLA", "Rice 25kg", "Rice & flour"],
    "SUGAR-50KG": ["sack", "#f4f6f8", "#1d6fd1", "SUGAR", "50 kg", "Rice & flour"],
    "ATTA-20KG": ["bag", "#d9a441", "#2d6a4f", "SUNRIDGE", "Atta 20kg", "Rice & flour"],
    "DAAL-CHANA": ["grain", "#f2b134", "#9c6644", "DAAL", "Chana", "Rice & flour"],
    "DAAL-MASOOR": ["grain", "#e76f51", "#9c6644", "DAAL", "Masoor", "Rice & flour"],
    "PEPSI-1.5L": ["bottle", "#1d4ed8", "#e11d48", "PEPSI", "1.5L", "Drinks"],
    "COKE-1.5L": ["bottle", "#c8102e", "#ffffff", "COCA-COLA", "1.5L", "Drinks"],
    "SPRITE-1.5L": ["bottle", "#1a9850", "#ffd60a", "SPRITE", "1.5L", "Drinks"],
    "WATER-1.5L": ["bottle", "#7cc6fe", "#0b5394", "PURE LIFE", "1.5L", "Drinks"],
    "SURF-EXCEL": ["box", "#1e5bb8", "#f5c400", "SURF", "Excel", "Home care"],
    "ARIEL": ["box", "#0b7a3e", "#e8f5e9", "ARIEL", "Detergent", "Home care"],
    "LIFEBUOY": ["soap", "#d00000", "#ffffff", "LIFEBUOY", "Soap", "Home care"],
    "LUX": ["soap", "#7b2cbf", "#f1c0e8", "LUX", "Soap", "Home care"],
    "SAFEGUARD": ["soap", "#f8f9fa", "#1d6fd1", "SAFEGUARD", "Soap", "Home care"],
    "SUNSILK": ["shampoo", "#e0218a", "#2b2d42", "SUNSILK", "Shampoo", "Home care"],
    "COLGATE": ["tube", "#d00000", "#ffffff", "COLGATE", "Toothpaste", "Home care"],
    "LU-PRINCE": ["biscuit", "#5b2a86", "#c08552", "PRINCE", "Biscuit", "Snacks"],
    "LU-CANDI": ["biscuit", "#f77f00", "#fcbf49", "CANDI", "Biscuit", "Snacks"],
    "LU-TUC": ["biscuit", "#ffd60a", "#1d3557", "TUC", "Crackers", "Snacks"],
    "KOLSON-SLANTY": ["pack", "#2a9d8f", "#e9c46a", "SLANTY", "Snack", "Snacks"],
    "KNORR-NOODLES": ["pack", "#1b7a3c", "#ffd60a", "KNORR", "Noodles", "Snacks"],
  };
  const CATEGORIES = ["Masala", "Ghee & oil", "Tea & milk", "Rice & flour", "Drinks", "Home care", "Snacks"];

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** Black or white label text, whichever reads on the given fill. */
  function ink(hex) {
    const n = parseInt(hex.slice(1), 16);
    const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? "#14213d" : "#ffffff";
  }

  function shade(hex, amt) {
    const n = parseInt(hex.slice(1), 16);
    const f = (v) => Math.max(0, Math.min(255, Math.round(v + amt * 255)));
    return "#" + [f((n >> 16) & 255), f((n >> 8) & 255), f(n & 255)].map((v) => v.toString(16).padStart(2, "0")).join("");
  }

  function label(x, y, w, l1, l2, fill, color, size = 9) {
    const s1 = Math.min(size, (w / Math.max(4, l1.length)) * 1.7);
    const s2 = Math.min(size * 0.8, (w / Math.max(4, l2.length)) * 1.7);
    return `<text x="${x}" y="${y}" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-weight="800" font-size="${s1.toFixed(1)}" fill="${color}" letter-spacing=".4">${esc(l1)}</text>
      <text x="${x}" y="${y + s2 + 3}" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-weight="600" font-size="${s2.toFixed(1)}" fill="${color}" opacity=".9">${esc(l2)}</text>`;
  }

  const SHAPES = {
    // Spice/detergent box with a visible side face
    box: (c, a, l1, l2) => `
      <path d="M34 24 L80 24 L92 32 L92 100 L46 100 L34 92 Z" fill="${shade(c, -0.18)}"/>
      <rect x="34" y="24" width="46" height="76" rx="3" fill="${c}"/>
      <path d="M80 24 L92 32 L92 100 L80 100 Z" fill="${shade(c, -0.12)}"/>
      <rect x="38" y="34" width="38" height="30" rx="4" fill="${a}"/>
      ${label(57, 47, 34, l1, l2, a, ink(a))}
      <circle cx="57" cy="80" r="9" fill="${shade(c, 0.12)}"/><circle cx="57" cy="80" r="5" fill="${a}" opacity=".85"/>`,
    // Spice jar with lid
    jar: (c, a, l1, l2) => `
      <rect x="40" y="22" width="40" height="12" rx="3" fill="${shade(c, -0.2)}"/>
      <rect x="36" y="32" width="48" height="68" rx="9" fill="${c}"/>
      <rect x="39" y="46" width="42" height="32" rx="5" fill="${a}"/>
      ${label(60, 59, 38, l1, l2, a, ink(a))}
      <rect x="44" y="86" width="32" height="5" rx="2.5" fill="${shade(c, 0.15)}"/>`,
    // Ghee tin (cylinder)
    tin: (c, a, l1, l2) => `
      <rect x="32" y="30" width="56" height="66" fill="${c}"/>
      <ellipse cx="60" cy="96" rx="28" ry="7" fill="${shade(c, -0.2)}"/>
      <ellipse cx="60" cy="30" rx="28" ry="7" fill="${shade(c, 0.12)}"/>
      <ellipse cx="60" cy="30" rx="20" ry="4" fill="${shade(c, -0.08)}"/>
      <rect x="32" y="48" width="56" height="30" fill="${a}"/>
      ${label(60, 61, 50, l1, l2, a, ink(a))}
      <rect x="32" y="30" width="6" height="66" fill="#ffffff" opacity=".18"/>`,
    // Oil / ghee pouch
    pouch: (c, a, l1, l2) => `
      <path d="M38 30 Q36 22 44 22 L76 22 Q84 22 82 30 L86 92 Q86 100 78 100 L42 100 Q34 100 34 92 Z" fill="${c}"/>
      <rect x="38" y="22" width="44" height="7" rx="2" fill="${shade(c, -0.18)}"/>
      <path d="M40 46 L80 46 L82 76 L38 76 Z" fill="${a}"/>
      ${label(60, 58, 40, l1, l2, a, ink(a))}
      <path d="M44 84 Q60 92 76 84" stroke="${shade(c, 0.2)}" stroke-width="3" fill="none" stroke-linecap="round"/>`,
    // Stand-up pack with zig-zag top
    pack: (c, a, l1, l2) => `
      <path d="M36 28 l4 -5 l4 5 l4 -5 l4 5 l4 -5 l4 5 l4 -5 l4 5 l4 -5 l4 5 l4 -5 l4 5 L84 100 L36 100 Z" fill="${c}"/>
      <rect x="40" y="44" width="40" height="32" rx="5" fill="${a}"/>
      ${label(60, 57, 36, l1, l2, a, ink(a))}
      <rect x="36" y="88" width="48" height="5" fill="${shade(c, -0.15)}"/>`,
    // Gable-top milk carton
    carton: (c, a, l1, l2) => `
      <path d="M40 34 L60 18 L80 34 Z" fill="${shade(c, 0.1)}"/>
      <rect x="56" y="12" width="8" height="8" rx="1" fill="${shade(c, -0.2)}"/>
      <rect x="40" y="34" width="40" height="66" fill="${c}"/>
      <path d="M80 34 L90 40 L90 100 L80 100 Z" fill="${shade(c, -0.15)}"/>
      <rect x="43" y="48" width="34" height="32" rx="4" fill="${a}"/>
      ${label(60, 61, 32, l1, l2, a, ink(a))}
      <path d="M43 88 Q52 84 60 88 T77 88" stroke="${a}" stroke-width="2.5" fill="none"/>`,
    // Rice / atta bag with a tied top
    bag: (c, a, l1, l2) => `
      <path d="M38 34 Q34 64 36 100 L84 100 Q86 64 82 34 Z" fill="${c}"/>
      <path d="M44 34 Q60 20 76 34" fill="${shade(c, -0.15)}"/>
      <rect x="50" y="22" width="20" height="6" rx="3" fill="${a}"/>
      <rect x="40" y="50" width="40" height="30" rx="5" fill="${a}"/>
      ${label(60, 62, 36, l1, l2, a, ink(a))}
      <path d="M48 90 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4" stroke="${a}" stroke-width="2" fill="none"/>`,
    // Woven sack (bori)
    sack: (c, a, l1, l2) => `
      <path d="M34 30 Q30 66 34 102 L86 102 Q90 66 86 30 Z" fill="${c}" stroke="${shade(c, -0.25)}" stroke-width="1.5"/>
      <path d="M34 30 Q60 22 86 30" stroke="${shade(c, -0.35)}" stroke-width="2" stroke-dasharray="3 3" fill="none"/>
      <path d="M40 40 L80 40 M38 92 L82 92" stroke="${shade(c, -0.12)}" stroke-width="1"/>
      <rect x="40" y="50" width="40" height="30" rx="4" fill="${a}"/>
      ${label(60, 62, 36, l1, l2, a, ink(a))}`,
    // Lentils: bag with a window showing grains
    grain: (c, a, l1, l2) => `
      <path d="M38 30 Q34 64 36 100 L84 100 Q86 64 82 30 Z" fill="#f8f4ec" stroke="${shade(a, 0.2)}" stroke-width="1.5"/>
      <rect x="44" y="26" width="32" height="6" rx="3" fill="${a}"/>
      <ellipse cx="60" cy="72" rx="18" ry="16" fill="${c}"/>
      ${Array.from({ length: 14 }, (_, i) => `<circle cx="${48 + (i % 5) * 6}" cy="${64 + Math.floor(i / 5) * 6}" r="2.2" fill="${shade(c, -0.15)}"/>`).join("")}
      ${label(60, 44, 36, l1, l2, "#f8f4ec", "#3d2b1f")}`,
    // Soft-drink / water bottle
    bottle: (c, a, l1, l2) => `
      <rect x="53" y="14" width="14" height="8" rx="2" fill="${shade(a, -0.1)}"/>
      <path d="M54 22 L66 22 L66 30 Q80 38 80 52 L80 96 Q80 102 74 102 L46 102 Q40 102 40 96 L40 52 Q40 38 54 30 Z" fill="${c}" opacity=".95"/>
      <rect x="40" y="56" width="40" height="24" fill="${a}"/>
      ${label(60, 66, 38, l1, l2, a, ink(a))}
      <rect x="45" y="36" width="5" height="56" rx="2.5" fill="#ffffff" opacity=".28"/>`,
    // Shampoo bottle
    shampoo: (c, a, l1, l2) => `
      <rect x="52" y="14" width="16" height="12" rx="3" fill="${a}"/>
      <rect x="40" y="26" width="40" height="76" rx="12" fill="${c}"/>
      <rect x="44" y="48" width="32" height="30" rx="5" fill="#ffffff"/>
      ${label(60, 60, 30, l1, l2, "#ffffff", a)}
      <rect x="45" y="32" width="4" height="62" rx="2" fill="#ffffff" opacity=".25"/>`,
    // Soap bar box
    soap: (c, a, l1, l2) => `
      <path d="M26 54 L86 54 L98 62 L98 92 L38 92 L26 84 Z" fill="${shade(c, -0.15)}"/>
      <rect x="26" y="54" width="60" height="38" rx="4" fill="${c}" stroke="${shade(c, -0.2)}" stroke-width="1"/>
      <path d="M86 54 L98 62 L98 92 L86 92 Z" fill="${shade(c, -0.1)}"/>
      <ellipse cx="56" cy="73" rx="24" ry="13" fill="${a}"/>
      ${label(56, 71, 40, l1, l2, a, ink(a), 8.5)}
      <circle cx="80" cy="40" r="6" fill="#ffffff" stroke="${shade(c, -0.1)}"/><circle cx="90" cy="30" r="4" fill="#ffffff" stroke="${shade(c, -0.1)}"/>`,
    // Toothpaste box
    tube: (c, a, l1, l2) => `
      <path d="M20 50 L94 50 L102 56 L102 82 L28 82 L20 76 Z" fill="${shade(c, -0.15)}"/>
      <rect x="20" y="50" width="74" height="32" rx="3" fill="${c}"/>
      <path d="M94 50 L102 56 L102 82 L94 82 Z" fill="${shade(c, -0.1)}"/>
      <rect x="26" y="56" width="50" height="20" rx="4" fill="${a}"/>
      ${label(51, 64, 46, l1, l2, a, ink(a), 8.5)}
      <path d="M80 60 Q86 66 80 72" stroke="${a}" stroke-width="3" fill="none" stroke-linecap="round"/>`,
    // Biscuit ticky pack
    biscuit: (c, a, l1, l2) => `
      <path d="M22 50 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4 l4 -4 l4 4 L98 92 L22 92 Z" fill="${c}"/>
      <circle cx="40" cy="72" r="11" fill="${a}"/><circle cx="40" cy="72" r="7" fill="${shade(a, -0.15)}"/>
      ${label(72, 68, 40, l1, l2, c, ink(c), 9)}`,
  };

  /** SVG markup for a product (by sku); a generic box for anything unknown. */
  function svg(sku, size = 120) {
    const [shape, c, a, l1, l2] = ART[sku] || ["box", "#94a3b8", "#e2e8f0", "PRODUCT", "", "Other"];
    const id = `g${sku.replace(/[^a-z0-9]/gi, "")}`;
    return `<svg viewBox="0 0 120 120" width="${size}" height="${size}" role="img" aria-label="${esc(l1)} ${esc(l2)} package" xmlns="http://www.w3.org/2000/svg">
      <defs><radialGradient id="${id}" cx="50%" cy="40%" r="65%"><stop offset="0" stop-color="${shade(c, 0.42)}" stop-opacity=".35"/><stop offset="1" stop-color="${shade(c, 0.42)}" stop-opacity="0"/></radialGradient></defs>
      <circle cx="60" cy="58" r="54" fill="url(#${id})"/>
      <ellipse cx="60" cy="106" rx="34" ry="5" fill="#0f1b2d" opacity=".12"/>
      ${(SHAPES[shape] || SHAPES.box)(c, a, l1, l2)}
    </svg>`;
  }

  const category = (sku) => (ART[sku] || [])[5] || "Other";

  return { svg, category, CATEGORIES };
})();
