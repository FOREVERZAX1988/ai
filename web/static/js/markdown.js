/**
 * Chat Markdown — markdown-it (OpenClaw) + ClawPanel lite fallback.
 * Vendor: OpMarkdown bundle, DOMPurify, highlight.js.
 */
(function (global) {
  'use strict';

  const ALLOWED_TAGS = [
    'a', 'b', 'blockquote', 'br', 'button', 'code', 'del', 'div', 'em', 'h1', 'h2', 'h3', 'h4',
    'hr', 'i', 'input', 'li', 'ol', 'p', 'pre', 's', 'span', 'strong', 'table', 'tbody', 'td',
    'th', 'thead', 'tr', 'ul',
  ];
  const ALLOWED_ATTR = ['target', 'rel', 'class', 'type', 'disabled', 'checked', 'start', 'href', 'data-code'];

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function parseTableRow(line) {
    return String(line || '').trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
  }

  function isDashSepLine(line) {
    const parts = String(line || '').trim().split(/\s+/).filter(Boolean);
    return parts.length >= 2 && parts.every((p) => /^-{3,}:?$/.test(p));
  }

  function parseTwoColHeader(line) {
    const t = String(line || '').trim();
    if (!t || t.includes('|')) return null;
    const m = t.match(/^(\S+)\s+(\S+)$/);
    if (m) return [m[1], m[2]];
    const parts = t.split(/\s{2,}/);
    if (parts.length >= 2) return [parts[0], parts.slice(1).join(' ')];
    return null;
  }

  function repairDashSeparatedTables(markdown) {
    let s = String(markdown);
    s = s.replace(
      /(项目|字段|项|属性)\s+(状态|值|说明|内容)\s+((?:-{3,}\s*)+)\s*/g,
      '\n| $1 | $2 |\n| --- | --- |\n',
    );
    const lines = s.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const hdr = parseTwoColHeader(lines[i]);
      const next = (lines[i + 1] || '').trim();
      if (hdr && isDashSepLine(next)) {
        out.push(`| ${hdr[0]} | ${hdr[1]} |`, '| --- | --- |');
        i += 2;
        while (i < lines.length) {
          const row = parseTwoColHeader(lines[i]);
          if (!row) break;
          out.push(`| ${row[0]} | ${row[1]} |`);
          i += 1;
        }
        continue;
      }
      out.push(lines[i]);
      i += 1;
    }
    return out.join('\n');
  }

  function splitGluedPipeRows(line) {
    let s = String(line || '');
    if (!s.includes('|')) return s;
    s = s.replace(/\|{3,}/g, '|\n|');
    s = s.replace(/\|\|(?=\s*[-:]{3,})/g, '|\n|');
    s = s.replace(/\|\|(?=[^|\s-])/g, '|\n|');
    s = s.replace(/(\|[^|\n]+\|)\s+(?=\|)/g, '$1\n');
    return s;
  }

  function isTableSepLine(line) {
    const t = String(line || '').trim();
    return /^\s*\|[\s\-:|]+\|\s*$/.test(t)
      || /^\s*\|?\s*\-{3,}\s*(\|\s*\-{3,}\s*)+\|?\s*$/.test(t)
      || /^\s*\-{3,}\s*\|\s*\-{3,}\s*$/.test(t);
  }

  function isCompleteTableRow(line) {
    const t = String(line || '').trim();
    return t.startsWith('|') && t.endsWith('|') && parseTableRow(t).length >= 2;
  }

  function isTableBlockStart(lines, index) {
    const line = String(lines[index] || '').trim();
    if (!line.includes('|')) return false;
    return index + 1 < lines.length && isTableSepLine(lines[index + 1]);
  }

  /** Merge multiline / list continuations into the previous table row. */
  function repairFragmentedTableRows(markdown) {
    const lines = String(markdown).split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
      if (!isTableBlockStart(lines, i)) {
        out.push(lines[i]);
        i += 1;
        continue;
      }
      out.push(lines[i], lines[i + 1]);
      i += 2;
      while (i < lines.length) {
        const raw = lines[i];
        const trimmed = raw.trim();
        if (!trimmed) break;
        if (isTableSepLine(trimmed)) {
          out.push(raw);
          i += 1;
          continue;
        }
        if (isTableBlockStart(lines, i)) break;
        if (isCompleteTableRow(trimmed)) {
          out.push(raw);
          i += 1;
          continue;
        }
        if (!trimmed.startsWith('|') && out.length < 3) break;

        let merged = trimmed.startsWith('|') ? trimmed : `| ${trimmed}`;
        i += 1;
        while (i < lines.length) {
          const next = lines[i];
          const nt = next.trim();
          if (!nt) break;
          if (isTableSepLine(nt) || isTableBlockStart(lines, i)) break;
          if (isCompleteTableRow(nt)) break;
          const piece = nt.replace(/^\|\s*/, '').replace(/\|\s*$/, '');
          merged = `${merged.replace(/\|\s*$/, '')}<br>${piece}`;
          i += 1;
          if (nt.endsWith('|')) {
            merged = `${merged} |`;
            break;
          }
        }
        if (!merged.trim().endsWith('|')) merged = `${merged.trim()} |`;
        out.push(merged);
      }
      out.push('');
    }
    return out.join('\n');
  }

  function repairSeparatorLines(markdown) {
    return String(markdown).replace(/^(\s*)\|?(-{3,}:?\s*\|)+-{3,}:?\|?\s*$/gm, (line) => {
      const count = (line.match(/-{3,}/g) || []).length;
      const cols = Math.max(2, count);
      return `| ${Array(cols).fill('---').join(' | ')} |`;
    });
  }

  function looksLikeMarkdownTable(text) {
    return /\|[^|\n]+\|/.test(text) || /^\s*[^|\n]+\s+\|/m.test(text);
  }

  function repairTrailingEmDash(markdown) {
    return String(markdown)
      .replace(/[：:]\s*[—\-―－]{2,}\s*$/gm, ':\n\n<hr>\n')
      .replace(/^\s*[—\-―－]{2,}\s*$/gm, '<hr>\n');
  }

  function promoteChatSectionHeadlines(markdown) {
    const emojiLead = /^(?:[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]|[\uD83C-\uDBFF][\uDC00-\uDFFF])/u;
    return String(markdown).split('\n').map((line) => {
      const t = line.trim();
      if (!t || t.includes('|') || /^#{1,6}\s/.test(t) || /^[-*]\s/.test(t) || /^\d+\.\s/.test(t)) return line;
      if (/^[0-9]{1,2}️⃣\s+\S/.test(t) && t.length <= 120) return `#### ${t}`;
      if (emojiLead.test(t) && t.length <= 48 && !/[。！？.!?]$/.test(t)) return `### ${t}`;
      return line;
    }).join('\n');
  }

  /** OpenClaw-style minimal normalize + op助手 table repairs. */
  function normalizeMarkdownInput(markdown) {
    let s = String(markdown || '').replace(/\r\n/g, '\n');
    if (!s.trim()) return '';

    s = repairTrailingEmDash(s);

    // ###Title — anywhere in the string (###基础状态|...)
    s = s.replace(/(#{1,6})([^\s#\n|])/g, '$1 $2');
    s = s.replace(/([^\n#])\s*(#{1,3}\s+)/g, '$1\n\n$2');
    // ### Section|项目|值| — header glued to table (no space before |)
    s = s.replace(/(#{1,3}\s+)([^|\n]+?)(\|)/g, '$1$2\n\n$3');
    s = s.replace(/^([^|\n#][^|\n]{0,120}?)\s+(\|[^|\n]+\|)/gm, '$1\n\n$2');

    const lines = [];
    for (const line of s.split('\n')) {
      for (const part of splitGluedPipeRows(line).split('\n')) lines.push(part);
    }
    s = lines.join('\n');

    s = repairFragmentedTableRows(s);
    s = repairSeparatorLines(s);
    s = repairDashSeparatedTables(s);
    s = s.replace(/^\s*(-{3,})\s*\|\s*(-{3,})\s*$/gm, '| --- | --- |');
    s = s.replace(/^(#{1,3}\s+[^\n]+)\n(\|)/gm, '$1\n\n$2');
    s = promoteChatSectionHeadlines(s);

    return s;
  }

  function inlineFormat(text) {
    return String(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`([^`\n]+)`/g, (_, code) => `<code>${escapeHtml(code)}</code>`)
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
        const safe = /^https?:|^mailto:/i.test(url.trim()) ? url.trim() : '#';
        return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
      });
  }

  function renderLiteTable(rows) {
    if (!rows || rows.length < 2) return '';
    const parts = ['<div class="md-table-wrap"><table class="md-table">'];
    let headerDone = false;
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i].trim();
      if (!row) continue;
      const isSep = /^\s*\|[\s\-:|]+\|\s*$/.test(row) || /^\s*[\-:]+(\s*\|\s*[\-:]+)+\s*$/.test(row);
      if (isSep) {
        headerDone = true;
        continue;
      }
      let cells = [];
      if (row.startsWith('|') && row.endsWith('|')) cells = row.slice(1, -1).split('|');
      else cells = row.split('|');
      cells = cells.map((c) => inlineFormat(c.trim()));
      if (!cells.length) continue;
      const tag = !headerDone ? 'th' : 'td';
      parts.push('<tr>');
      for (const cell of cells) parts.push(`<${tag}>${cell}</${tag}>`);
      parts.push('</tr>');
      if (!headerDone && i + 1 < rows.length) {
        const next = rows[i + 1].trim();
        if (/^\s*\|[\s\-:|]+\|\s*$/.test(next)) headerDone = true;
      }
    }
    parts.push('</table></div>');
    return parts.join('');
  }

  /** ClawPanel-style fallback when markdown-it is unavailable. */
  function renderLite(markdown) {
    const text = normalizeMarkdownInput(markdown);
    if (!text.trim()) return '';

    let html = text.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const highlighted = highlightCode(code.trimEnd(), lang);
      const langLabel = lang ? `<span class="md-code-lang">${escapeHtml(lang)}</span>` : '';
      const encoded = encodeURIComponent(code.trimEnd());
      return `<div class="md-code-wrap"><div class="md-code-head">${langLabel}<button type="button" class="md-code-copy" data-code="${encoded}">复制</button></div><pre class="md-pre"><code>${highlighted}</code></pre></div>`;
    });

    const lines = html.split('\n');
    const out = [];
    let inList = false;
    let listType = '';
    let tableRows = [];
    let inTable = false;

    function flushTable() {
      if (!tableRows.length) return;
      out.push(renderLiteTable(tableRows));
      tableRows = [];
      inTable = false;
    }

    for (let i = 0; i < lines.length; i++) {
      let line = lines[i];
      if (line.startsWith('<div class="md-code-wrap"')) {
        flushTable();
        if (inList) { out.push(`</${listType}>`); inList = false; }
        out.push(line);
        while (i < lines.length - 1 && !lines[i].includes('</pre></div>')) { i += 1; out.push(lines[i]); }
        continue;
      }

      const isTableRow = /^\s*\|.*\|\s*$/.test(line) || /^\s*[^\|]+\s*\|\s*[^\|]+/.test(line);
      const nextSep = i + 1 < lines.length && (/^\s*\|[\s\-:|]+\|\s*$/.test(lines[i + 1]) || /^\s*[\-:]+(\s*\|\s*[\-:]+)+\s*$/.test(lines[i + 1]));

      if (inTable) {
        if (isTableRow && line.trim()) {
          tableRows.push(line);
          continue;
        }
        flushTable();
      } else if (isTableRow && nextSep) {
        if (inList) { out.push(`</${listType}>`); inList = false; }
        inTable = true;
        tableRows.push(line);
        continue;
      }

      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) {
        flushTable();
        if (inList) { out.push(`</${listType}>`); inList = false; }
        const level = Math.min(4, heading[1].length);
        out.push(`<h${level}>${inlineFormat(heading[2])}</h${level}>`);
        continue;
      }

      const ul = line.match(/^[\s]*[-*]\s+(.+)$/);
      if (ul) {
        flushTable();
        if (!inList || listType !== 'ul') {
          if (inList) out.push(`</${listType}>`);
          out.push('<ul>'); inList = true; listType = 'ul';
        }
        out.push(`<li>${inlineFormat(ul[1])}</li>`);
        continue;
      }

      const ol = line.match(/^[\s]*\d+\.\s+(.+)$/);
      if (ol) {
        flushTable();
        if (!inList || listType !== 'ol') {
          if (inList) out.push(`</${listType}>`);
          out.push('<ol>'); inList = true; listType = 'ol';
        }
        out.push(`<li>${inlineFormat(ol[1])}</li>`);
        continue;
      }

      if (inList) { out.push(`</${listType}>`); inList = false; }
      if (!line.trim()) { out.push(''); continue; }
      if (!line.startsWith('<')) out.push(`<p>${inlineFormat(line)}</p>`);
      else out.push(line);
    }

    if (inList) out.push(`</${listType}>`);
    flushTable();
    return out.join('\n');
  }

  function highlightCode(text, lang) {
    const hljs = global.hljs;
    if (!hljs) return escapeHtml(text);
    try {
      const language = String(lang || '').trim().toLowerCase();
      if (language && hljs.getLanguage(language)) {
        return hljs.highlight(text, { language, ignoreIllegals: true }).value;
      }
      if (!language && text.trim() && hljs.highlightAuto) {
        const result = hljs.highlightAuto(text);
        if (result.relevance >= 2) return result.value;
      }
    } catch (_) { /* ignore */ }
    return escapeHtml(text);
  }

  let mdInstance = null;

  function getMarkdownIt() {
    if (mdInstance) return mdInstance;
    if (!global.OpMarkdown || typeof global.OpMarkdown.createMarkdownIt !== 'function') return null;
    const md = global.OpMarkdown.createMarkdownIt();

    const origTableOpen = md.renderer.rules.table_open || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options));
    md.renderer.rules.table_open = (tokens, idx, options, env, self) => {
      tokens[idx].attrJoin('class', 'md-table');
      return `<div class="md-table-wrap">${origTableOpen(tokens, idx, options, env, self)}`;
    };
    const origTableClose = md.renderer.rules.table_close || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options));
    md.renderer.rules.table_close = (tokens, idx, options, env, self) => `${origTableClose(tokens, idx, options, env, self)}</div>`;

    md.renderer.rules.fence = (tokens, idx) => {
      const token = tokens[idx];
      const lang = token.info ? token.info.trim().split(/\s+/)[0] : '';
      const code = token.content.endsWith('\n') ? token.content.slice(0, -1) : token.content;
      const highlighted = highlightCode(code, lang);
      const hljsClass = highlighted.includes('hljs-') ? 'hljs ' : '';
      const langClass = lang ? `language-${escapeHtml(lang)} ` : '';
      const langLabel = lang ? `<span class="md-code-lang">${escapeHtml(lang)}</span>` : '';
      const encoded = encodeURIComponent(code);
      return `<div class="md-code-wrap">${langLabel || encoded ? `<div class="md-code-head">${langLabel}<button type="button" class="md-code-copy" data-code="${encoded}">复制</button></div>` : ''}<pre class="md-pre"><code class="${hljsClass}${langClass}">${highlighted}</code></pre></div>`;
    };

    const origLinkOpen = md.renderer.rules.link_open || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options));
    md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
      const token = tokens[idx];
      if (token.attrIndex('target') < 0) token.attrPush(['target', '_blank']);
      if (token.attrIndex('rel') < 0) token.attrPush(['rel', 'noopener noreferrer']);
      return origLinkOpen(tokens, idx, options, env, self);
    };

    mdInstance = md;
    return md;
  }

  function sanitizeHtml(html) {
    if (!html) return '';
    const purify = global.DOMPurify;
    if (!purify || typeof purify.sanitize !== 'function') return html;
    return purify.sanitize(html, {
      ALLOWED_TAGS,
      ALLOWED_ATTR,
      ADD_TAGS: ['input'],
    });
  }

  function renderMarkdownHtml(markdown) {
    const input = normalizeMarkdownInput(markdown);
    if (!input.trim()) return '';

    const md = getMarkdownIt();
    if (md) {
      try {
        let html = sanitizeHtml(md.render(input));
        if (looksLikeMarkdownTable(input) && !html.includes('<table')) {
          html = sanitizeHtml(renderLite(input));
        }
        return html;
      } catch (err) {
        console.warn('[markdown] markdown-it failed, using lite renderer:', err);
      }
    }
    return sanitizeHtml(renderLite(input));
  }

  function render(markdown) {
    return renderMarkdownHtml(markdown);
  }

  function renderNormalized(markdown) {
    return renderMarkdownHtml(markdown);
  }

  /** Stream updates re-render the full normalized document (OpenClaw finish + ClawPanel simplicity). */
  function toStreamingHtml(markdown) {
    return renderNormalized(markdown);
  }

  function findStableStreamingMarkdownBoundary(markdown) {
    const input = String(markdown || '');
    return input.length;
  }

  function renderToElement(el, markdown, options) {
    if (!el) return;
    const text = String(markdown || '');
    const streaming = Boolean(options && options.streaming);
    if (!text.trim()) {
      el.textContent = '';
      return;
    }
    el.classList.add('md-content', 'chat-text');
    let html = renderNormalized(text);
    if (streaming && options?.cursor !== false) {
      html += '<span class="md-stream-cursor" aria-hidden="true">▊</span>';
    }
    el.innerHTML = html;
  }

  function bindCopyButtons(root) {
    if (!root || root.dataset.mdCopyBound === '1') return;
    root.dataset.mdCopyBound = '1';
    root.addEventListener('click', (e) => {
      const btn = e.target.closest('.md-code-copy');
      if (!btn) return;
      e.preventDefault();
      let code = '';
      try {
        code = decodeURIComponent(btn.getAttribute('data-code') || '');
      } catch (_) {
        code = btn.getAttribute('data-code') || '';
      }
      if (!code) return;
      const done = () => {
        const prev = btn.textContent;
        btn.textContent = '已复制';
        setTimeout(() => { btn.textContent = prev; }, 1200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(done).catch(() => {});
      }
    });
  }

  global.Markdown = {
    render,
    escapeHtml,
    normalizeMarkdownInput,
    renderToElement,
    toStreamingHtml,
    findStableStreamingMarkdownBoundary,
    bindCopyButtons,
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => bindCopyButtons(document.getElementById('messages')));
    } else {
      bindCopyButtons(document.getElementById('messages'));
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
