"""Prevent browser and importer settings from silently targeting different data."""


def validate_project_urls(api_url, frontend_url):
    if (
        api_url
        and frontend_url
        and api_url.rstrip("/").casefold() != frontend_url.rstrip("/").casefold()
    ):
        raise ValueError(
            "Dashboard and importer use different Supabase projects. Align VITE_SUPABASE_URL and SUPABASE_URL before syncing."
        )
