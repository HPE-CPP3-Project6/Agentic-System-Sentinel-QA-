import { ApiErrorSchema } from "./types";

export class ApiError extends Error {
  code: string;
  detail?: Record<string, unknown>;

  constructor(code: string, message: string, detail?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail;
  }
}

const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const parsed = ApiErrorSchema.safeParse(body);
    if (parsed.success) {
      const { code, message, detail } = parsed.data.error;
      return new ApiError(code, message, detail);
    }
  } catch {
    // fall through
  }
  return new ApiError("unknown", res.statusText || "Request failed");
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    throw await parseError(res);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }

  return (await res.text()) as T;
}

export function wsUrl(path: string): string {
  const base = import.meta.env.VITE_WS_URL;
  if (base) return `${base}${path}`;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
