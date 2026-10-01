# lawbench-assistant-ui

CopilotKit floating-assistant island for the law-bench workbench (change
`add-admin-copilot-assistant`). Builds to a self-mounting IIFE bundle rendered
into `#lawbench-assistant-root` by `base.html` — which includes it **only for
sessions holding the `admin` scope AND only when `COPILOT_RUNTIME_URL` is
configured** (see `src/web/templating.py`).

```sh
npm install
npm run build   # tsc --noEmit && vite build → ../src/web/static/assistant/
```

All chat traffic goes to the same-origin `/copilotkit` route, the admin-gated
proxy in `src/web/routes/copilot.py` — the only public path to the CopilotKit
runtime. Deployment topology and rollback live in
`deploy/cheap-box/README.md` ("Admin assistant topology").

The production image builds this island in its own node stage
(`Dockerfile`, `FROM ... AS assistant-ui`); the committed repo does not carry
the build output.
