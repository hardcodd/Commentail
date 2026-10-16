/* Progressive HTML interactions; the same endpoints work without JavaScript. */
(() => {
  const enhance = (root) => {
    root.querySelectorAll("textarea.commentail-input").forEach((field) => {
      const resize = () => {
        field.style.height = "auto";
        const style = window.getComputedStyle(field);
        // scrollHeight includes padding, while CSS height follows box-sizing.
        const adjustment = style.boxSizing === "border-box"
          ? parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
          : -parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
        field.style.height = `${Math.ceil(field.scrollHeight + adjustment)}px`;
      };
      field.addEventListener("input", resize);
      resize();
    });
    root.querySelectorAll(".commentail-avatar-image").forEach((image) => {
      image.addEventListener("error", () => image.remove());
      if (image.complete && !image.naturalWidth) image.remove();
    });
  };
  // Server forms remain a native fallback; mount only the active reply inline.
  // Its independent main ticket avoids deduplicating a different main comment.
  const mountReply = (block) => {
    const form = block.querySelector(".commentail-form[data-reply-to]");
    if (!form?.dataset?.replyTo) return;
    const target = block.querySelector(`#commentail-${form.dataset.replyTo} .commentail-content`);
    const template = block.querySelector(".commentail-main-template");
    if (!target || !template) return;
    form.before(template.content.firstElementChild.cloneNode(true));
    target.append(form);
    form.classList.add("commentail-reply-form");
    const error = block.querySelector('.commentail-error[role="alert"]:not(.commentail-network-error)');
    if (error) form.prepend(error);
    const network = block.querySelector(".commentail-network-error");
    if (network) form.prepend(network);
  };
  const draft = (block, reply = false) => {
    const values = {};
    const selector = reply ? '.commentail-form[data-reply-to] [name]' : '.commentail-form:not([data-reply-to]) [name]';
    block.querySelectorAll(selector).forEach((field) => {
      if (["text", "name", "email", "subscribe"].includes(field.name)) {
        values[field.name] = field.type === "checkbox" ? field.checked : field.value;
      }
    });
    return values;
  };
  const restoreDraft = (block, values, reply = false) => {
    const selector = reply ? '.commentail-form[data-reply-to] [name]' : '.commentail-form:not([data-reply-to]) [name]';
    block.querySelectorAll(selector).forEach((field) => {
      if (!(field.name in values)) return;
      if (field.type === "checkbox") field.checked = values[field.name];
      else field.value = values[field.name];
    });
  };
  const focusContent = (element) => {
    if (!element) return;
    // Programmatic focus must not add reading targets to the normal Tab order.
    element.setAttribute("tabindex", "-1");
    element.focus();
  };
  const update = async (block, url, { body, focus, keepDraft = false, reply = false } = {}) => {
    if (block.getAttribute("aria-busy") === "true") return;
    const destination = new URL(url, window.location.href);
    if (destination.origin !== window.location.origin) return;
    const previousMessages = new Set([...block.querySelectorAll(".commentail-comment")].map((item) => item.id));
    const previousPrivate = new Set([...block.querySelectorAll(".commentail-pending")].map((item) => item.id));
    block.setAttribute("aria-busy", "true");
    const alert = block.querySelector(".commentail-network-error");
    if (alert) alert.hidden = true;
    const controls = [...block.querySelectorAll('button, input[type="submit"]')];
    const previouslyDisabled = controls.map((button) => button.disabled);
    controls.forEach((button) => { button.disabled = true; });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(destination, {
        method: body ? "POST" : "GET", body,
        credentials: "same-origin", mode: "same-origin", cache: "no-store",
        signal: controller.signal,
      });
      if (![200, 400, 403].includes(response.status)) throw new Error("Unavailable response");
      const html = new DOMParser().parseFromString(await response.text(), "text/html");
      const next = [...html.querySelectorAll(".commentail[data-discussion]")]
        .find((item) => item.dataset.discussion === block.dataset.discussion);
      if (!next) throw new Error("Missing discussion");
      mountReply(next);
      // Preserve drafts during reading/navigation, including typing during the fetch.
      if (keepDraft || reply) restoreDraft(next, draft(block));
      if (keepDraft) {
        const previousReply = draft(block, true);
        const main = draft(block);
        restoreDraft(next, Object.keys(previousReply).length ? previousReply : {
          name: main.name || "", email: main.email || "",
        }, true);
      }
      block.replaceWith(next);
      enhance(next);
      const error = next.querySelector('[role="alert"]:not([hidden])');
      const composer = next.querySelector(".commentail-reply-form");
      const active = composer?.dataset?.replyTo ? composer : next;
      const field = focus && active.querySelector(`.commentail-form [name="${focus}"], [name="${focus}"]`);
      const added = [...next.querySelectorAll(".commentail-comment")].find((item) => !previousMessages.has(item.id));
      const accepted = [...next.querySelectorAll(".commentail-pending")].find((item) => !previousPrivate.has(item.id));
      if (error) focusContent(error);
      else if (body && (accepted || added)) focusContent(accepted || added);
      else if (field) field.focus();
      else focusContent(added || next.querySelector(".commentail-header h2"));
    } catch (_error) {
      // Do not replay a POST: the server may already have accepted it. Its form
      // key stays intact so an explicit retry remains deduplicated server-side.
      if (alert) {
        alert.textContent = block.dataset.networkError;
        alert.hidden = false;
        focusContent(alert);
      }
    } finally {
      clearTimeout(timeout);
      block.removeAttribute("aria-busy");
      controls.forEach((button, index) => { button.disabled = previouslyDisabled[index]; });
    }
  };
  const start = () => {
    if (!window.fetch || !window.DOMParser || !window.AbortController) {
      enhance(document);
      return;
    }
    document.querySelectorAll(".commentail[data-discussion]").forEach(mountReply);
    enhance(document);
    document.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest("a[data-commentail-navigation]");
      const block = link && link.closest(".commentail[data-discussion]");
      if (!block || new URL(link.href).origin !== window.location.origin) return;
      if (block.getAttribute("aria-busy") === "true") {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      if (link.dataset.commentailCancel !== undefined) {
        const form = link.closest(".commentail-reply-form");
        if (form) {
          const trigger = block.querySelector(`[data-commentail-reply="${form.dataset.replyTo}"]`);
          const network = form.querySelector(".commentail-network-error");
          if (network) { network.hidden = true; block.prepend(network); }
          form.remove();
          const current = new URL(window.location.href);
          current.searchParams.delete("reply_to");
          window.history?.replaceState(null, "", current);
          trigger?.focus();
          return;
        }
      }
      const destination = new URL(link.href);
      // POST fragments have no navigation query; cancelled forms leave stale
      // rendered URLs behind. The live composer is the navigation authority.
      if (link.dataset.commentailReply === undefined) {
        const activeReply = block.querySelector(".commentail-form[data-reply-to]");
        if (activeReply?.dataset?.replyTo) {
          destination.searchParams.set("reply_to", activeReply.dataset.replyTo);
          destination.searchParams.set("target", activeReply.dataset.replyTo);
        } else destination.searchParams.delete("reply_to");
      }
      update(block, destination.href, { focus: link.dataset.commentailFocus, keepDraft: true });
    });
    document.addEventListener("submit", (event) => {
      const form = event.target;
      const block = form.matches(".commentail-form") && form.closest(".commentail[data-discussion]");
      if (!block || new URL(form.action).origin !== window.location.origin) return;
      event.preventDefault();
      const body = new FormData(form);
      const button = event.submitter;
      if (button && button.name) body.append(button.name, button.value);
      update(block, form.action, { body, reply: Boolean(form.dataset?.replyTo), focus: button?.name === "refresh" ? "answer" : "text" });
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
