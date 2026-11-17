/* Локализация интерфейса. Сейчас поддерживается только русский. */
(function (global) {
  'use strict';
  const data = global.__I18N__ || {};
  const locale = (document.documentElement.lang || 'ru').slice(0, 2);

  function lookup(key) {
    if (Object.prototype.hasOwnProperty.call(data, key)) return data[key];
    return key;
  }

  function format(template, params) {
    if (!params) return template;
    return String(template).replace(/\{(\w+)\}/g, (_match, name) =>
      Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : '{' + name + '}');
  }

  function t(key, params) {
    return format(lookup(key), params);
  }

  function apply(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-i18n]').forEach((element) => {
      const key = element.getAttribute('data-i18n');
      if (!key) return;
      const value = lookup(key);
      if (value !== key) element.textContent = value;
    });
    [
      ['data-i18n-placeholder', 'placeholder'],
      ['data-i18n-title', 'title'],
      ['data-i18n-aria', 'aria-label'],
      ['data-i18n-alt', 'alt'],
    ].forEach(([attribute, target]) => {
      scope.querySelectorAll('[' + attribute + ']').forEach((element) => {
        const key = element.getAttribute(attribute);
        if (!key) return;
        const value = lookup(key);
        if (value !== key) element.setAttribute(target, value);
      });
    });
  }

  global.t = t;
  global.I18N = { t, apply, locale, data };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => apply(document));
  } else {
    apply(document);
  }
})(window);
