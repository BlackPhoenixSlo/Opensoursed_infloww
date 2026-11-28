import { SUPPORT_PHOTO_SIDE } from "./supportReducer";

export async function toJpeg(file: Blob, side = SUPPORT_PHOTO_SIDE): Promise<Blob> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("That file isn't a photo."));
      i.src = url;
    });
    const k = Math.min(1, side / Math.max(img.naturalWidth, img.naturalHeight, 1));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(img.naturalWidth * k));
    c.height = Math.max(1, Math.round(img.naturalHeight * k));
    const g = c.getContext("2d");
    if (!g) throw new Error("Couldn't read that photo.");
    g.fillStyle = "#fff";
    g.fillRect(0, 0, c.width, c.height);
    g.drawImage(img, 0, 0, c.width, c.height);
    return await new Promise<Blob>((resolve, reject) => {
      c.toBlob((b) => (b ? resolve(b) : reject(new Error("Couldn't read that photo."))), "image/jpeg", 0.85);
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function imageFiles(list: FileList | File[] | null | undefined): File[] {
  return Array.from(list ?? []).filter((f) => f.type.startsWith("image/"));
}
