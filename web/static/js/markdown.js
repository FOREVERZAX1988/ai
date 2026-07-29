/**

 * Lightweight Markdown → HTML for op助手 chat (offline-safe, no CDN).

 */

(function (global) {

  'use strict';



  function escapeHtml(text) {

    return String(text)

      .replace(/&/g, '&amp;')

      .replace(/</g, '&lt;')

      .replace(/>/g, '&gt;')

      .replace(/"/g, '&quot;');

  }



  function inlineFormat(text) {

    let s = escapeHtml(text);

    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');

    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    return s;

  }



  function isTableRow(line) {

    const t = String(line || '').trim();

    if (!t.includes('|')) return false;

    const cells = parseTableRow(t);

    return cells.length >= 2;

  }



  function isTableSep(line) {

    return /^\s*\|?[\s:|-]+\|[\s|:-]+\|?\s*$/.test(String(line || ''));

  }



  function parseTableRow(line) {

    return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

  }



  function synthesizeTableSep(headerCells) {

    const cols = Math.max(1, headerCells.length);

    return `| ${Array(cols).fill('---').join(' | ')} |`;

  }



  function renderTable(lines) {

    let header = parseTableRow(lines[0]);

    let bodyStart = 1;

    if (lines.length > 1 && isTableSep(lines[1])) {

      bodyStart = 2;

    } else if (lines.length > 1) {

      lines = [lines[0], synthesizeTableSep(header), ...lines.slice(1)];

      bodyStart = 2;

    }

    let html = '<div class="md-table-wrap"><table class="md-table';
    const h0 = (header[0] || '').trim();
    const h1 = (header[1] || '').trim();
    const isKv = header.length === 2
      && /^(项目|字段|项|属性|键)$/i.test(h0)
      && /^(状态|值|说明|内容)$/i.test(h1);
    if (isKv) html += ' md-kv-table';
    html += '"><thead><tr>';

    for (const cell of header) {

      html += `<th>${inlineFormat(cell)}</th>`;

    }

    html += '</tr></thead><tbody>';

    for (let i = bodyStart; i < lines.length; i++) {

      const line = lines[i];

      if (!isTableRow(line)) continue;

      const cells = parseTableRow(line);

      html += '<tr>';

      for (const cell of cells) {

        html += `<td>${inlineFormat(cell)}</td>`;

      }

      html += '</tr>';

    }

    html += '</tbody></table></div>';

    return html;

  }



  function repairKeyValuePipeTables(markdown) {
    const lines = String(markdown).split('\n');
    const out = [];
    let i = 0;

    function isSinglePipeCell(line) {
      const t = String(line || '').trim();
      if (!t.startsWith('|')) return false;
      return parseTableRow(t).length === 1;
    }

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();

      const inlineHdr = trimmed.match(/^(.*?)(?:[：:]\s*)?(项目|字段|项)\s+(状态|值|说明)\s*$/);
      if (inlineHdr && !trimmed.includes('|')) {
        const prefix = inlineHdr[1].trim();
        if (prefix) out.push(prefix);
        out.push(`| ${inlineHdr[2]} | ${inlineHdr[3]} |`);
        out.push('| --- | --- |');
        i += 1;
        continue;
      }

      if (isSinglePipeCell(trimmed)) {
        const block = [];
        let j = i;
        while (j < lines.length && isSinglePipeCell(lines[j])) {
          block.push(lines[j].trim());
          j += 1;
        }
        if (block.length >= 2 && block.length % 2 === 0) {
          const hasHeader = out.length > 0 && out[out.length - 1].includes('|---');
          if (!hasHeader) {
            out.push('| 项目 | 状态 |');
            out.push('| --- | --- |');
          }
          for (let k = 0; k < block.length; k += 2) {
            const key = parseTableRow(block[k])[0] || block[k].replace(/^\|/, '').trim();
            const val = parseTableRow(block[k + 1])[0] || block[k + 1].replace(/^\|/, '').replace(/\|\s*$/, '').trim();
            out.push(`| ${key} | ${val} |`);
          }
          i = j;
          continue;
        }
      }

      out.push(line);
      i += 1;
    }
    return out.join('\n');
  }



  /** Expand models that emit tables/lists on one line (common with tool-heavy replies). */

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

  function parseTwoColRow(line) {
    const t = String(line || '').trim();
    if (!t || t.includes('|') || isDashSepLine(t)) return null;
    const m = t.match(/^(\S+)\s+(.+)$/);
    if (m) return [m[1], m[2]];
    return null;
  }

  function parseMultiTwoColRows(line) {
    const t = String(line || '').trim();
    if (!t || t.includes('|')) return [];
    const rows = [];
    const re = /([\u4e00-\u9fffA-Za-z0-9_/.·]+)\s+([^|\n]+?)(?=\s+[\u4e00-\u9fffA-Za-z0-9_/.·]+\s+|$)/g;
    let m;
    while ((m = re.exec(t)) !== null) {
      rows.push([m[1].trim(), m[2].trim()]);
    }
    if (!rows.length) {
      const one = parseTwoColRow(t);
      if (one) rows.push(one);
    }
    return rows;
  }

  function repairOrphanDashSepLines(markdown) {
    const lines = String(markdown).split('\n');
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      const t = lines[i].trim();
      const prev = out.length ? out[out.length - 1].trim() : '';
      if (/^-{3,}$/.test(t) && isTableRow(prev)) {
        out.push('| --- | --- |');
        while (i + 1 < lines.length && /^-{3,}$/.test(lines[i + 1].trim())) i += 1;
        continue;
      }
      if (/^-{3,}\s*\|\s*-{3,}$/.test(t) || /^\|\s*-{3,}\s*\|\s*-{3,}\s*\|?$/.test(t)) {
        out.push('| --- | --- |');
        continue;
      }
      out.push(lines[i]);
    }
    return out.join('\n');
  }

  function repairMalformedPipeTables(markdown) {
    let s = String(markdown);
    s = s.replace(/^\s*(-{3,})\s*\|\s*(-{3,})\s*$/gm, '| --- | --- |');
    s = s.replace(/^\s*\|\s*(-{3,})\s*\|\s*(-{3,})\s*\|?\s*$/gm, '| --- | --- |');
    s = s.replace(/^([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*$/gm, (m, a, b) => {
      const c1 = a.trim();
      const c2 = b.trim();
      if (/^-{3,}$/.test(c1) || /^-{3,}$/.test(c2)) return m;
      if (!c1 || !c2) return m;
      return `| ${c1} | ${c2} |`;
    });
    return s;
  }

  function repairDashSeparatedTables(markdown) {
    let s = String(markdown);
    s = s.replace(/(\*\*[^*\n]+\*\*)\s+(?=(项目|字段|项)\s+(状态|值|说明))/g, '$1\n\n');
    s = s.replace(
      /(项目|字段|项|属性)\s+(状态|值|说明|内容)\s+((?:-{3,}\s*){2,})\s*/g,
      '\n| $1 | $2 |\n| --- | --- |\n'
    );
    const lines = s.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const hdr = parseTwoColHeader(lines[i]);
      const next = (lines[i + 1] || '').trim();
      if (hdr && isDashSepLine(next)) {
        out.push(`| ${hdr[0]} | ${hdr[1]} |`);
        out.push('| --- | --- |');
        i += 2;
        while (i < lines.length) {
          const multi = parseMultiTwoColRows(lines[i]);
          if (!multi.length) break;
          for (const row of multi) out.push(`| ${row[0]} | ${row[1]} |`);
          i += 1;
        }
        continue;
      }
      if (out.length && out[out.length - 1] === '| --- | --- |') {
        const multi = parseMultiTwoColRows(lines[i]);
        if (multi.length) {
          for (const row of multi) out.push(`| ${row[0]} | ${row[1]} |`);
          i += 1;
          continue;
        }
      }
      out.push(lines[i]);
      i += 1;
    }
    return out.join('\n');
  }

  function promoteSectionHeadings(markdown) {
    const lines = String(markdown).split('\n');
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      const t = lines[i].trim();
      let j = i + 1;
      while (j < lines.length && !lines[j].trim()) j += 1;
      const next = (lines[j] || '').trim();
      const looksLikeSection = t.length >= 2 && t.length <= 32
        && !t.includes('|')
        && !/^[#>\-*`\d]/.test(t)
        && !/[。！？.!?，,]$/.test(t)
        && (next.startsWith('|') || /^(项目|字段|项)\s/.test(next));
      if (looksLikeSection && !t.startsWith('#')) {
        out.push(`### ${t}`);
      } else {
        out.push(lines[i]);
      }
    }
    return out.join('\n');
  }

  function normalizeMarkdownInput(markdown) {

    let s = String(markdown).replace(/\r\n/g, '\n');

    s = promoteSectionHeadings(s);
    s = repairMalformedPipeTables(s);
    s = s.split('\n').map((line) => {
      if (!line.includes('|') && /-{3,}/.test(line) && /(项目|字段|项)\s+(状态|值|说明)/.test(line)) {
        return repairDashSeparatedTables(line);
      }
      return line;
    }).join('\n');
    s = repairDashSeparatedTables(s);
    s = repairOrphanDashSepLines(s);
    s = repairKeyValuePipeTables(s);

    // glued rows in one-line tables: "| a | b | | c | d |"
    // skip lines already inside tables with complete rows
    s = s.split('\n').map((line) => {
      if (!line.includes('|')) return line;
      const cells = parseTableRow(line);
      if (cells.length >= 2) return line;
      return line.replace(/\|\s*\|\s*/g, '|\n|');
    }).join('\n');

    // heading glued to prior text
    s = s.replace(/([^\n#])(#{1,3}\s+)/g, '$1\n$2');

    // list items glued to prior text
    s = s.replace(/([^\n])(\s[-*]\s+)/g, '$1\n$2');
    s = s.replace(/([^\n])(\s\d+\.\s+)/g, '$1\n$2');

    // "## Title | col | col" -> heading + table row
    s = s.replace(/^(#{1,3}\s+[^|\n]+?)\s+(\|.+)$/gm, '$1\n$2');

    s = s.split('\n').map((line) => {
      if (!line.includes('|')) return line;
      const pipeCount = (line.match(/\|/g) || []).length;
      if (pipeCount < 3) return line;
      return line.trim();
    }).join('\n');

    s = s.replace(/([：:])\s*-\s+/g, '$1\n- ');
    s = s.replace(/([^\n])\s+(#{1,3}\s+)/g, '$1\n$2');

    return s;

  }



  function render(markdown) {

    if (!markdown) return '';

    const lines = normalizeMarkdownInput(markdown).split('\n');

    const out = [];

    let i = 0;

    let inCode = false;

    let codeBuf = [];

    let listType = null;



    function flushList() {

      if (!listType) return;

      out.push(listType === 'ol' ? '</ol>' : '</ul>');

      listType = null;

    }



    while (i < lines.length) {

      const line = lines[i];



      if (line.trim().startsWith('```')) {

        flushList();

        if (!inCode) {

          inCode = true;

          codeBuf = [];

        } else {

          inCode = false;

          out.push(`<pre class="md-pre"><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`);

          codeBuf = [];

        }

        i += 1;

        continue;

      }



      if (inCode) {

        codeBuf.push(line);

        i += 1;

        continue;

      }



      if (isTableRow(line)) {

        const tableLines = [line];

        i += 1;

        if (i < lines.length && isTableSep(lines[i])) {

          tableLines.push(lines[i]);

          i += 1;

        }

        while (i < lines.length && isTableRow(lines[i])) {

          tableLines.push(lines[i]);

          i += 1;

        }

        if (tableLines.length >= 2 || (tableLines.length === 1 && tableLines[0].split('|').length > 3)) {

          flushList();

          if (tableLines.length === 1) {

            tableLines.push(synthesizeTableSep(parseTableRow(tableLines[0])));

          }

          out.push(renderTable(tableLines));

          continue;

        }

        i -= tableLines.length - 1;

      }



      const h3 = line.match(/^###\s+(.+)$/);

      const h2 = line.match(/^##\s+(.+)$/);

      const h1 = line.match(/^#\s+(.+)$/);

      if (h3 || h2 || h1) {

        flushList();

        const level = h3 ? 3 : h2 ? 2 : 1;

        const text = (h3 || h2 || h1)[1];

        out.push(`<h${level} class="md-h${level}">${inlineFormat(text)}</h${level}>`);

        i += 1;

        continue;

      }



      const ul = line.match(/^\s*[-*]\s+(.+)$/);

      const ol = line.match(/^\s*\d+\.\s+(.+)$/);

      if (ul || ol) {

        const type = ol ? 'ol' : 'ul';

        const text = (ul || ol)[1];

        if (listType !== type) {

          flushList();

          listType = type;

          out.push(type === 'ol' ? '<ol class="md-list">' : '<ul class="md-list">');

        }

        out.push(`<li>${inlineFormat(text)}</li>`);

        i += 1;

        continue;

      }



      if (line.trim() === '') {

        flushList();

        i += 1;

        continue;

      }



      flushList();

      out.push(`<p>${inlineFormat(line)}</p>`);

      i += 1;

    }



    flushList();

    if (inCode && codeBuf.length) {

      out.push(`<pre class="md-pre"><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`);

    }

    return out.join('\n');

  }



  global.Markdown = { render, escapeHtml, normalizeMarkdownInput };

})(typeof window !== 'undefined' ? window : globalThis);


