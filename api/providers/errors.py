"""Keep credentials out of provider errors, reports and progress output."""

import os
import re


def safe_error(error):
    text = str(error)
    for name in (
        "THE_ODDS_API_KEY",
        "API_SPORTS_KEY",
        "API_SPORTS_MMA_KEY",
        "APISPORTS_KEY",
        "APISPORTS_MMA_KEY",
        "API_MMA_KEY",
        "SUPABASE_SERVICE_KEY",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ACCESS_TOKEN",
        "DISCORD_BOT_TOKEN",
    ):
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "[redacted]")
    text = re.sub(
        r"(?i)([?&](?:apikey|api_key|token|access_token|key)=)[^&\s'\"]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer|bot)\s+)[^\s'\"]+",
        r"\1[redacted]",
        text,
    )
    return text
