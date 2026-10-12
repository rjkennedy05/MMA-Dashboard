import providerManifest from "../../api/providers/manifest.json";

export const ALL_PROMOTIONS_KEY = "all";

const LABELS = {
  ufc: "UFC",
  dwcs: "DWCS",
  pfl: "PFL",
  one: "ONE",
  bkfc: "BKFC",
  lfa: "LFA",
};

export const SUPPORTED_PROMOTIONS = providerManifest.active_promotions.map((key) => ({
  key,
  label: LABELS[key] ?? key.toUpperCase(),
  aliases: providerManifest.aliases[key] ?? [key],
}));

export const ARCHIVED_PROMOTION_KEYS = new Set(providerManifest.archived_promotions);
export const PROVIDER_CORE_VERSION = providerManifest.provider_core_version;

export function getPromotionKey(name) {
  const normalizedName = name
    ?.trim()
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/\s+/g, " ");

  if (!normalizedName) {
    return null;
  }

  // Providers use several DWCS labels, sometimes prefixed with
  // "UFC". Classify Contender Series before the general UFC alias.
  if (normalizedName.includes("contender series")) {
    return "dwcs";
  }

  return (
    SUPPORTED_PROMOTIONS.find((promotion) =>
      promotion.aliases.some(
        (alias) => {
          const normalizedAlias = alias.replace(/[’']/g, "");

          return (
            normalizedName === normalizedAlias ||
            normalizedName.startsWith(`${normalizedAlias} `)
          );
        }
      )
    )?.key ?? null
  );
}

export function getPromotionLabel(key) {
  return (
    SUPPORTED_PROMOTIONS.find(
      (promotion) => promotion.key === key
    )?.label ?? "Other"
  );
}
