"use strict";
(async () => {
  const root = document.getElementById("api-reference");
  try {
    const response = await fetch("/openapi.json");
    if (!response.ok) throw new Error("Could not load the API schema.");
    const schema = await response.json();
    root.replaceChildren();
    for (const [path, methods] of Object.entries(schema.paths)) {
      for (const [method, operation] of Object.entries(methods)) {
        const section = document.createElement("details");
        section.className = "panel";
        const title = document.createElement("summary");
        title.textContent = `${method.toUpperCase()} ${path} — ${operation.summary || ""}`;
        const code = document.createElement("pre");
        code.className = "api-operation";
        code.textContent = JSON.stringify(operation, null, 2);
        section.append(title, code);
        root.append(section);
      }
    }
  } catch (error) { root.textContent = error.message; }
})();
