/* Простой и безопасный рендер Markdown в HTML для окна чата. */
(function (global) {
  'use strict';

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
  const SAFE_URL = /^(https?:\/\/|tg:\/\/|mailto:)/i;

  const KEYWORDS = {
    sql: new Set(('select from where and or not null is in like between join left right inner outer ' +
      'full on as group by order having limit offset insert into values update set delete create table ' +
      'drop alter add column primary key foreign references unique index view distinct union all case ' +
      'when then else end exists asc desc count sum avg min max coalesce cast return').split(' ')),
    python: new Set(('def class return if elif else for while in not and or is None True False import ' +
      'from as try except finally with lambda pass break continue raise yield global nonlocal assert ' +
      'del async await yield match case').split(' ')),
    js: new Set(('const let var function return if else for while do switch case break continue new ' +
      'class extends super this typeof instanceof in of try catch finally throw async await import ' +
      'export from default null undefined true false').split(' ')),
    ts: new Set(('const let var function return if else for while switch case break continue new class ' +
      'extends implements interface type enum public private protected readonly async await import ' +
      'export from default null undefined true false as satisfies').split(' ')),
    json: new Set(('true false null').split(' ')),
    bash: new Set(('if then else elif fi for while do done case esac function in return exit echo cd ' +
      'export source alias sudo docker compose git npm pnpm yarn python pip').split(' ')),
    css: new Set(('important media supports keyframes from to').split(' ')),
    generic: new Set(('true false null none undefined return if else for while function class const ' +
      'let var new import export').split(' ')),
  };

  function highlight(code, language) {
    const lang = String(language || '').toLowerCase().split(/\s+/)[0];
    const key = ({ py: 'python', python3: 'python', js: 'js', javascript: 'js', ts: 'ts',
      typescript: 'ts', sh: 'bash', shell: 'bash', zsh: 'bash', console: 'bash',
      postgres: 'sql', postgresql: 'sql', mysql: 'sql', sqlite: 'sql' })[lang] || lang;
    const words = KEYWORDS[key] || KEYWORDS.generic;
    const lineComment = key === 'sql' ? '--' : (key === 'python' || key === 'bash' || key === 'yaml') ? '#' : '//';
    const blockComment = key === 'html' ? ['<!--', '-->'] : ['/*', '*/'];
    const src = String(code == null ? '' : code);
    let html = '';
    let i = 0;

    const span = (cls, text) => '<span class="tok-' + cls + '">' + esc(text) + '</span>';

    while (i < src.length) {
      const rest = src.slice(i);
      if (rest.startsWith(lineComment)) {
        const end = rest.indexOf('\n');
        const text = end === -1 ? rest : rest.slice(0, end);
        html += span('com', text);
        i += text.length;
        continue;
      }
      if (rest.startsWith(blockComment[0])) {
        const end = rest.indexOf(blockComment[1], blockComment[0].length);
        const text = end === -1 ? rest : rest.slice(0, end + blockComment[1].length);
        html += span('com', text);
        i += text.length;
        continue;
      }
      const ch = src[i];
      if (ch === '"' || ch === "'" || ch === '`') {
        let j = i + 1;
        while (j < src.length) {
          if (src[j] === '\\') { j += 2; continue; }
          if (src[j] === ch) { j += 1; break; }
          if (ch !== '`' && src[j] === '\n') break;
          j += 1;
        }
        html += span('str', src.slice(i, j));
        i = j;
        continue;
      }
      if (/[0-9]/.test(ch) && (i === 0 || /[\s([{,:=+\-*/<>!&|]/.test(src[i - 1]))) {
        let j = i + 1;
        while (j < src.length && /[0-9a-fA-FxX._]/.test(src[j])) j += 1;
        html += span('num', src.slice(i, j));
        i = j;
        continue;
      }
      if (/[A-Za-z_$@]/.test(ch)) {
        let j = i + 1;
        while (j < src.length && /[A-Za-z0-9_$]/.test(src[j])) j += 1;
        const word = src.slice(i, j);
        const lower = word.toLowerCase();
        let k = j;
        while (k < src.length && /\s/.test(src[k])) k += 1;
        if (words.has(lower) || words.has(word)) {
          html += span('kw', word);
        } else if (src[k] === '(') {
          html += span('fn', word);
        } else {
          html += esc(word);
        }
        i = j;
        continue;
      }
      html += esc(ch);
      i += 1;
    }
    return html;
  }

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
    let details = null;
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
    const flushDetails = () => {
      if (!details || !details.length) { details = null; return; }
      out.push(
        '<blockquote class="md-quote md-quote-expandable">' +
          '<div class="md-quote-clip">' + details.map(inline).join('<br>') + '</div>' +
          '<button class="md-quote-toggle" type="button" aria-expanded="false" title="Развернуть">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
              '<path d="M6 9l6 6 6-6"></path></svg>' +
          '</button>' +
        '</blockquote>'
      );
      details = null;
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
      flushDetails();
      flushList();
    };

    for (const item of prepared) {
      if (item.type === 'pre') {
        flushAll();
        const cls = item.lang ? ' data-lang="' + esc(item.lang) + '"' : '';
        out.push(
          '<div class="md-pre"' + cls + '>' +
            '<button class="md-copy" type="button" title="Скопировать код">⧉</button>' +
            '<pre><code>' + highlight(item.code, item.lang) + '</code></pre>' +
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
      const expandable = trimmed.match(/^>!\s?(.*)$/);
      if (expandable) {
        flushPara();
        flushQuote();
        flushList();
        if (!details) details = [];
        details.push(expandable[1]);
        continue;
      }
      if (/^>\s?/.test(trimmed)) {
        flushPara();
        flushList();
        flushDetails();
        quote.push(trimmed.replace(/^>\s?/, ''));
        continue;
      }
      const ul = line.match(/^\s*[-*+]\s+(.*)$/);
      const ol = line.match(/^\s*\d{1,9}[.)]\s+(.*)$/);
      if (ul || ol) {
        flushPara();
        flushQuote();
        flushDetails();
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
      flushDetails();
      para.push(line);
    }
    flushAll();

    return out.join('').replace(/\u0000(\d+)\u0000/g, (_m, idx) => stash[Number(idx)] || '');
  }

  global.MD = { render: render, escape: esc };
})(window);
