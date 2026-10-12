import {
  ExternalLink,
  Newspaper,
  PlaySquare,
  Search,
} from "lucide-react";

import { getPromotionKey } from "../config/promotions";

function googleSearch(query) {
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}

const PROMOTION_SOURCES = {
  ufc: {
    label: "UFCStats",
    detail: "Official metrics",
    domain: "ufcstats.com",
  },
  dwcs: {
    label: "UFCStats",
    detail: "Official metrics",
    domain: "ufcstats.com",
  },
  pfl: {
    label: "PFL",
    detail: "Official profile",
    domain: "pflmma.com",
  },
  one: {
    label: "ONE",
    detail: "Official profile",
    domain: "onefc.com",
  },
  bkfc: {
    label: "BKFC",
    detail: "Official profile",
    domain: "bkfc.com",
  },
  lfa: {
    label: "LFA",
    detail: "Promotion source",
    domain: "lfafighting.com",
  },
};

function buildLinks(fighterName, opponentName, promotionName) {
  const matchup = `${fighterName} vs ${opponentName}`;
  const promotionKey = getPromotionKey(promotionName);
  const promotionSource =
    PROMOTION_SOURCES[promotionKey] ?? PROMOTION_SOURCES.ufc;

  return [
    {
      label: "Tapology",
      detail: "Record & opponents",
      href: googleSearch(`site:tapology.com ${fighterName}`),
      icon: Search,
    },
    {
      label: "ESPN",
      detail: "Profile & stats",
      href: googleSearch(`site:espn.com/mma ${fighterName}`),
      icon: Search,
    },
    {
      label: promotionSource.label,
      detail: promotionSource.detail,
      href: googleSearch(`site:${promotionSource.domain} ${fighterName}`),
      icon: Search,
    },
    {
      label: "FightOdds",
      detail: "Line movement",
      href: googleSearch(`site:fightodds.io ${matchup}`),
      icon: Search,
    },
    {
      label: "X / Clips",
      detail: "Tape & current buzz",
      href: `https://x.com/search?q=${encodeURIComponent(`${fighterName} fight`)}&src=typed_query`,
      icon: PlaySquare,
    },
    {
      label: "YouTube",
      detail: "Fight tape",
      href: `https://www.youtube.com/results?search_query=${encodeURIComponent(`${fighterName} full fight`)}`,
      icon: PlaySquare,
    },
    {
      label: "Recent News",
      detail: "Camp & interviews",
      href: `https://news.google.com/search?q=${encodeURIComponent(fighterName)}`,
      icon: Newspaper,
    },
  ];
}

export default function ResearchLinks({ fighter, opponent, promotionName }) {
  const links = buildLinks(
    fighter.full_name,
    opponent.full_name,
    promotionName
  );

  return (
    <nav className="research-link-list" aria-label={`${fighter.full_name} research links`}>
      {links.map(({ label, detail, href, icon: Icon }) => (
        <a
          key={label}
          className="research-link"
          href={href}
          target="_blank"
          rel="noreferrer"
        >
          <Icon size={16} aria-hidden="true" />
          <span>
            <strong>{label}</strong>
            <small>{detail}</small>
          </span>
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      ))}
    </nav>
  );
}
