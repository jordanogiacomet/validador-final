import type { BannerState } from "@/lib/types";

interface StateBannerProps {
  banner: BannerState | null;
}

export function StateBanner({ banner }: StateBannerProps) {
  if (!banner) {
    return null;
  }

  return (
    <section className={`panel state-banner ${banner.kind}`}>
      <small>Estado do lote</small>
      <strong>{banner.label}</strong>
      <p>{banner.detail}</p>
    </section>
  );
}
