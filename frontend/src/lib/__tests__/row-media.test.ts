import { describe, expect, it } from "vitest";

import {
  extractRenderableImageSources,
  extractRenderableImageSource,
  resolveRowPhotoSources,
  resolveRowPhotoSource,
} from "@/lib/row-media";
import type { RowReadResponse } from "@/lib/types";

function buildRowPayload(row: Record<string, string>): RowReadResponse {
  return {
    job_id: "job-1",
    row_index: 0,
    row,
    resolved_columns: {},
  };
}

describe("row media helpers", () => {
  it("extracts every renderable image from a mixed Redesim memento list", () => {
    expect(
      extractRenderableImageSources(
        "['/data/user/0/app/image.jpg', 'https://example.com/item-one.jpg?alt=media&token=abc', 'https://example.com/item-two.jpg']",
      ),
    ).toEqual([
      "https://example.com/item-one.jpg?alt=media&token=abc",
      "https://example.com/item-two.jpg",
    ]);
  });

  it("keeps first-photo compatibility for existing consumers", () => {
    expect(
      extractRenderableImageSource(
        "['/data/user/0/app/image.jpg', 'https://example.com/item.jpg?alt=media&token=abc']",
      ),
    ).toBe("https://example.com/item.jpg?alt=media&token=abc");
  });

  it("ignores local app paths because the browser cannot render them from the CSV", () => {
    expect(
      extractRenderableImageSource(
        "['/data/user/0/com.apollogestao.inventario/app_flutter/images/1773950963916.jpg']",
      ),
    ).toBeNull();
  });

  it("keeps data image URLs renderable", () => {
    expect(
      extractRenderableImageSource("data:image/png;base64,aGVsbG8="),
    ).toBe("data:image/png;base64,aGVsbG8=");
  });

  it("accepts data image URLs without an explicit mime subtype", () => {
    expect(extractRenderableImageSources("['data:image;base64,aGVsbG8=']")).toEqual([
      "data:image;base64,aGVsbG8=",
    ]);
  });

  it("wraps long raw base64 values as a JPEG data URL", () => {
    const rawBase64 = "a".repeat(120);
    expect(extractRenderableImageSource(rawBase64)).toBe(
      `data:image/jpeg;base64,${rawBase64}`,
    );
  });

  it("resolves every renderable image across photo-like columns", () => {
    const rowPayload = buildRowPayload({
      item: "110007510",
      foto_complementar_memento:
        "['https://example.com/photo-one.jpg', 'https://example.com/photo-two.jpg']",
      imagem_url: "['https://example.com/photo-two.jpg', '/data/user/0/app/image.jpg']",
    });

    expect(resolveRowPhotoSources(rowPayload)).toEqual([
      "https://example.com/photo-one.jpg",
      "https://example.com/photo-two.jpg",
    ]);
    expect(resolveRowPhotoSource(rowPayload)).toBe("https://example.com/photo-one.jpg");
  });

  it("returns null when no photo-like column has a renderable value", () => {
    const rowPayload = buildRowPayload({
      item: "110007510",
      foto_complementar_memento:
        "['/data/user/0/com.apollogestao.inventario/app_flutter/images/1773950963916.jpg']",
    });

    expect(resolveRowPhotoSource(rowPayload)).toBeNull();
  });
});
