/* Local code-native SVG symbols; no external icon or image requests. */
"use strict";
window.gatewayIcon=function(name){
 const paths={
  dashboard:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  playground:'M21 11.5a8 8 0 0 1-8 8H6l-4 3v-11a9 9 0 0 1 19 0Z',
  providers:'m12 3 9 5-9 5-9-5 9-5Z M3 8v9l9 5 9-5V8 M12 13v9',
  cache:'M20 6c0 2-4 3-8 3S4 8 4 6s4-3 8-3 8 1 8 3Z M4 6v6c0 2 4 3 8 3s8-1 8-3V6 M4 12v6c0 2 4 3 8 3s8-1 8-3v-6',
  requests:'M7 5h14 M7 12h14 M7 19h14 M3 5h.01 M3 12h.01 M3 19h.01',
  metrics:'M4 20V11 M10 20V4 M16 20v-7 M22 20H2',
  settings:'m10 3-1 3-3 1-2-1-2 4 2 2v3l-2 2 2 4 3-1 3 1 1 3h4l1-3 3-1 3 1 2-4-2-2v-3l2-2-2-4-3 1-3-1-1-3h-4Z M16 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  admin:'M12 3 3 7v5c0 5 9 10 9 10s9-5 9-10V7l-9-4Z M8 12l3 3 5-6',
  system:'M3 12h4l3-8 4 16 3-8h4',
  menu:'M4 6h16 M4 12h16 M4 18h16',
  refresh:'M20 7v5h-5 M4 17v-5h5 M19 7a8 8 0 0 0-14 0 M5 17a8 8 0 0 0 14 0',
  theme:'M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z',
  logout:'M9 4H4v16h5 M9 12h12 m-5-5 5 5-5 5',
  clock:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 7v5l3 2',
  cost:'M12 2v20 M17 6H9a3 3 0 0 0 0 6h6a3 3 0 0 1 0 6H6',
  github:'M9 19c-5 2-5-3-7-3 M16 22v-4a4 4 0 0 0-1-3c4 0 7-2 7-6a5 5 0 0 0-1-3 4 4 0 0 0 0-4s-2-1-4 2a14 14 0 0 0-7 0C8 1 5 2 5 2a4 4 0 0 0 0 4 5 5 0 0 0-1 3c0 4 3 6 7 6a4 4 0 0 0-1 3v4'
 };
 return `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${paths[name]||paths.providers}"/></svg>`;
};
