// Markdown 渲染工具（供检索命中片段还原显示用，见 SearchView.vue）。
//
// 只引 marked：目标是把「markdown 原文」还原成排版，不做完整文档阅读器
// （不需要目录 / 大纲 / 代码高亮，那些是笔记详情页的事）。
//
// 笔记内容属于**不可信输入**，而这里产出的 HTML 会走 v-html（全项目唯一一处），
// 因此有两道必须自己做的兜底 —— marked 都不管：
//   1. 原始 HTML 一律转义。marked 自 v5 起移除了 sanitize 选项，只能覆写 renderer.html；
//   2. 链接协议白名单。marked 内置的 URL 清洗只做 encodeURI，`javascript:` 原样放行。
import { Marked } from 'marked'

/** 能按 markdown 还原的扩展名；其余一律走纯文本，不走 marked。 */
const MARKDOWN_EXTS = new Set(['md', 'markdown'])

/** 允许出现在 href 里的协议：其余（javascript:、data:、vbscript:…）降级为纯文本。 */
const SAFE_PROTOCOLS = new Set(['http:', 'https:', 'mailto:'])

export function isMarkdownPath(path) {
  const name = String(path ?? '').split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  if (dot < 0) return false
  return MARKDOWN_EXTS.has(name.slice(dot + 1).toLowerCase())
}

function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * 返回可安全放进 href 的地址；不安全返回 ''。
 * 相对地址（#锚点、./a.md、a/b.md）没有协议，交给浏览器按同源解析，放行。
 */
function safeHref(href) {
  const raw = String(href ?? '').trim()
  if (!raw) return ''
  if (raw.startsWith('#')) return raw
  try {
    const url = new URL(raw, 'https://notes-rag.invalid/')
    return SAFE_PROTOCOLS.has(url.protocol) ? raw : ''
  } catch {
    return ''
  }
}

const marked = new Marked({
  gfm: true,
  // 笔记（Obsidian 默认）里单个换行就是换行，而 GFM 会把软换行折叠成空格：
  // 片段本来就短，折叠后语义丢失，所以按笔记的语义来。
  breaks: true,
  renderer: {
    /** 原始 HTML / 内联标签：转义成字面文本，绝不让它变成真实节点。 */
    html({ text }) {
      return escapeHtml(text)
    },
    link(token) {
      const label = token.tokens?.length
        ? this.parser.parseInline(token.tokens)
        : escapeHtml(token.text)
      const href = safeHref(token.href)
      if (!href) return label        // 不安全协议：退化成纯文本，不留可点链接
      const title = token.title ? ` title="${escapeHtml(token.title)}"` : ''
      // 同页锚点 / 相对路径留在本页打开，只有真正的外部地址才新开标签
      const attrs = /^https?:/i.test(href) ? ' target="_blank" rel="noopener noreferrer"' : ''
      return `<a href="${escapeHtml(href)}"${title}${attrs}>${label}</a>`
    },
    /** 片段里不加载图片：相对路径解析不了，外链则只是白送一次网络请求。 */
    image({ text }) {
      return escapeHtml(text)
    },
    /**
     * 代码块：套一层容器，顶部小条放语言标签与「复制」按钮。
     *
     * 代码文本刻意不写进按钮的 data-* 属性（样式门禁禁用属性选择器），
     * 由 AppMarkdown 在点击时从同一容器的 <code> 里现取（事件委托，见该组件）。
     */
    code({ text, lang, escaped }) {
      const body = escaped ? text : escapeHtml(text)
      // infostring 可能是 "js title=foo"，只取第一段当语言名
      const language = String(lang ?? '').trim().split(/\s+/)[0]
      const cls = language ? ` class="language-${escapeHtml(language)}"` : ''
      return (
        '<div class="md-code">' +
        '<div class="md-code__bar">' +
        `<span class="md-code__lang">${language ? escapeHtml(language) : '代码'}</span>` +
        '<button type="button" class="md-copy">复制</button>' +
        '</div>' +
        `<pre><code${cls}>${body}</code></pre>` +
        '</div>'
      )
    },
  },
})

export function renderMarkdown(source) {
  return marked.parse(String(source ?? ''))
}

/**
 * Markdown → 纯文本（朗读用，见 speech.js）。
 *
 * 不引 marked 的 lexer：朗读只需要「把标记去掉」，不需要语法树，一条条正则更直观也更好读。
 * 两处刻意的取舍：
 *  - 代码块**整体略去**而不是保留内容：念出 `const a = () => {}` 全是噪音，
 *    用户想听的是讲解文字；
 *  - 链接/图片只留文字部分（label / alt），URL 不念。
 */
export function toPlainText(source) {
  let text = String(source ?? '')
  text = text.replace(/```[\s\S]*?```/g, ' ')      // 围栏代码块
  text = text.replace(/~~~[\s\S]*?~~~/g, ' ')
  text = text.replace(/`([^`]*)`/g, '$1')          // 行内代码保留文字
  text = text.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
  text = text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  text = text.replace(/^\s{0,3}#{1,6}\s+/gm, '')   // 标题符号
  text = text.replace(/^\s{0,3}>\s?/gm, '')        // 引用
  text = text.replace(/^\s{0,3}([-*_]\s*){3,}$/gm, '') // 分隔线
  text = text.replace(/^\s{0,3}([-*+]|\d+\.)\s+/gm, '') // 列表项
  text = text.replace(/<\/?[a-zA-Z][^>]*>/g, '')   // 原始 HTML 标签
  text = text.replace(/(\*\*|__)(.*?)\1/g, '$2')
  text = text.replace(/(\*|_)(.*?)\1/g, '$2')
  text = text.replace(/~~(.*?)~~/g, '$1')
  text = text.replace(/[ \t]+/g, ' ')
  text = text.replace(/\n{3,}/g, '\n\n')
  return text.trim()
}