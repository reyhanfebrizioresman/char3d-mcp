const paths = {
  script: '<path d="M7 3h8l4 4v14H5V3h2Z"/><path d="M14 3v5h5M8 12h8M8 16h6"/>',
  scene: '<path d="m12 3 9 5-9 5-9-5 9-5ZM3 8v9l9 5 9-5V8M12 13v9"/>',
  user: '<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',
  render:
    '<rect x="3" y="5" width="18" height="15" rx="2"/><path d="m3 9 18-4M7 4l3 4M14 3l3 4m-7 6 5 3-5 3v-6Z"/>',
  gallery:
    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  tools: '<path d="m8 5-6 7 6 7m8-14 6 7-6 7m-3-17-2 20"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10Z"/>',
  queue: '<path d="M4 6h16M4 12h12M4 18h8m4-3 4 3-4 3v-6Z"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  play: '<path d="m9 5 12 7-12 7V5Z"/>',
  spark: '<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7Z"/>',
  settings:
    '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
  shield:
    '<path d="m12 2 8 3v7c0 5-8 10-8 10S4 17 4 12V5l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  bulb: '<path d="M8 17c0-4-3-4-3-8a7 7 0 1 1 14 0c0 4-3 4-3 8M8 17h8M9 21h6"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  refresh:
    '<path d="M20 8a8 8 0 0 0-14-3L3 8m0-6v6h6m-5 8a8 8 0 0 0 14 3l3-3m0 6v-6h-6"/>',
  save: '<path d="M4 3h13l4 4v14H3V3h1ZM7 3v7h10V3M7 21v-7h10v7"/>',
  folder: '<path d="M3 6V3h6l3 3h9v15H3V6Z"/>',
  plus: '<path d="M12 4v16M4 12h16"/>',
  search: '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
  camera:
    '<rect x="3" y="6" width="18" height="15" rx="2"/><path d="m7 6 2-3h6l2 3"/><circle cx="12" cy="13" r="4"/>',
  light: '<path d="m9 3-3 9h6l-3 9 9-12h-6l3-6H9Z"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  check: '<path d="m4 12 5 5L20 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7"/>',
  image:
    '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="2"/><path d="m3 18 6-6 4 4 3-3 5 5"/>',
};
export const icon = (name) =>
  `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.scene}</svg>`;
