import DOMPurify from 'isomorphic-dompurify';

/**
 * Sanitize Telegram-style HTML for safe rendering with dangerouslySetInnerHTML.
 * Strips <script>, event handlers, <iframe>, <object>, <embed>, <form>, etc.
 * Preserves safe Telegram formatting: <b>, <i>, <s>, <code>, <pre>, <a>, <blockquote>, <br>.
 */
export function sanitizeTelegramHtml(html: string): string {
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      'b', 'strong', 'i', 'em', 's', 'strike', 'del',
      'code', 'pre',
      'a', 'blockquote',
      'br', 'p', 'span', 'div',
      'ul', 'ol', 'li',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    ],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'class', 'style'],
    ALLOW_DATA_ATTR: false,
  });

  // Post-process: add target="_blank" and rel to all links
  return clean.replace(/<a /g, '<a target="_blank" rel="noopener noreferrer" ');
}
