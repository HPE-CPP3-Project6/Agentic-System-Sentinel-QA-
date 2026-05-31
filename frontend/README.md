# Sentinel-QA Frontend

React SPA for the Sentinel-QA pipeline — **2 pages**, **6 tabs** inside the workspace.

## Implementation status (12 stages)

| Stage | Status |
|-------|--------|
| 1–5 Foundation + Home + Workspace shell | Complete |
| 6–11 All workspace tabs | Complete |
| 12 Polish (enterprise UI, theme, charts, Shiki) | Complete |

**UI:** Fortify-style navy header + Jenkins-style tables. Light mode default; toggle in top bar.

**Mock data:** Based on real pipeline artifacts (NFR security run).

| Page | Route | Purpose |
|------|-------|---------|
| **Home** | `/` | Story list, create story, bulk upload |
| **Workspace** | `/workspace/:storyId?tab=input&run=r_xxx` | Single pipeline screen with 6 step tabs |

## Workspace tabs (golden path)

1. **Input** — story editor  
2. **Surface Map** — requirement traceability  
3. **Scenarios** — test case table + inline edit  
4. **Scripts** — generated pytest  
5. **Run** — live phase tracker + console  
6. **Report** — quality gate + export  

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — MSW mock API is enabled by default (`VITE_USE_MSW=true`).

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_USE_MSW` | `true` | Mock API via MSW when no backend shim |
| `VITE_API_URL` | *(proxy)* | REST base URL |
| `VITE_WS_URL` | *(same host)* | WebSocket base URL |

When the FastAPI shim is running on port 8000, set `VITE_USE_MSW=false` and use the Vite proxy (configured in `vite.config.ts`).

## Scripts

- `npm run dev` — development server  
- `npm run build` — production build  
- `npm run preview` — preview production build  
