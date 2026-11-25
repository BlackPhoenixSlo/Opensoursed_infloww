import type { ProxyChoice } from "@/components/setup/creatorFlow";

export type RemoteLoginState = "starting" | "typing" | "challenge" | "otp" | "capturing" | "done" | "error" | "cancelled";

export interface RemoteLoginStatus {
  id: string;
  backend: string;
  state: RemoteLoginState;
  message: string;
  error: string | null;
  account_id: string | null;
  session_file: string | null;
  proxy: ProxyChoice["type"];
  proxy_label: string;
  live_view_url: string | null;
  expires_at: number;
}

export const TERMINAL = new Set(["done", "error", "cancelled"]);
export const STATE_TEXT: Record<string, string> = {
  starting: "Starting the remote browser (about 10 to 20 seconds)…",
  typing: "Entering the email and password on OnlyFans…",
  challenge: "OnlyFans is showing a verification check. Solve it in the live view.",
  otp: "OnlyFans is asking for the 2FA code. Enter it below (or in the live view).",
  capturing: "Signed in. Saving the session…",
};
export const jobPath = (id: string) => `/admin/login/remote/${encodeURIComponent(id)}`;
