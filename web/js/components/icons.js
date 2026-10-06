// 아웃라인 아이콘 (stroke = currentColor)
const svg = (body, size = 24) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

export const icons = {
  home: svg('<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z"/>'),
  list: svg('<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M9 15v-3M12 15V9M15 15v-5"/>'),
  wallet: svg('<path d="M4 7.5A2.5 2.5 0 0 1 6.5 5H17a2 2 0 0 1 2 2v1"/><rect x="4" y="8" width="16" height="11" rx="3"/><path d="M16 13.5h.01"/>'),
  refresh: svg('<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20v-4h-4"/>', 18),
  star: svg('<path d="m12 3.8 2.5 5.1 5.6.8-4 4 1 5.6-5.1-2.7-5.1 2.7 1-5.6-4-4 5.6-.8z"/>', 20),
  starFilled: `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="m12 3.8 2.5 5.1 5.6.8-4 4 1 5.6-5.1-2.7-5.1 2.7 1-5.6-4-4 5.6-.8z"/></svg>`,
  search: svg('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4"/>', 18),
  close: svg('<path d="M6 6l12 12M18 6 6 18"/>', 20),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 18),
  alert: svg('<path d="M12 8v5M12 16.5h.01"/><circle cx="12" cy="12" r="9"/>', 22),
  inbox: svg('<path d="M4 13h4l1.5 2.5h5L16 13h4"/><path d="M5.5 6h13L20 13v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5z"/>', 22),
};
