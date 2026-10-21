import type { ChatterMeDTO } from "@/contexts/ChatterContext";
import type { AuthedUserDTO } from "@/contexts/UserContext";

/** A chatter signed in with no User cookie. The User principal wins when both
 *  are present, matching the relay's admin gate (which 403s chatters). */
export function isChatterOnly(
  user: AuthedUserDTO | null | undefined,
  chatter: ChatterMeDTO | null | undefined,
): boolean {
  return !user && !!chatter;
}
