/* Facebook group / public post pages, or a Zalo-web-like feed — visible post TEXT, permalink, timestamp text.
 * Never returns names, profile links, avatars or phones (phones become phone_hash). Only posts already rendered
 * on screen are read; scrolling is the human's job. Read-only. */
const SITE = /facebook/.test(location.hostname) ? 'facebook' : (/zalo/.test(location.hostname) ? 'zalo' : (location.hostname || 'social').replace(/^www\./, ''));
const items = [];
const seen = {};
const posts = $all('div[role="article"], [data-pagelet^="FeedUnit"], .chat-message, .message-item');
for (const p of posts) {
  if (p.parentElement && p.parentElement.closest('div[role="article"]')) continue; // comments inside a post
  const msg = $1('div[data-ad-preview="message"], div[data-ad-comet-preview="message"]', p) || p;
  const text = cleanText(msg.innerText);
  if (!text || text.length < 20) continue;
  let permalink = null, timeText = null;
  for (const a of $all('a[href]', p)) {
    const h = a.href || '';
    if (/\/posts\/|\/permalink\/|story_fbid=|\/groups\/[^/]+\/posts\//.test(h)) {
      permalink = h.split('?')[0].split('&__')[0];
      timeText = cleanText(a.getAttribute('aria-label')) || txt(a);
      break;
    }
  }
  const key = permalink || sha1(text.slice(0, 200));
  if (seen[key]) continue;
  seen[key] = true;
  const hs = phoneHashesIn(text);
  items.push({ text: stripPhones(text).slice(0, 4000), permalink: permalink, time_text: timeText,
    post_id: permalink ? siteIdFromUrl(permalink, 'facebook') : null, phone_hash: hs[0] || null });
}
return envelope(SITE, 'social', items, items.length ? [] : ['no posts visible']);
