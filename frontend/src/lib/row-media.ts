import type { RowReadResponse } from "@/lib/types";

const PHOTO_COLUMN_NAMES = new Set([
  "foto",
  "foto_complementar",
  "foto_complementar_memento",
  "imagem",
  "image",
  "photo",
]);

const PHOTO_COLUMN_TOKENS = ["foto", "imagem", "image", "photo", "memento"];
const QUOTED_VALUE_PATTERN = /'([^']*)'|"([^"]*)"/g;
const HTTP_URL_PATTERN = /https?:\/\/[^\s"',\]]+/gi;
const DATA_IMAGE_PATTERN = /^data:image(?:\/[a-z0-9.+-]+)?;base64,[a-z0-9+/=\s]+$/i;
const RAW_BASE64_IMAGE_PATTERN = /^[a-z0-9+/=\s]+$/i;

function normalizeColumnName(columnName: string): string {
  return columnName
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function isLikelyPhotoColumn(columnName: string): boolean {
  const normalizedName = normalizeColumnName(columnName);
  return (
    PHOTO_COLUMN_NAMES.has(normalizedName) ||
    PHOTO_COLUMN_TOKENS.some((token) => normalizedName.includes(token))
  );
}

function trimUrlCandidate(url: string): string {
  return url.replace(/[).;]+$/g, "");
}

function appendUniqueSource(target: string[], source: string): void {
  if (!target.includes(source)) {
    target.push(source);
  }
}

function extractQuotedCandidates(rawValue: string): string[] {
  return Array.from(rawValue.matchAll(QUOTED_VALUE_PATTERN), (match) =>
    (match[1] || match[2] || "").trim(),
  ).filter(Boolean);
}

function extractCandidateSources(candidate: string): string[] {
  const value = candidate.trim();
  if (!value) {
    return [];
  }

  if (DATA_IMAGE_PATTERN.test(value)) {
    return [value.replace(/\s/g, "")];
  }

  const httpMatches = Array.from(value.matchAll(HTTP_URL_PATTERN), (match) =>
    trimUrlCandidate(match[0]),
  );
  if (httpMatches.length > 0) {
    return httpMatches;
  }

  const compactValue = value.replace(/\s/g, "");
  if (compactValue.length >= 120 && RAW_BASE64_IMAGE_PATTERN.test(compactValue)) {
    return [`data:image/jpeg;base64,${compactValue}`];
  }

  return [];
}

export function extractRenderableImageSources(rawValue: string): string[] {
  const value = rawValue.trim();
  if (!value) {
    return [];
  }

  const sources: string[] = [];
  const candidates = extractQuotedCandidates(value);
  const valuesToInspect = candidates.length > 0 ? [...candidates, value] : [value];

  for (const candidate of valuesToInspect) {
    for (const source of extractCandidateSources(candidate)) {
      appendUniqueSource(sources, source);
    }
  }

  return sources;
}

export function extractRenderableImageSource(rawValue: string): string | null {
  return extractRenderableImageSources(rawValue)[0] || null;
}

export function resolveRowPhotoSources(rowPayload: RowReadResponse): string[] {
  const sources: string[] = [];

  for (const [columnName, value] of Object.entries(rowPayload.row)) {
    if (!isLikelyPhotoColumn(columnName)) {
      continue;
    }

    for (const photoSource of extractRenderableImageSources(value)) {
      appendUniqueSource(sources, photoSource);
    }
  }

  return sources;
}

export function resolveRowPhotoSource(rowPayload: RowReadResponse): string | null {
  return resolveRowPhotoSources(rowPayload)[0] || null;
}
