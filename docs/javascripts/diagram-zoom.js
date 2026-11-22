// Zoom, pan and full screen for the Mermaid diagrams.
// The theme draws each diagram in an element of class "mermaid". This
// wraps that element in a frame with four buttons, and moves and scales
// it with a CSS transform. Drag to pan.
(function () {
  const STEP = 1.25;

  function frame(diagram) {
    const box = document.createElement("div");
    box.className = "diagram-zoom";
    // The theme has no dark colours for packet diagrams: the stylesheet
    // inverts those. The source is still readable here, before drawing.
    if (/^\s*(---[\s\S]*?---\s*)?packet/.test(diagram.textContent)) box.classList.add("diagram-zoom--packet");
    diagram.replaceWith(box);
    box.append(diagram);

    const state = { scale: 1, x: 0, y: 0 };
    const target = () => box.querySelector(".mermaid");
    const apply = () => {
      const el = target();
      if (el) el.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
    };
    const zoom = (factor) => { state.scale = Math.min(8, Math.max(0.25, state.scale * factor)); apply(); };
    const reset = () => { state.scale = 1; state.x = 0; state.y = 0; apply(); };

    const bar = document.createElement("div");
    bar.className = "diagram-zoom__bar";
    for (const [label, title, action] of [
      ["+", "Zoom in", () => zoom(STEP)],
      ["−", "Zoom out", () => zoom(1 / STEP)],
      ["⟲", "Reset", reset],
      ["⛶", "Full screen", () => (document.fullscreenElement ? document.exitFullscreen() : box.requestFullscreen())],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.title = title;
      button.setAttribute("aria-label", title);
      button.addEventListener("click", action);
      bar.append(button);
    }
    box.prepend(bar);

    let drag = null;
    box.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".diagram-zoom__bar")) return;
      drag = { x: event.clientX - state.x, y: event.clientY - state.y };
      box.setPointerCapture(event.pointerId);
    });
    box.addEventListener("pointermove", (event) => {
      if (!drag) return;
      state.x = event.clientX - drag.x;
      state.y = event.clientY - drag.y;
      apply();
    });
    box.addEventListener("pointerup", () => { drag = null; });
    box.addEventListener("fullscreenchange", reset);
  }

  function scan() {
    for (const diagram of document.querySelectorAll(".mermaid")) {
      if (!diagram.parentElement.classList.contains("diagram-zoom")) frame(diagram);
    }
  }

  new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
  scan();
})();
