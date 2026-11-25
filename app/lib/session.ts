import type { ChatterMeDTO } from "@/contexts/ChatterContext";
import type { AuthedUserDTO } from "@/contexts/UserContext";

export function isChatterOnly(
  user: AuthedUserDTO | null | undefined,
  chatter: ChatterMeDTO | null | undefined,
): boolean {
  return !user && !!chatter;
}
