'use strict';
// 起動時の配色のちらつきを防ぐため スタイル読み込み前に適用する
(() => {
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference;
  try { preference = localStorage.getItem('deadlock-theme'); } catch {}
  if (!['light', 'dark'].includes(preference)) preference = null;
  const apply = theme => {
    document.documentElement.dataset.theme = theme;
    const button = document.querySelector('#theme-toggle');
    if (!button) return;
    const dark = theme === 'dark';
    const label = dark ? 'ライトモードに切り替え' : 'ダークモードに切り替え';
    button.setAttribute('aria-pressed', String(dark));
    button.setAttribute('aria-label', label);
    button.title = label;
    button.querySelector('span').textContent = dark ? 'ライト' : 'ダーク';
  };
  apply(preference || (system.matches ? 'dark' : 'light'));
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.querySelector('#theme-toggle').addEventListener('click', () => {
      preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('deadlock-theme', preference); } catch {}
      apply(preference);
    });
  });
  system.addEventListener('change', event => {
    if (!preference) apply(event.matches ? 'dark' : 'light');
  });
})();
