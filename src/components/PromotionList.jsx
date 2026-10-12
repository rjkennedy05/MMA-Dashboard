import {
  ALL_PROMOTIONS_KEY,
  SUPPORTED_PROMOTIONS,
} from "../config/promotions";

export default function PromotionList({
  selectedPromotionKey,
  onSelectPromotion,
}) {
  const promotions = [
    {
      key: ALL_PROMOTIONS_KEY,
      label: "All cards",
    },
    ...SUPPORTED_PROMOTIONS,
  ];

  return (
    <nav
      className="promotion-filter"
      aria-label="Promotion filters"
    >
      {promotions.map((promotion) => {
        const isSelected =
          promotion.key === selectedPromotionKey;

        return (
          <button
            type="button"
            key={promotion.key}
            className={[
              "promotion-filter-button",
              isSelected
                ? "promotion-filter-button-selected"
                : "",
            ]
              .filter(Boolean)
              .join(" ")}
            aria-pressed={isSelected}
            onClick={() =>
              onSelectPromotion(promotion.key)
            }
          >
            {promotion.label}
          </button>
        );
      })}
    </nav>
  );
}
