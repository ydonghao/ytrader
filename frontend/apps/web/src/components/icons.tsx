/**
 * Shared inline SVG icon set.
 * Unified style: 16×16 viewBox, strokeWidth 1.5, stroke=currentColor, fill=none.
 * Keep additions to this file — never reach for emoji/unicode glyphs.
 */
import React from 'react';

type SvgProps = React.SVGProps<SVGSVGElement>;

const base: SvgProps = {
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
};

export const Icons = {
  /* ── Navigation (mirrors Layout.tsx nav) ── */
  dashboard: (<svg {...base}><rect x="1" y="1" width="6" height="6" rx="1" /><rect x="9" y="1" width="6" height="6" rx="1" /><rect x="1" y="9" width="6" height="6" rx="1" /><rect x="9" y="9" width="6" height="6" rx="1" /></svg>),
  market: (<svg {...base}><polyline points="1,12 5,6 8,9 15,2" /><polyline points="11,2 15,2 15,6" /></svg>),
  trading: (<svg {...base}><path d="M2 14h12M4 10V6M8 10V3M12 10V5" /></svg>),
  strategies: (<svg {...base}><polygon points="8,1 15,14 1,14" /></svg>),
  portfolio: (<svg {...base}><rect x="1" y="3" width="14" height="10" rx="2" /><path d="M1 7h14" /></svg>),
  analytics: (<svg {...base}><circle cx="8" cy="8" r="6" /><path d="M8 2v6l4 2" /></svg>),
  backtest: (<svg {...base}><path d="M3 8h10M9 4l4 4-4 4" /></svg>),
  risk: (<svg {...base}><path d="M8 1L1 14h14L8 1z" /><line x1="8" y1="6" x2="8" y2="10" /><circle cx="8" cy="12" r="0.5" fill="currentColor" /></svg>),
  reports: (<svg {...base}><path d="M4 1h6l4 4v9a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" /><polyline points="10,1 10,5 14,5" /></svg>),
  financial: (<svg {...base}><rect x="1" y="2" width="14" height="12" rx="1" /><line x1="1" y1="6" x2="15" y2="6" /><line x1="5" y1="6" x2="5" y2="14" /><line x1="10" y1="6" x2="10" y2="14" /></svg>),
  intel: (<svg {...base}><path d="M2 12a6 6 0 0012 0" /><line x1="8" y1="2" x2="8" y2="8" /><circle cx="8" cy="1.5" r="1" /></svg>),
  alerts: (<svg {...base}><path d="M8 1a5 5 0 015 5v3l1 2H2l1-2V6a5 5 0 015-5z" /><path d="M6 13a2 2 0 004 0" /></svg>),
  settings: (<svg {...base}><circle cx="8" cy="8" r="2.5" /><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" /></svg>),

  /* ── UI primitives ── */
  chevronDown: (<svg {...base}><polyline points="4,6 8,10 12,6" /></svg>),
  chevronRight: (<svg {...base}><polyline points="6,4 10,8 6,12" /></svg>),
  collapse: (<svg {...base}><line x1="3" y1="2" x2="13" y2="2" /><line x1="3" y1="14" x2="13" y2="14" /><polyline points="10,6 8,8 6,6" /><line x1="8" y1="8" x2="8" y2="2" /></svg>),
  expand: (<svg {...base}><line x1="3" y1="2" x2="13" y2="2" /><line x1="3" y1="14" x2="13" y2="14" /><polyline points="6,10 8,8 10,10" /><line x1="8" y1="8" x2="8" y2="14" /></svg>),
  plus: (<svg {...base}><line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" /></svg>),
  refresh: (<svg {...base}><path d="M13 6a5 5 0 10-1 5.5" /><polyline points="13,2 13,6 9,6" /></svg>),
  star: (<svg {...base}><polygon points="8,1.5 10,5.8 14.5,6.3 11,9.5 12,14 8,11.7 4,14 5,9.5 1.5,6.3 6,5.8" fill="currentColor" stroke="none" /></svg>),

  /* ── Domain (Settings / Intel) ── */
  cpu: (<svg {...base}><rect x="4" y="4" width="8" height="8" rx="1" /><rect x="6.5" y="6.5" width="3" height="3" /><path d="M6 1v2M10 1v2M6 13v2M10 13v2M1 6h2M1 10h2M13 6h2M13 10h2" /></svg>),
  terminal: (<svg {...base}><rect x="1" y="2" width="14" height="12" rx="1" /><polyline points="4,6 6,8 4,10" /><line x1="8" y1="10" x2="12" y2="10" /></svg>),
  bell: (<svg {...base}><path d="M8 1.5a4.5 4.5 0 014.5 4.5v2.5l1 2H2.5l1-2V6A4.5 4.5 0 018 1.5z" /><path d="M6 12.5a2 2 0 004 0" /></svg>),
  flask: (<svg {...base}><path d="M6 1h4M6.5 1v4.5L2.8 12A1.5 1.5 0 004 14.5h8A1.5 1.5 0 0013.2 12L9.5 5.5V1" /><line x1="4.5" y1="9" x2="11.5" y2="9" /></svg>),
  globe: (<svg {...base}><circle cx="8" cy="8" r="6" /><path d="M2 8h12M8 2c2 2 2 10 0 12M8 2c-2 2-2 10 0 12" /></svg>),
  link: (<svg {...base}><path d="M7 9l-2 2a2 2 0 11-3-3l2-2a2 2 0 013 0" /><path d="M9 7l2-2a2 2 0 113 3l-2 2a2 2 0 01-3 0" /></svg>),
};

export type IconName = keyof typeof Icons;
