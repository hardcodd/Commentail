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
  const mountEditor = (block) => {
    const editor = block.querySelector(".commentail-edit-form");
    const network = block.querySelector(".commentail-network-error");
    if (editor?.dataset?.editComment && network) editor.prepend(network);
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
  const mountPendingReplies = (block) => {
    block.querySelectorAll(".commentail-pending").forEach((item) => {
      const identifier = item.id?.replace("commentail-private-", "");
      const target = (identifier && block.querySelector(`#commentail-${identifier} .commentail-content`))
        || (item.dataset?.replyTo && block.querySelector(`#commentail-${item.dataset.replyTo} .commentail-content`));
      if (target) target.append(item);
    });
  };
  const reveal = (element) => {
    element.focus({ preventScroll: true });
    const rect = element.getBoundingClientRect();
    if (rect.top < 16 || rect.bottom > window.innerHeight - 16) {
      element.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
    }
  };
  const focusContent = (element) => {
    if (!element) return;
    // Programmatic focus must not add reading targets to the normal Tab order.
    element.setAttribute("tabindex", "-1");
    reveal(element);
  };
  // Replacing a widget must not reset the reader's position in the host page.
  const viewportAnchor = (block, preferred) => {
    const element = preferred?.id ? preferred : [...block.querySelectorAll(".commentail-comment")]
      .find((item) => item.getBoundingClientRect().bottom > 0);
    return element ? { id: element.id, top: element.getBoundingClientRect().top } : null;
  };
  const restorePosition = (block, anchor) => {
    const element = anchor && block.querySelector(`#${anchor.id}`);
    if (element) window.scrollBy({ top: element.getBoundingClientRect().top - anchor.top, behavior: "instant" });
  };
  const update = async (block, url, { body, focus, keepDraft = false, reply = false, editing = false, editFocus = false, anchor } = {}) => {
    if (block.getAttribute("aria-busy") === "true") return;
    const destination = new URL(url, window.location.href);
    if (destination.origin !== window.location.origin) return;
    if (body) {
      const activeReply = block.querySelector(".commentail-form[data-reply-to]");
      if (editing && activeReply?.dataset?.replyTo) destination.searchParams.set("reply_to", activeReply.dataset.replyTo);
      const activeEdit = block.querySelector(".commentail-edit-form");
      if (!editing && activeEdit?.dataset?.editComment) destination.searchParams.set("edit_comment", activeEdit.dataset.editComment);
    }
    // Carry each open thread's signed window through GETs and POST redirects.
    if (!destination.searchParams.has("window") && block.dataset.window) {
      destination.searchParams.set("window", block.dataset.window);
    }
    const threads = new Set(destination.searchParams.getAll("thread"));
    const windows = new Set(destination.searchParams.getAll("replies"));
    const requestedThread = destination.searchParams.get("thread");
    block.querySelectorAll(".commentail-replies[data-open]").forEach((item) => {
      threads.add(item.dataset.thread);
      if (item.dataset.window && item.dataset.thread !== requestedThread) windows.add(item.dataset.window);
    });
    destination.searchParams.delete("thread");
    destination.searchParams.delete("replies");
    threads.forEach((value) => destination.searchParams.append("thread", value));
    windows.forEach((value) => destination.searchParams.append("replies", value));
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
      mountPendingReplies(next);
      mountReply(next);
      mountEditor(next);
      const previousEditor = block.querySelector(".commentail-edit-form");
      const nextEditor = next.querySelector(".commentail-edit-form");
      if (!editing && previousEditor?.dataset?.editComment && previousEditor.dataset.editComment === nextEditor?.dataset?.editComment) {
        nextEditor.querySelector('[name="text"]').value = previousEditor.querySelector('[name="text"]').value;
      }
      // Preserve independent drafts, including typing during the fetch.
      if (keepDraft || reply || editing) restoreDraft(next, draft(block));
      if (keepDraft) {
        const previousReply = draft(block, true);
        const main = draft(block);
        restoreDraft(next, Object.keys(previousReply).length ? previousReply : {
          name: main.name || "", email: main.email || "",
        }, true);
      }
      const position = viewportAnchor(block, anchor);
      block.replaceWith(next);
      enhance(next);
      restorePosition(next, position);
      const error = next.querySelector('[role="alert"]:not([hidden])');
      const composer = next.querySelector(".commentail-reply-form");
      const active = (editing || editFocus) && nextEditor?.dataset?.editComment
        ? nextEditor : composer?.dataset?.replyTo ? composer : next;
      const field = focus && active.querySelector(`.commentail-form [name="${focus}"], [name="${focus}"]`);
      const added = [...next.querySelectorAll(".commentail-comment")].find((item) => !previousMessages.has(item.id));
      const accepted = [...next.querySelectorAll(".commentail-pending")].find((item) => !previousPrivate.has(item.id));
      const result = new URL(response.url || destination, window.location.href);
      const targetURL = body ? result : destination;
      const rawIdentifier = targetURL.hash.match(/^#commentail-(\d+)$/)?.[1] || (body ? targetURL.searchParams.get("target") : null);
      const identifier = /^\d+$/.test(rawIdentifier || "") ? rawIdentifier : null;
      const exact = identifier && (next.querySelector(`#commentail-${identifier}`) || next.querySelector(`#commentail-private-${identifier}`));
      const submitted = exact || accepted || added;
      const notice = next.querySelector(".commentail-mail-notice");
      if (body && submitted && notice) (submitted.querySelector(".commentail-content") || submitted).append(notice);
      if (editing && response.status === 200 && !nextEditor) {
        const current = new URL(window.location.href);
        current.searchParams.delete("edit_comment");
        current.searchParams.delete("commentail_draft");
        window.history?.replaceState(null, "", current);
      }
      if (error) focusContent(error);
      else if (body && submitted) focusContent(submitted);
      else if (field) reveal(field);
      else if (exact) focusContent(exact);
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
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const menu = event.target.closest("details.commentail-menu[open]");
      if (!menu) return;
      event.preventDefault();
      menu.removeAttribute("open");
      reveal(menu.querySelector("summary"));
    });
    if (!window.fetch || !window.DOMParser || !window.AbortController) {
      enhance(document);
      return;
    }
    document.querySelectorAll(".commentail[data-discussion]").forEach((block) => {
      mountPendingReplies(block);
      mountReply(block);
      mountEditor(block);
    });
    enhance(document);
    document.addEventListener("click", (event) => {
      document.querySelectorAll("details.commentail-menu[open]").forEach((menu) => {
        if (!menu.contains(event.target)) menu.removeAttribute("open");
      });
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest("a[data-commentail-navigation]");
      const block = link && link.closest(".commentail[data-discussion]");
      if (!block || new URL(link.href).origin !== window.location.origin) return;
      if (block.getAttribute("aria-busy") === "true") {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      if (link.dataset.commentailEditCancel !== undefined) {
        const editor = link.closest(".commentail-editor");
        const article = link.closest(".commentail-comment");
        if (editor && article) {
          const trigger = block.querySelector(`[data-commentail-edit="${article.id.replace("commentail-", "")}"]`);
          const network = editor.querySelector?.(".commentail-network-error");
          if (network) { network.hidden = true; block.prepend(network); }
          const position = viewportAnchor(block, article);
          editor.remove();
          restorePosition(block, position);
          const current = new URL(window.location.href);
          current.searchParams.delete("edit_comment");
          current.searchParams.delete("commentail_draft");
          window.history?.replaceState(null, "", current);
          const summary = trigger?.closest?.("details.commentail-menu")?.querySelector("summary");
          if (summary || trigger) reveal(summary || trigger);
          return;
        }
      }
      if (link.dataset.commentailCancel !== undefined) {
        const form = link.closest(".commentail-reply-form");
        if (form) {
          const trigger = block.querySelector(`[data-commentail-reply="${form.dataset.replyTo}"]`);
          const network = form.querySelector(".commentail-network-error");
          if (network) { network.hidden = true; block.prepend(network); }
          const position = viewportAnchor(block, form.closest(".commentail-comment"));
          form.remove();
          restorePosition(block, position);
          const current = new URL(window.location.href);
          current.searchParams.delete("reply_to");
          window.history?.replaceState(null, "", current);
          if (trigger) reveal(trigger);
          return;
        }
      }
      const destination = new URL(link.href);
      if (link.dataset.commentailEdit === undefined) {
        const editor = block.querySelector(".commentail-edit-form");
        if (editor?.dataset?.editComment) destination.searchParams.set("edit_comment", editor.dataset.editComment);
        else destination.searchParams.delete("edit_comment");
      }
      // POST fragments have no navigation query; cancelled forms leave stale
      // rendered URLs behind. The live composer is the navigation authority.
      if (link.dataset.commentailReply === undefined) {
        const activeReply = block.querySelector(".commentail-form[data-reply-to]");
        if (activeReply?.dataset?.replyTo) {
          destination.searchParams.set("reply_to", activeReply.dataset.replyTo);
          destination.searchParams.set("target", activeReply.dataset.replyTo);
        } else destination.searchParams.delete("reply_to");
      }
      update(block, destination.href, { focus: link.dataset.commentailFocus, editFocus: link.dataset.commentailEdit !== undefined, keepDraft: true, anchor: link.closest(".commentail-comment") });
    });
    document.addEventListener("submit", (event) => {
      const form = event.target;
      const block = form.matches(".commentail-form, .commentail-edit-form") && form.closest(".commentail[data-discussion]");
      if (!block || new URL(form.action).origin !== window.location.origin) return;
      event.preventDefault();
      const body = new FormData(form);
      const button = event.submitter;
      if (button && button.name) body.append(button.name, button.value);
      update(block, form.action, { body, editing: Boolean(form.dataset?.editComment), keepDraft: Boolean(form.dataset?.editComment), reply: Boolean(form.dataset?.replyTo), anchor: form.closest(".commentail-comment"), focus: button?.name === "refresh" ? "answer" : "text" });
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
