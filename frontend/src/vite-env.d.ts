/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MSW: string;
  readonly VITE_API_URL?: string;
  readonly VITE_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.css" {
  const content: string;
  export default content;
}
