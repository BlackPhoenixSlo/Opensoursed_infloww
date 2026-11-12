/** Client mirror of service/bio_pages/decide.py; the API remains authoritative. */
export interface FormError { msg: string; fields: string[] }
export const chars = (s: string) => [...s].length;
export const IMAGE_ACCEPT = "image/jpeg,image/png,image/gif,image/webp";
export const MAX_DISPLAY_NAME = 100;
export const MAX_BIO = 500;
export const MAX_TITLE = 200;
export const MAX_DESTINATION = 2000;
export const USERNAME_MSG = "Username: 3-30 lowercase letters, digits or _.";
export const RESERVED_MSG = "That username is reserved.";
export const NAME_MSG = "Enter a display name.";
export const TITLE_MSG = "Enter a title.";
export const DEST_EMPTY_MSG = "Enter a Destination after https://.";
export const DEST_MSG = "Destination: start with https://, http:// or /; no spaces or backslashes.";
export const CODE_MSG = "Default Tracking Code: digits only, or leave it empty.";
export const USERNAME = /^[a-z0-9_]{3,30}$/;
export const RESERVED = ["api", "edit", "images", "internal", "netlify"];
// PB 0002 with Go RE2 whitespace semantics, as decide.DESTINATION.
export const DESTINATION = /^(?:https?:\/\/[^\t\n\f\r \\/]|\/[^\t\n\f\r \\/])[^\t\n\f\r \\]*$/;
export const CODE = /^[0-9]{0,12}$/;
