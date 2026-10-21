/** qrcode-svg 1.1.0's API, the part ofMirrorQr uses (see qrcode-svg.js). */
export interface QRCodeOptions {
  content: string;
  padding?: number;
  width?: number;
  height?: number;
  color?: string;
  background?: string;
  ecl?: "L" | "M" | "H" | "Q";
  join?: boolean;
  pretty?: boolean;
  xmlDeclaration?: boolean;
  container?: "svg" | "svg-viewbox" | "g" | "none";
}
export default class QRCode {
  constructor(options: QRCodeOptions | string);
  options: Required<QRCodeOptions>;
  qrcode: { modules: boolean[][] };
  svg(opt?: { container?: QRCodeOptions["container"] }): string;
}
