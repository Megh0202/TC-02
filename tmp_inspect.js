(() => {
  const esc = (value) => String(value || "").split("\\").join("\\\\").split("\"").join("\\\"");
  const cssEsc = (value) => String(value || "").split("\\").join("\\\\").split("\"").join("\\\"");
  const selectorsFor = (el, tag, text, aria, name, id, testid, role, placeholder) => {
    const selectors = [];
    if (id) selectors.push(`#${id}`);
    if (testid) selectors.push('[data-testid="' + cssEsc(testid) + '"]');
    if (name && ["input", "textarea", "select"].includes(tag)) selectors.push(tag + '[name="' + cssEsc(name) + '"]');
    if (aria) {
      selectors.push(tag + '[aria-label*="' + cssEsc(aria.slice(0, 60)) + '"]');
      if (role) selectors.push('[role="' + cssEsc(role) + '"][aria-label*="' + cssEsc(aria.slice(0, 60)) + '"]');
    }
    if (placeholder && ["input", "textarea"].includes(tag)) selectors.push(tag + '[placeholder*="' + cssEsc(placeholder.slice(0, 60)) + '"]');
    if (text) {
      const shortText = text.slice(0, 80);
      if (tag === "button" || role === "button") selectors.push((tag === "button" ? "button" : '[role="' + cssEsc(role) + '"]') + ':has-text("' + esc(shortText) + '")');
      else if (tag === "a" || role === "link") selectors.push((tag === "a" ? "a" : '[role="' + cssEsc(role) + '"]') + ':has-text("' + esc(shortText) + '")');
      selectors.push('text=' + shortText);
    }
    return Array.from(new Set(selectors)).slice(0, 6);
  };
  const pick = (elements) => elements
    .map((el) => {
      const text = (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
      const aria = el.getAttribute("aria-label") || "";
      const name = el.getAttribute("name") || "";
      const id = el.getAttribute("id") || "";
      const testid = el.getAttribute("data-testid") || "";
      const role = el.getAttribute("role") || "";
      const placeholder = el.getAttribute("placeholder") || "";
      const href = el.getAttribute("href") || "";
      const inputType = el.getAttribute("type") || "";
      const tag = el.tagName.toLowerCase();
      if (!(text || aria || name || id || testid || placeholder)) return null;
      return {
        tag,
        type: inputType,
        text: text.slice(0, 120),
        aria,
        name,
        id,
        testid,
        role,
        placeholder,
        href: href.slice(0, 120),
        selectors: selectorsFor(el, tag, text, aria, name, id, testid, role, placeholder),
      };
    })
    .filter(Boolean)
    .slice(0, 40);

  const interactive = pick(Array.from(document.querySelectorAll("button, a, input, textarea, select, [role='button'], [role='link'], [role='textbox'], [data-testid]")));
  const textExcerpt = (document.body?.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 3000);
  return {
    url: window.location.href,
    title: document.title || "",
    text_excerpt: textExcerpt,
    interactive_elements: interactive,
  };
})