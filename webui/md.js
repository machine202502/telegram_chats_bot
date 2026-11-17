/* Простой и безопасный рендер Markdown в HTML для окна чата. */
(function (global) {
  'use strict';

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
  const SAFE_URL = /^(https?:\/\/|tg:\/\/|mailto:)/i;

  function render(markdown) {
    const src = String(markdown == null ? '' : markdown).replace(/\r\n?/g, '\n');
    const stash = [];
    const put = (html) => '\u0000' + (stash.push(html) - 1) + '\u0000';

    function inline(raw) {
      let t = esc(raw);

      t = t.replace(/`([^`\n]+)`/g, (_m, code) => put('<code class="md-code">' + code + '</code>'));

      t = t.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, title, url) => {
        if (!SAFE_URL.test(url)) return m;
        return put(
          '<a class="md-link" href="' + url + '" target="_blank" rel="noreferrer">' +
            title + '</a>'
        );
      });

      t = t.replace(/\*\*(?=\S)([\s\S]+?)(?<=\S)\*\*/g, '<b>$1</b>');
      t = t.replace(/(?<![\w])__(?=\S)([\s\S]+?)(?<=\S)__(?![\w])/g, '<b>$1</b>');
      t = t.replace(/(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])/g, '<i>$1</i>');
      t = t.replace(/(?<![\w_])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![\w_])/g, '<i>$1</i>');
      t = t.replace(/~~(?=\S)([\s\S]+?)(?<=\S)~~/g, '<s>$1</s>');
      t = t.replace(/\|\|(?=\S)([\s\S]+?)(?<=\S)\|\|/g, '<span class="spoiler" tabindex="0">$1</span>');

      t = t.replace(/(^|[\s(])((?:https?:\/\/|www\.)[^\s<>"']+)/g, (_m, pre, url) => {
        let trail = '';
        const tail = url.match(/[.,;:!?)\]]+$/);
        if (tail) {
          trail = tail[0];
          url = url.slice(0, -trail.length);
        }
        const href = url.indexOf('www.') === 0 ? 'https://' + url : url;
        return (
          pre +
          '<a class="md-link" href="' + href + '" target="_blank" rel="noreferrer">' +
          url + '</a>' + esc(trail)
        );
      });
      return t;
    }

    const prepared = [];
    const lines = src.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const fence = line.trim().match(/^```([^\s`]*)\s*$/);
      if (fence) {
        const lang = fence[1] || '';
        const body = [];
        i += 1;
        while (i < lines.length && lines[i].trim().indexOf('```') !== 0) {
          body.push(lines[i]);
          i += 1;
        }
        prepared.push({ type: 'pre', lang: lang, code: body.join('\n') });
        continue;
      }
      prepared.push({ type: 'line', text: line });
    }

    const out = [];
    let para = [];
    let quote = [];
    let list = null;

    const flushPara = () => {
      if (!para.length) return;
      out.push('<div class="md-p">' + para.map(inline).join('<br>') + '</div>');
      para = [];
    };
    const flushQuote = () => {
      if (!quote.length) return;
      out.push('<blockquote class="md-quote">' + quote.map(inline).join('<br>') + '</blockquote>');
      quote = [];
    };
    const flushList = () => {
      if (!list) return;
      const tag = list.type === 'ol' ? 'ol' : 'ul';
      out.push(
        '<' + tag + ' class="md-list">' +
          list.items.map((item) => '<li>' + inline(item) + '</li>').join('') +
          '</' + tag + '>'
      );
      list = null;
    };
    const flushAll = () => {
      flushPara();
      flushQuote();
      flushList();
    };

    for (const item of prepared) {
      if (item.type === 'pre') {
        flushAll();
        const cls = item.lang ? ' data-lang="' + esc(item.lang) + '"' : '';
        out.push(
          '<div class="md-pre"' + cls + '>' +
            '<button class="md-copy" type="button" title="Скопировать код">⧉</button>' +
            '<pre><code>' + esc(item.code) + '</code></pre>' +
          '</div>'
        );
        continue;
      }

      const line = item.text;
      const trimmed = line.trim();
      if (!trimmed) {
        flushAll();
        continue;
      }

      const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushAll();
        out.push('<div class="md-h md-h' + heading[1].length + '">' + inline(heading[2]) + '</div>');
        continue;
      }
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushAll();
        out.push('<hr class="md-hr">');
        continue;
      }
      if (/^>\s?/.test(trimmed)) {
        flushPara();
        flushList();
        quote.push(trimmed.replace(/^>\s?/, ''));
        continue;
      }
      const ul = line.match(/^\s*[-*+]\s+(.*)$/);
      const ol = line.match(/^\s*\d{1,9}[.)]\s+(.*)$/);
      if (ul || ol) {
        flushPara();
        flushQuote();
        const type = ul ? 'ul' : 'ol';
        if (!list || list.type !== type) {
          flushList();
          list = { type: type, items: [] };
        }
        list.items.push((ul || ol)[1]);
        continue;
      }

      flushQuote();
      flushList();
      para.push(line);
    }
    flushAll();

    return out.join('').replace(/\u0000(\d+)\u0000/g, (_m, idx) => stash[Number(idx)] || '');
  }

  global.MD = { render: render, escape: esc };
})(window);
